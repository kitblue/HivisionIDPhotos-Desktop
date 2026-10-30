# -*- coding: utf-8 -*-
"""模型包（models bundle）的生成、校验与安装

「模型包」= 一个 zip，内部结构固定为：

    manifest.json
    hivision/creator/weights/<抠图模型>.onnx
    hivision/creator/retinaface/weights/retinaface-resnet50.onnx

三处用途：
    1. 生成：把本地已下载的权重组包发版（scripts/pack_models.py）；
    2. 安装：把模型包解到程序资源目录，让「不带模型」的发行包一次变离线可用；
    3. 自动导入：程序启动时扫描 exe 同级 models/ 目录、*.zip 模型包，自动入库。

设计原则：
    · 仓库与 Git 索引里永远不出现 onnx，权重只以「模型包」形式随 Release 分发；
    · 模型包与程序资源目录的布局一一对应，安装即复制，不改 hivision 内部路径；
    · 解压只认 manifest 中登记的相对路径，拒绝绝对路径与 ../ 跳出。
"""

import hashlib
import json
import os
import shutil
import time
import zipfile

from model_manager import MODELS

MANIFEST_NAME = "manifest.json"
BUNDLE_KIND = "hivision-models"
CHUNK = 1024 * 1024


# ---------------------------------------------------------------- 路径约定
def rel_path(name):
    """模型在「程序资源根目录」下的相对路径（posix 分隔符）"""
    info = MODELS[name]
    fname = info["file"]
    if info.get("subdir"):
        return "hivision/creator/%s/weights/%s" % (info["subdir"], fname)
    return "hivision/creator/weights/%s" % fname


def abs_path(name, base_dir):
    return os.path.join(base_dir, *rel_path(name).split("/"))


def bundle_name(version):
    return "hivision-models-v%s.zip" % version


# ---------------------------------------------------------------- 工具
def _sha256(path, progress=None):
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return h.hexdigest()


def _safe_member(name):
    """只接受 manifest 里登记过的相对路径，防 zip slip"""
    if name.startswith("/") or name.startswith("\\") or ".." in name.split("/"):
        return False
    if ":" in name.split("/")[0]:  # 形如 C:/ 的盘符
        return False
    return name.startswith("hivision/")


# ---------------------------------------------------------------- 生成
def build(src_base, out_zip, version, names=None, progress=None, log=None):
    """把 src_base 下已存在的权重打成模型包。

    src_base：源码目录（含 hivision/creator/weights 的那一层）
    返回 dict：{path, version, count, bytes, missing: [...], files: [...]}
    """
    names = list(names or MODELS)
    entries, missing = [], []
    for name in names:
        path = abs_path(name, src_base)
        if not os.path.isfile(path) or os.path.getsize(path) < MODELS[name]["size"] * 0.9:
            missing.append(name)
            continue
        entries.append({
            "name": name,
            "path": rel_path(name),
            "file": MODELS[name]["file"],
            "size": os.path.getsize(path),
            "sha256": _sha256(path),
            "desc": MODELS[name]["desc"],
            "source": MODELS[name]["url"],
        })
        if log:
            log("加入模型包：%s（%.1fMB）" % (MODELS[name]["file"], entries[-1]["size"] / 1048576.0))

    if not entries:
        raise RuntimeError("没有任何可用于打包的模型权重")

    manifest = {
        "kind": BUNDLE_KIND,
        "version": version,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generator": "scripts/pack_models.py",
        "total_size": sum(e["size"] for e in entries),
        "files": entries,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_zip)) or ".", exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for e in entries:
            zf.write(abs_path(e["name"], src_base), e["path"])
            if log:
                log("已写入 %s" % e["path"])
            if progress:
                progress(e["name"])

    return {
        "path": os.path.abspath(out_zip),
        "version": version,
        "count": len(entries),
        "bytes": os.path.getsize(out_zip),
        "missing": missing,
        "files": [e["file"] for e in entries],
        "manifest": manifest,
    }


