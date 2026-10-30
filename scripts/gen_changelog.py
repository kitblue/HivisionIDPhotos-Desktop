# -*- coding: utf-8 -*-
"""从 GitHub 提交记录自动生成 CHANGELOG.md

用法：
    python scripts/gen_changelog.py                                  # 按 tag 自动分段
    python scripts/gen_changelog.py --version 1.1.0                  # 未发版提交归到 v1.1.0
    python scripts/gen_changelog.py --repo kitblue/HivisionIDPhotos-Desktop --out CHANGELOG.md
    python scripts/gen_changelog.py --dry-run                        # 只打印不写盘

凭据来源（按顺序）：
    1. 环境变量 GITHUB_TOKEN / GH_TOKEN
    2. Windows 凭据管理器里 git:https://github.com 的密码（Git Credential Manager 存的 PAT）

提交信息按 Conventional Commits 归类：feat / fix / perf / refactor / docs / build / style / test / chore。
"""

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CATEGORIES = [
    ("feat", "新增功能"),
    ("fix", "问题修复"),
    ("perf", "性能优化"),
    ("refactor", "重构"),
    ("docs", "文档"),
    ("build", "构建与打包"),
    ("style", "界面与样式"),
    ("test", "测试"),
    ("chore", "杂项"),
]

SKIP_PREFIX = ("docs(changelog)", "chore(release)")

HEADER = """# 更新日志

本文件由 `scripts/gen_changelog.py` 依据仓库提交记录自动生成，请勿手工编辑。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

"""


# ---------------------------------------------------------------- 凭据
class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def token_from_credential_manager():
    if sys.platform != "win32":
        return None
    advapi = ctypes.windll.advapi32
    for target in ("git:https://github.com", "LegacyGeneric:target=git:https://github.com"):
        ptr = ctypes.POINTER(CREDENTIAL)()
        if not advapi.CredReadW(ctypes.c_wchar_p(target), 1, 0, ctypes.byref(ptr)):
            continue
        try:
            cred = ptr.contents
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            secret = raw.decode("utf-16-le", "replace").strip()
            if secret:
                return secret
        finally:
            advapi.CredFree(ptr)
    return None


def resolve_token(explicit=None):
    if explicit:
        return explicit
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(env, "").strip()
        if val:
            return val
    return token_from_credential_manager()


# ---------------------------------------------------------------- API
def api(url, token, retries=2):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HivisionIDPhotos-Desktop-changelog",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()[:200].decode("utf-8", "replace")
            raise RuntimeError("GitHub API %s -> HTTP %s %s" % (url, exc.code, body))
        except Exception as exc:  # noqa: BLE001 - 网络抖动重试
            last = exc
    raise RuntimeError("GitHub API 失败：%s（%s）" % (url, last))


def fetch_commits(repo, token, branch="main", max_pages=5):
    commits = []
    for page in range(1, max_pages + 1):
        url = "https://api.github.com/repos/%s/commits?sha=%s&per_page=100&page=%d" % (repo, branch, page)
        batch = api(url, token)
        if not batch:
            break
        commits.extend(batch)
        if len(batch) < 100:
            break
    return commits


def fetch_tags(repo, token):
    """返回 [{name, sha}]，按提交时间倒序"""
    tags = api("https://api.github.com/repos/%s/tags?per_page=100" % repo, token)
    out = []
    for tag in tags:
        name = tag.get("name", "")
        sha = (tag.get("commit") or {}).get("sha")
        if not name or not sha:
            continue
        try:
            detail = api("https://api.github.com/repos/%s/commits/%s" % (repo, sha), token)
            date = ((detail.get("commit") or {}).get("committer") or {}).get("date", "")
        except RuntimeError:
            date = ""
        out.append({"name": name, "sha": sha, "date": date})
    out.sort(key=lambda t: t["date"] or "", reverse=True)
    return out


# ---------------------------------------------------------------- 解析
PATTERN = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<subject>.+)$")


