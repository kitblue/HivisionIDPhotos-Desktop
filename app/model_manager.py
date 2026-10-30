# -*- coding: utf-8 -*-
"""模型权重在线获取模块（桌面版运行时使用）

设计原则：
    · 仓库与发行包里都不内置 onnx 权重，避免仓库膨胀、绕开 Release 附件分发限制；
    · 首次运行或切换到大模型时，按需从官方源下载到本地 weights 目录；
    · 下载失败不阻断程序启动，只提示可在「AI 模型」卡片里手动重试。

所有模型均来自其官方发布渠道（上游 Release 附件 / HuggingFace / 作者 Release），
本项目只做镜像转发，不修改权重内容。
"""

import os
import time
import urllib.error
import urllib.request

# 单个模型元信息：文件名、官方地址、预期大小（字节，用于完整性校验）、说明
MODELS = {
    "hivision_modnet": {
        "file": "hivision_modnet.onnx",
        "size": 25888609,
        "url": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx",
        "desc": "HIVISION ModNet 抠图模型（约 25MB）",
    },
    "modnet_photographic_portrait_matting": {
        "file": "modnet_photographic_portrait_matting.onnx",
        "size": 25888640,
        "url": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx",
        "desc": "ModNet 摄影人像抠图模型（约 25MB）",
    },
    "rmbg-1.4": {
        "file": "rmbg-1.4.onnx",
        "size": 176153355,
        "url": "https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx",
        "desc": "BRIA RMBG-1.4 抠图模型（约 168MB，非商用许可）",
    },
    "birefnet-v1-lite": {
        "file": "birefnet-v1-lite.onnx",
        "size": 224005088,
        "url": "https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "desc": "BiRefNet-lite 抠图模型（约 214MB）",
    },
    "retinaface-resnet50": {
        "file": "retinaface-resnet50.onnx",
        "size": 109458296,
        "url": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/retinaface-resnet50.onnx",
        "desc": "RetinaFace ResNet50 人脸检测模型（约 104MB）",
        "subdir": "retinaface",
    },
}

# 可选下载加速前缀：设置环境变量 HV_MODEL_MIRROR=https://ghfast.top/ 即可走镜像
MIRROR_ENV = "HV_MODEL_MIRROR"

CHUNK = 1024 * 256


def app_weights_root(app_root):
    """返回 weights 根目录（hivision/creator/weights）"""
    return os.path.join(app_root, "hivision", "creator", "weights")


def model_path(name, weights_root):
    info = MODELS[name]
    if info.get("subdir"):
        return os.path.join(
            os.path.dirname(weights_root), info["subdir"], "weights", info["file"]
        )
    return os.path.join(weights_root, info["file"])


def is_present(name, weights_root, tolerance=0.9):
    """文件存在且大小接近预期即视为可用（避免半截文件被判定为完整）"""
    path = model_path(name, weights_root)
    if not os.path.isfile(path):
        return False
    expect = MODELS[name]["size"]
    return os.path.getsize(path) >= expect * tolerance


def missing(weights_root, names=None):
    names = names or list(MODELS)
    return [n for n in names if not is_present(n, weights_root)]


def _urls(name):
    url = MODELS[name]["url"]
    mirror = os.environ.get(MIRROR_ENV, "").strip()
    urls = []
    if mirror:
        urls.append(mirror.rstrip("/") + "/" + url)
    urls.append(url)
    return urls


def download_one(name, weights_root, progress=None, log=None):
    """下载单个模型；progress(done, total) 回调，log(str) 回调。返回本地路径。"""
    info = MODELS[name]
    target = model_path(name, weights_root)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"

    if is_present(name, weights_root):
        if log:
            log("已存在，跳过：%s" % info["file"])
        return target

    last_err = None
    for url in _urls(name):
        for attempt in (1, 2):
            try:
                done = os.path.getsize(part) if os.path.exists(part) else 0
                req = urllib.request.Request(url, headers={"User-Agent": "HivisionIDPhotos-Desktop"})
                if done:
                    req.add_header("Range", "bytes=%d-" % done)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if done and resp.status != 206:
                        done = 0  # 服务端不支持断点续传，从头开始
                    total = int(resp.headers.get("Content-Length") or 0) + done
                    if total <= 0:
                        total = info["size"]
                    mode = "ab" if done else "wb"
                    with open(part, mode) as fh:
                        while True:
                            block = resp.read(CHUNK)
                            if not block:
                                break
                            fh.write(block)
                            done += len(block)
                            if progress:
                                progress(done, total)
                if os.path.getsize(part) < info["size"] * 0.9:
                    raise IOError("文件大小异常，可能未下载完整")
                if os.path.exists(target):
                    os.remove(target)
                os.replace(part, target)
                if log:
                    log("下载完成：%s" % info["file"])
                return target
            except Exception as exc:  # noqa: BLE001 - 网络错误统一降级重试
                last_err = exc
                if log:
                    log("下载失败（第 %d 次）：%s %s" % (attempt, url.split("/")[2], exc))
                time.sleep(1.5)
    raise IOError("模型下载失败：%s（%s）" % (info["file"], last_err))


def download_many(names, weights_root, progress=None, log=None):
    ok, failed = [], []
    for i, name in enumerate(names):
        try:
            download_one(name, weights_root, progress=progress, log=log)
            ok.append(name)
        except Exception as exc:  # noqa: BLE001
            failed.append((name, str(exc)))
            if log:
                log("跳过 %s：%s" % (name, exc))
    return ok, failed
