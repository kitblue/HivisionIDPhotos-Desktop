# -*- coding: utf-8 -*-
"""把本地已下载的权重打包成「模型包」（hivision-models-vX.zip）

用法：
    python scripts/pack_models.py                          # 打全部已存在的权重
    python scripts/pack_models.py --model hivision_modnet   # 只打指定模型
    python scripts/pack_models.py --out output/hivision-models-v1.1.0.zip --version 1.1.0
    python scripts/pack_models.py --verify                  # 打完顺带校验 sha256

模型包内结构（与程序资源目录一致，解压即用）：
    manifest.json
    hivision/creator/weights/*.onnx
    hivision/creator/retinaface/weights/retinaface-resnet50.onnx
"""

import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "app"))

from model_bundle import build, bundle_name, verify  # noqa: E402
from model_manager import MODELS  # noqa: E402


def _fmt(n):
    return "%.1fMB" % (n / 1048576.0)


def read_version():
    path = os.path.join(BASE, "app", "desktop_app.py")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def main():
    ap = argparse.ArgumentParser(description="生成 HivisionIDPhotos 桌面版模型包")
    ap.add_argument("--version", default=None, help="版本号，默认取 desktop_app.py 里的 APP_VERSION")
    ap.add_argument("--out", default=None, help="输出 zip 路径，默认 output/<模型包名>")
    ap.add_argument("--model", nargs="*", default=None, help="只打包指定模型名")
    ap.add_argument("--verify", action="store_true", help="打包后校验（含 sha256）")
    args = ap.parse_args()

    version = args.version or read_version()
    out = args.out or os.path.join(BASE, "output", bundle_name(version))

    names = args.model or list(MODELS)
    unknown = [n for n in names if n not in MODELS]
    if unknown:
        print("未知模型：%s" % ", ".join(unknown))
        return 2

    src = os.path.join(BASE, "app")  # 资源根：其下即有 hivision/creator/weights
    print("模型包版本：%s" % version)
    print("扫描权重目录：%s" % os.path.join(src, "hivision", "creator", "weights"))
    result = build(src, out, version, names=names, log=lambda m: print("  " + m))

    print("-" * 56)
    print("模型包：%s" % result["path"])
    print("包含模型：%d 个 -> %s" % (result["count"], ", ".join(result["files"])))
    print("压缩体积：%s" % _fmt(result["bytes"]))
    if result["missing"]:
        print("未打包（本地不存在）：%s" % ", ".join(result["missing"]))

    if args.verify:
        ok, manifest, errors = verify(result["path"], check_hash=True)
        print("校验：%s" % ("通过" if ok else "失败"))
        for err in errors:
            print("  ! " + err)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