def parse_commit(commit):
    msg = ((commit.get("commit") or {}).get("message") or "").strip()
    if not msg:
        return None
    first = msg.splitlines()[0].strip()
    if first.startswith(SKIP_PREFIX) or first.lower().startswith("merge "):
        return None
    m = PATTERN.match(first)
    if m:
        ctype = m.group("type").lower()
        scope = m.group("scope") or ""
        subject = m.group("subject").strip()
    else:
        ctype, scope, subject = "chore", "", first
    known = {c for c, _ in CATEGORIES}
    if ctype not in known:
        ctype = "chore"
    date = ((commit.get("commit") or {}).get("committer") or {}).get("date", "")[:10]
    return {"type": ctype, "scope": scope, "subject": subject, "date": date,
            "sha": (commit.get("sha") or "")[:7]}


def clean_subject(subject):
    return subject[0].upper() + subject[1:] if subject else subject


def render_section(title, date, commits):
    lines = ["## %s%s" % (title, " - " + date if date else ""), ""]
    grouped = {}
    for c in commits:
        grouped.setdefault(c["type"], []).append(c)
    if not commits:
        lines.append("_本版本无提交记录_")
        lines.append("")
        return lines
    for ctype, label in CATEGORIES:
        items = grouped.get(ctype)
        if not items:
            continue
        lines.append("### " + label)
        lines.append("")
        for item in items:
            scope = "**%s**：" % item["scope"] if item["scope"] else ""
            lines.append("- %s%s（`%s`）" % (scope, clean_subject(item["subject"]), item["sha"]))
        lines.append("")
    return lines


def build_changelog(repo, token, branch, unreleased_version):
    commits = fetch_commits(repo, token, branch)
    if not commits:
        raise RuntimeError("未取到任何提交，检查仓库名与分支")

    tags = []
    try:
        tags = fetch_tags(repo, token)
    except RuntimeError as exc:
        print("警告：读取 tag 失败，全部按当前版本处理：%s" % exc)

    parsed = [p for p in (parse_commit(c) for c in commits) if p]

    # 以 tag 的 sha 为界切段
    sections = []
    current = []
    tag_index = {}
    for tag in tags:
        tag_index[tag["sha"]] = tag
    for commit in commits:
        tag = tag_index.get(commit.get("sha"))
        if tag:
            if current or not sections:
                sections.append((None, current))
                current = []
            sections.append((tag, [commit]))
            continue
        if sections and sections[-1][0] is not None:
            sections[-1][1].append(commit)
        else:
            current.append(commit)
    if current or not sections:
        sections.insert(0, (None, current))

    # 提交 -> 解析结果映射，保持顺序
    def to_parsed(group):
        out = []
        for c in group:
            p = parse_commit(c)
            if p:
                out.append(p)
        return out

    lines = [HEADER]
    first = True
    for tag, group in sections:
        items = to_parsed(group)
        if tag is None:
            if not items:
                continue
            title = unreleased_version or "未发布"
            if unreleased_version and not title.lower().startswith("v"):
                title = "v" + title
            date = items[0]["date"]
        else:
            title = tag["name"]
            date = (tag["date"] or "")[:10]
        if first and tag is None and unreleased_version:
            pass
        lines.extend(render_section(title, date, items))
        first = False

    if not any(line.startswith("## ") for line in lines):
        lines.extend(render_section(unreleased_version or "未发布", "", parsed))

    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="从 GitHub 提交自动生成 CHANGELOG.md")
    ap.add_argument("--repo", default="kitblue/HivisionIDPhotos-Desktop")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--version", default=None, help="未打 tag 的最新提交归入的版本号，如 1.1.0")
    ap.add_argument("--out", default=os.path.join(BASE, "CHANGELOG.md"))
    ap.add_argument("--token", default=None, help="GitHub PAT，缺省读环境变量或凭据管理器")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = resolve_token(args.token)
    if not token:
        print("未取得 GitHub 凭据：请设置 GITHUB_TOKEN，或在凭据管理器保存 github 账号密码。")
        return 2
    print("凭据：已就绪（长度 %d）" % len(token))

    text = build_changelog(args.repo, token, args.branch, args.version)
    if args.dry_run:
        print(text)
        return 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("已写入：%s（%d 字符）" % (args.out, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
