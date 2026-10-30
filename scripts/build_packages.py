# -*- coding: utf-8 -*-
"""一键构建两个发行包：带模型（full）与不带模型（slim）

用法：
    python scripts/build_packages.py                     # 两个包都构建
    python scripts/build_packages.py --variant slim      # 只构建不带模型的
    python scripts/build_packages.py --variant full --no-zip
    python scripts/build_packages.py --python runtime\\python.exe

产物：
    output/HivisionIDPhotos-v<ver>-slim/HivisionIDPhotos.exe   （不含 onnx，几十 MB）
    output/HivisionIDPhotos-v<ver>-full/HivisionIDPhotos.exe   （内置全部 onnx）
    output/HivisionIDPhotos-v<ver>-slim.zip
    output/HivisionIDPhotos-v<ver>-full.zip

两个包代码完全一致，差别只在 _internal/hivision/creator/**/weights/*.onnx 是否存在。
slim 包首次运行按需在线下载，或导入官方模型包 zip（界面「导入模型包」按钮）。
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE, "output")
BUILD = os.path.join(BASE, "build")

WEIGHT_DIRS = [
    os.path.join("hivision", "creator", "weights"),
    os.path.join("hivision", "creator", "retinaface", "weights"),
]

USAGE_SLIM = """HivisionIDPhotos 桌面版 v{ver}（精简包 / 不含模型）

本包不包含 onnx 模型权重，首次运行请任选一种方式补齐模型：
  1. 程序启动时提示「需要下载模型」，点「是」按官方源下载（约 25MB 起，选大模型需 200MB+）；
  2. 界面左侧「AI 模型」卡片 -> 「下载 / 补齐模型」；
  3. 已下载官方模型包 hivision-models-v{ver}.zip 的话，点「导入模型包（.zip）…」，
     或把 zip 放到本程序目录下的 models\\ 文件夹，下次启动自动导入。

网络不佳可在启动前设置镜像前缀：
  set HV_MODEL_MIRROR=https://ghfast.top/

模型齐全后完全离线推理，照片不上传。
"""

USAGE_FULL = """HivisionIDPhotos 桌面版 v{ver}（完整包 / 内置模型）

本包已内置全部 5 个模型权重，解压后双击 HivisionIDPhotos.exe 即可离线使用，
无需联网、无需下载。

若需更换或修复模型，可用「导入模型包（.zip）…」重新导入官方模型包。

【目录里两个 exe 的区别】
  HivisionIDPhotos.exe        启动器，请双击这个（会自动处理长路径问题）
  HivisionIDPhotos.real.exe   真正的主程序，请勿直接双击或删除

【路径过长怎么办】
Windows 单条路径上限为 260 字符。启动器会先把程序目录转换成 8.3 短路径再拉
起主程序，所以即使解压在较深的目录里通常也能正常运行。
若该磁盘关闭了 8.3 短名支持，或仍提示「文件名或扩展名太长」，请把整个文件夹
移到磁盘根目录附近再运行，例如 D:\\HivisionIDPhotos。