# ---------------------------------------------------------------- 读取 / 校验
def read_manifest(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        try:
            raw = zf.read(MANIFEST_NAME)
        except KeyError:
            raise ValueError("不是有效的模型包：缺少 %s" % MANIFEST_NAME)
    data = json.loads(raw.decode("utf-8"))
    if data.get("kind") != BUNDLE_KIND:
        raise ValueError("不是有效的模型包：kind=%r" % data.get("kind"))
    return data


def verify(zip_path, check_hash=False):
    """校验模型包结构；check_hash=True 时逐个算 sha256（慢，仅发版前用）"""
    manifest = read_manifest(zip_path)
    errors = []
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for item in manifest.get("files", []):
            rel = item["path"]
            if not _safe_member(rel):
                errors.append("非法路径：%s" % rel)
                continue
            if rel not in names:
                errors.append("缺少文件：%s" % rel)
                continue
            info = zf.getinfo(rel)
            if info.file_size != item["size"]:
                errors.append("大小不符：%s（%d != %d）" % (rel, info.file_size, item["size"]))
                continue
            if check_hash:
                h = hashlib.sha256()
                with zf.open(rel) as fh:
                    while True:
                        block = fh.read(CHUNK)
                        if not block:
                            break
                        h.update(block)
                if h.hexdigest() != item["sha256"]:
                    errors.append("校验和不符：%s" % rel)
    return (not errors), manifest, errors


# ---------------------------------------------------------------- 安装
def install(zip_path, dest_base, log=None, progress=None, check_hash=False):
    """把模型包安装到 dest_base（程序资源根目录）。

    返回 (installed:list[str], skipped:list[str])
    """
    ok, manifest, errors = verify(zip_path, check_hash=check_hash)
    if not ok:
        raise ValueError("模型包校验失败：\n" + "\n".join(errors))

    installed, skipped = [], []
    with zipfile.ZipFile(zip_path) as zf:
        for item in manifest.get("files", []):
            rel = item["path"]
            target = os.path.join(dest_base, *rel.split("/"))
            if os.path.isfile(target) and os.path.getsize(target) == item["size"]:
                skipped.append(rel)
                if log:
                    log("已存在，跳过：%s" % os.path.basename(rel))
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            part = target + ".part"
            with zf.open(rel) as src, open(part, "wb") as dst:
                while True:
                    block = src.read(CHUNK)
                    if not block:
                        break
                    dst.write(block)
                    if progress:
                        progress(os.path.basename(rel))
            os.replace(part, target)
            installed.append(rel)
            if log:
                log("已安装：%s（%.1fMB）" % (os.path.basename(rel), item["size"] / 1048576.0))
    return installed, skipped


def scan_dir(src_dir, dest_base, log=None, maxdepth=3):
    """把目录里的 onnx 按文件名对号入座复制进 dest_base。返回已安装的模型名。"""
    wanted = {}
    for name in MODELS:
        wanted[MODELS[name]["file"]] = name

    base_depth = src_dir.rstrip("\\/").count(os.sep)
    found = []
    for root, _dirs, files in os.walk(src_dir):
        if root.count(os.sep) - base_depth >= maxdepth:
            _dirs[:] = []
        for fname in files:
            lname = fname.lower()
            if not lname.endswith(".onnx") or fname not in wanted:
                continue
            name = wanted[fname]
            src = os.path.join(root, fname)
            if not os.path.isfile(src):
                continue
            if os.path.getsize(src) < MODELS[name]["size"] * 0.9:
                if log:
                    log("跳过（大小不足，可能是半截文件）：%s" % fname)
                continue
            target = abs_path(name, dest_base)
            if os.path.isfile(target) and os.path.getsize(target) >= MODELS[name]["size"] * 0.9:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
            found.append(name)
            if log:
                log("已导入：%s" % fname)
    return found


def auto_import(app_home, dest_base, log=None):
    """启动时自动导入：扫描 exe 同级目录（或源码目录）的模型包与散装权重。

    约定位置（按优先级）：
        <app_home>/models/            目录，内含 onnx 或模型包 zip
        <app_home>/models/*.zip
        <app_home>/*models*.zip
        <app_home>/                    直接散放 onnx
        环境变量 HV_MODELS_DIR         指向上述任一形态的目录

    返回 (summary:list[str], installed:list[str])
    """
    summary, installed = [], []
    candidates = []

    env_dir = os.environ.get("HV_MODELS_DIR", "").strip()
    if env_dir:
        candidates.append(env_dir)
    candidates.append(os.path.join(app_home, "models"))
    candidates.append(app_home)

    seen = set()
    for cand in candidates:
        if not cand or not os.path.isdir(cand):
            continue
        real = os.path.abspath(cand)
        if real in seen:
            continue
        seen.add(real)

        # 1) 目录内的模型包 zip
        zips = []
        try:
            for fname in os.listdir(real):
                if fname.lower().endswith(".zip") and ("model" in fname.lower()):
                    zips.append(os.path.join(real, fname))
        except OSError:
            zips = []
        for zpath in zips:
            try:
                ins, _skip = install(zpath, dest_base, log=log)
                installed.extend(ins)
                summary.append("%s（%d 个文件）" % (os.path.basename(zpath), len(ins)))
            except Exception as exc:  # noqa: BLE001 - 单个包坏了不影响其它来源
                if log:
                    log("模型包导入失败：%s -> %s" % (os.path.basename(zpath), exc))

        # 2) 目录内的散装 onnx（含子目录）
        got = scan_dir(real, dest_base, log=log)
        if got:
            installed.extend(got)
            summary.append("%s（%d 个模型）" % (os.path.basename(real.rstrip("\\/")) or real, len(got)))

    # 去重但保序
    dedup = []
    for name in installed:
        if name not in dedup:
            dedup.append(name)
    return summary, dedup
