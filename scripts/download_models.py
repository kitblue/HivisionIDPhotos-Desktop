# -*- coding: utf-8 -*-
"""模型权重在线下载脚本（源码运行 / 打包前准备）

仓库与安装包均不内置 onnx 权重，用本脚本按需拉取：

    python scripts/download_models.py                 # 只下默认必需（hivision_modnet）
    python scripts/download_models.py --all           # 全部 5 个模型（约 535MB）
    python scripts/download_models.py --model rmbg-1.4 birefnet-v1-lite
    python scripts/download_models.py --list          # 查看可下载模型

国内网络可先设置镜像前缀再执行：
    set HV_MODEL_MIRROR=https://ghfast.top/
"""

import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "app"))

from model_manager import (  # noqa: E402
    MODELS,
    app_weights_root,
    download_many,
    is_present,
    missing,
)

DEFAULT_NAMES = ["hivision_modnet"]


def _fmt(n):
    return "%.1fMB" % (n / 1048576.0)


def show_list(weights_root):
    print("可用模型：")
    for name, info in MODELS.items():
        exist = "已下载" if is_present(name, weights_root) else "未下载"
        print("  %-38s %-8s %s" % (name, _fmt(info["size"]), existing(info, exist)))
    print("\nweights 目录：%s" % weights_root)


def existing(info, exist):
    return "%s  %s" % (exist, info["desc"])


def main():
    ap = argparse.ArgumentParser(description="在线下载 HivisionIDPhotos 桌面版模型权重")
    ap.add_argument("--model", nargs="*", default=None, help="指定模型名，可多个")
    ap.add_argument("--all", action="store_true", help="下载全部模型")
    ap.add_argument("--list", action="store_true", help="仅列出模型")
    args = ap.parse_args()

    weights_root = app_weights_root(BASE)

    if args.list:
        show_list(weights_root)
        return 0

    if args.all:
        names = list(MODELS)
    elif args.model:
        unknown = [m for m in args.model if m not in MODELS]
        if unknown:
            print("未知模型：%s\n用 --list 查看可用名" % ", ".join(unknown))
            return 2
        names = args.model
    else:
        names = DEFAULT_NAMES

    names = [n for n in names if not is_present(n, weights_root)]
    if not names:
        print("模型已齐全，无需下载：%s" % weights_root)
        return 0

    total = sum(MODELS[n]["size"] for n in names)
    print("准备下载 %d 个模型，共约 %s → %s" % (len(names), _fmt(total), weights_root))

    def progress(done, total_):
        pct = 100.0 * done / total_ if total_ else 0
        bar = "#" * int(pct / 4)
        sys.stdout.write("\r  [%-25s] %5.1f%%  %s / %s" % (bar, pct, _fmt(done), _fmt(total_)))
        sys.stdout.flush()

    ok, failed = download_many(names, weights_root, progress=progress, log=lambda m: None)
    print()
    print("完成：%d 个成功" % len(ok))
    if failed:
        print("失败：")
        for name, err in failed:
            print("  %s -> %s" % (name, err))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