照片默认输出到程序目录下的「照片输出」文件夹。
"""


def read_version():
    path = os.path.join(BASE, "app", "desktop_app.py")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def fmt(n):
    if n >= 1024 ** 3:
        return "%.2fGB" % (n / 1024.0 ** 3)
    return "%.1fMB" % (n / 1048576.0)


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def strip_weights(pkg_dir):
    """删掉 _internal 下的模型权重，得到 slim 包"""
    internal = os.path.join(pkg_dir, "_internal")
    removed = []
    for rel in WEIGHT_DIRS:
        folder = os.path.join(internal, rel)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower().endswith(".onnx"):
                path = os.path.join(folder, f)
                removed.append((f, os.path.getsize(path)))
                os.remove(path)
    return removed


def install_launcher(pkg_dir):
    """把主程序改名，装入 8.3 短路径启动器，规避 MAX_PATH(260) 限制。

    路径过长时 PyInstaller 引导程序在加载 python311.dll / base_library.zip 时就会失败，
    Python 层代码来不及执行，因此只能由外层 exe 先把目录换成短路径再拉起主程序。
    """
    launcher = os.path.join(BASE, "scripts", "launcher", "Launcher.exe")
    main_exe = os.path.join(pkg_dir, "HivisionIDPhotos.exe")
    if not os.path.isfile(launcher):
        print("警告：未找到 scripts\\launcher\\Launcher.exe，跳过长路径启动器")
        return False
    if not os.path.isfile(main_exe):
        print("警告：未找到主程序 exe，跳过长路径启动器")
        return False
    real_exe = os.path.join(pkg_dir, "HivisionIDPhotos.real.exe")
    if os.path.exists(real_exe):
        os.remove(real_exe)
    os.rename(main_exe, real_exe)
    shutil.copy2(launcher, main_exe)
    print("已装入长路径启动器：HivisionIDPhotos.exe -> HivisionIDPhotos.real.exe")
    return True


def zip_dir(src_dir, out_zip, top_name):
    """打包成 zip，顶层目录为 top_name，方便用户直接解压"""
    files = []
    for root, _dirs, names in os.walk(src_dir):
        for f in names:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src_dir).replace("\\", "/")
            files.append((full, top_name + "/" + rel))
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for full, rel in files:
            zf.write(full, rel)
    return len(files), os.path.getsize(out_zip)


def run_build(python, name, distpath, workpath, specpath, log=print):
    cmd = [
        python, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--runtime-hook", os.path.join(BASE, "app", "pyi_rth_shortpath.py"),
        "--name", name,
        "--icon", os.path.join(BASE, "app", "assets", "hivisionai.ico"),
        "--add-data", os.path.join(BASE, "app", "assets") + ";assets",
        "--add-data", os.path.join(BASE, "app", "demo") + ";demo",
        "--add-data", os.path.join(BASE, "app", "hivision") + ";hivision",
        "--hidden-import", "mtcnnruntime",
        "--collect-all", "mtcnnruntime",
        "--distpath", distpath,
        "--workpath", workpath,
        "--specpath", specpath,
        os.path.join(BASE, "app", "desktop_app.py"),
    ]
    log("执行：PyInstaller --onedir %s" % name)
    proc = subprocess.run(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-6:]
    for line in tail:
        log("  " + line)
    if proc.returncode != 0:
        raise SystemExit("PyInstaller 失败，返回码 %d" % proc.returncode)


def build_variant(variant, version, python, keep_dir, do_zip):
    t0 = time.time()
    name = "HivisionIDPhotos"
    dist = os.path.join(BUILD, "dist-" + variant)
    work = os.path.join(BUILD, "work-" + variant)
    spec = os.path.join(BUILD, "spec-" + variant)
    for path in (dist, work, spec):
        if os.path.isdir(path):
            shutil.rmtree(path)

    print("\n=== 构建 %s 包 ===" % variant)
    run_build(python, name, dist, work, spec)

    pkg = os.path.join(dist, name)
    removed = []
    if variant == "slim":
        removed = strip_weights(pkg)
        print("剥离权重：%d 个文件 %s" % (len(removed), fmt(sum(s for _f, s in removed))))

    target_name = "HivisionIDPhotos-v%s-%s" % (version, variant)
    target = os.path.join(OUTPUT, target_name)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(OUTPUT, exist_ok=True)
    shutil.move(pkg, target)
    install_launcher(target)

    usage = USAGE_SLIM if variant == "slim" else USAGE_FULL
    with open(os.path.join(target, "使用说明.txt"), "w", encoding="utf-8") as fh:
        fh.write(usage.format(ver=version))

    size = dir_size(target)
    print("目录：%s（%s）" % (target, fmt(size)))

    zip_info = None
    if do_zip:
        out_zip = os.path.join(OUTPUT, target_name + ".zip")
        if os.path.exists(out_zip):
            os.remove(out_zip)
        print("压缩中…")
        count, zsize = zip_dir(target, out_zip, target_name)
        zip_info = (out_zip, zsize, count)
        print("压缩包：%s（%s，%d 个文件）" % (out_zip, fmt(zsize), count))

    if not keep_dir and do_zip:
        shutil.rmtree(target)
        print("已删除中间目录，仅保留压缩包")

    print("耗时 %.1f 秒" % (time.time() - t0))
    return {"variant": variant, "dir": target if keep_dir or not do_zip else None,
            "size": size, "zip": zip_info, "removed": removed}


def main():
    ap = argparse.ArgumentParser(description="构建带模型 / 不带模型两个发行包")
    ap.add_argument("--variant", choices=["full", "slim", "both"], default="both")
    ap.add_argument("--version", default=None)
    ap.add_argument("--python", default=os.path.join(BASE, "runtime", "python.exe"),
                    help="用于 PyInstaller 的 Python 解释器")
    ap.add_argument("--no-zip", action="store_true", help="只出目录，不压缩")
    ap.add_argument("--keep-dir", action="store_true", help="压缩后保留解压目录")
    args = ap.parse_args()

    version = args.version or read_version()
    variants = ["slim", "full"] if args.variant == "both" else [args.variant]
    print("版本：%s    发行包：%s" % (version, ", ".join(variants)))

    results = []
    for variant in variants:
        results.append(build_variant(variant, version, args.python,
                                     args.keep_dir, not args.no_zip))

    print("\n=== 汇总 ===")
    for r in results:
        line = "%-5s 目录体积 %s" % (r["variant"], fmt(r["size"]))
        if r["zip"]:
            line += "    zip %s：%s" % (os.path.basename(r["zip"][0]), fmt(r["zip"][1]))
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
