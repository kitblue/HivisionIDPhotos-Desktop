# -*- coding: utf-8 -*-
"""
HivisionIDPhotos 桌面版（Windows 原生 UI）

把网页端（Gradio）的全部证件照制作能力，实现在一个本地桌面程序里：
    · 尺寸列表 / 只换底 / 自定义 px / 自定义 mm
    · 背景色（预设 + 自定义 RGB + 自定义 HEX + 美式背景）
    · 渲染方式（纯色 / 上下渐变 / 中心渐变）
    · 相纸排版（六寸 / 五寸 / A4 / 3R / 4R）+ 裁剪线
    · 自定义 KB / DPI
    · 抠图模型 / 人脸检测模型切换
    · 美颜（美白 / 亮度 / 对比度 / 饱和度 / 锐化）+ 头身比 / 头顶留白
    · 水印（文字 / 颜色 / 字号 / 透明度 / 角度 / 间距）
    · 人脸旋转对齐 / 水平翻转 / JPEG 输出
    · 模板照（2 款）

所有推理在本地完成，内置模型，不联网、不依赖浏览器。
"""

import os
import sys
import time
import queue
import traceback
import threading

# 源码运行：资源与可写目录都是本文件所在目录
# exe 运行（PyInstaller）：资源在 _MEIPASS 解包目录，可写目录（输出照片）在 exe 同级
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    APP_HOME = os.path.dirname(os.path.abspath(sys.executable))
    BASE_DIR = getattr(sys, "_MEIPASS", APP_HOME)
else:
    APP_HOME = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = APP_HOME
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

APP_NAME = "HivisionIDPhotos 证件照制作工具（桌面版）"
APP_VERSION = "1.0.5"


def _enable_high_dpi():
    """让程序在 Windows 高 DPI 缩放下按物理像素渲染，避免被系统整体拉伸发虚。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_high_dpi()


# ---------------------------------------------------------------- 屏蔽上游 gradio 依赖
# 上游 hivision 包内若干模块（水印、美颜、retinaface）在文件尾部保留了 Gradio 演示界面，
# 导入时会执行 `with gr.Blocks()...`。桌面版不需要也不安装 gradio，
# 这里注入一个空壳模块吸收这些纯界面调用，业务函数不受影响。
def _install_gradio_stub():
    import types

    if "gradio" in sys.modules:
        return

    class _Stub(object):
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return _Stub()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __getattr__(self, name):
            return _Stub()

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

        def __iter__(self):
            return iter([])

    try:
        import gradio  # noqa: F401
    except Exception:
        module = types.ModuleType("gradio")
        module.__getattr__ = lambda name: _Stub
        sys.modules["gradio"] = module


_install_gradio_stub()

# ---------------------------------------------------------------- 依赖 & 上游模块
import numpy as np
import cv2
from PIL import Image, ImageTk

from hivision import IDCreator
from hivision.error import FaceError, APIError
from hivision.utils import (
    add_background,
    add_background_with_image,
    resize_image_to_kb,
    add_watermark,
    save_image_dpi_to_bytes,
)
from hivision.creator.layout_calculator import (
    generate_layout_array,
    generate_layout_image,
)
from hivision.creator.choose_handler import (
    choose_handler,
    HUMAN_MATTING_MODELS,
    FACE_DETECT_MODELS,
)
from hivision.plugin.template.template_calculator import generte_template_photo
from demo.locales import LOCALES

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

try:  # 高 DPI 适配
    from ctypes import windll

    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


# ---------------------------------------------------------------- 文案
def _zh(key, field="label", default=""):
    try:
        return LOCALES[key]["zh"][field]
    except Exception:
        return default


LANG = "zh"
SIZE_MODE_CHOICES = _zh("size_mode", "choices", ["尺寸列表", "只换底"]) or []
MODE_LIST, MODE_BG_ONLY, MODE_PX, MODE_MM = (SIZE_MODE_CHOICES + ["", "", "", ""])[:4]
SIZE_PRESETS = list(LOCALES["size_list"][LANG]["develop"].keys())
SIZE_PRESET_MAP = LOCALES["size_list"][LANG]["develop"]
BG_CHOICES = _zh("bg_color", "choices", ["蓝色", "白色", "红色"])
BG_HEX_MAP = LOCALES["bg_color"][LANG]["develop"]
RENDER_CHOICES = _zh("render_mode", "choices", ["纯色"])
RENDER_MODES = {0: "pure_color", 1: "updown_gradient", 2: "center_gradient"}
PRINT_CHOICES = _zh("print_switch", "choices", ["六寸", "五寸", "A4", "3R", "4R"])
PRINT_SHAPES = dict(zip(PRINT_CHOICES, LOCALES["print_switch"]["shape"]))
KB_CHOICES = _zh("image_kb", "choices", ["不设置", "自定义"])
DPI_CHOICES = _zh("image_dpi", "choices", ["不设置", "自定义"])
WM_CHOICES = _zh("watermark_switch", "choices", ["不添加", "添加"])
PLUGIN_CHOICES = _zh("plugin", "choices", ["人脸旋转对齐", "水平翻转", "排版照裁剪线", "JPEG格式"])
PLUGIN_DEFAULT = _zh("plugin", "value", [])
WM_DEFAULT_TEXT = _zh("watermark_text", "value", "仅限个人使用")

COLOR_AMERICAN = BG_CHOICES[6] if len(BG_CHOICES) > 6 else "美式证件照"
COLOR_CUSTOM_RGB = BG_CHOICES[7] if len(BG_CHOICES) > 7 else "自定义(RGB)"
COLOR_CUSTOM_HEX = BG_CHOICES[8] if len(BG_CHOICES) > 8 else "自定义(HEX)"

MATTING_MODELS = [m for m in HUMAN_MATTING_MODELS]
FACE_DETECT_MODELS = [m for m in FACE_DETECT_MODELS if "face++" not in m]
DEFAULT_MATTING = "hivision_modnet"
DEFAULT_FACE_DETECT = "mtcnn"

# 各模型特点说明（选择时在下方提示）
MATTING_MODEL_HINTS = {
    "hivision_modnet": "速度最快、内存占用最低，日常标准证件照首选",
    "modnet_photographic_portrait_matting": "人像边缘更细腻，速度中等，适合发丝较多的照片",
    "rmbg-1.4": "发丝与半透明边缘处理更强，速度较慢",
    "birefnet-v1-lite": "抠图质量最高、细节最锐利，模型最大、速度最慢",
}
FACE_DETECT_HINTS = {
    "mtcnn": "默认，轻量快速，单人正脸照片识别稳定",
    "retinaface-resnet50": "小脸、侧脸、遮挡场景更准，速度略慢、体积更大",
}

def _default_output_root():
    """优先输出到程序目录下的「照片输出」；不可写时回退到用户图片目录"""
    local = os.path.join(APP_HOME, "照片输出")
    try:
        os.makedirs(local, exist_ok=True)
        probe = os.path.join(local, ".write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("1")
        os.unlink(probe)
        return local
    except Exception:
        fallback = os.path.join(os.path.expanduser("~"), "Pictures", "HivisionIDPhotos")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback


OUTPUT_ROOT = _default_output_root()
AMERICAN_BG_PATH = os.path.join(BASE_DIR, "demo", "assets", "american-style.png")


# ---------------------------------------------------------------- 工具函数
def imread_unicode(path):
    """读取含中文路径的图片（Windows 兼容）"""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise IOError("无法读取图片：%s" % path)
    return img


def clean_preset_name(name):
    return " ".join(str(name).replace("\t", " ").split())


def hex_to_rgb(hex_color):
    """'#628bce' -> (98, 139, 206)，与上游 hex 字节序一致"""
    hex_color = str(hex_color).strip().lstrip("#")
    if len(hex_color) != 6:
        raise ValueError("HEX 颜色需为 6 位，例如 FFFFFF 或 #FFFFFF")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def np_to_pil(img, src_is_bgr=False):
    """ndarray -> PIL.Image。推理结果数组已是 RGB 序；原图来自 cv2 时传 src_is_bgr=True"""
    if img is None:
        return None
    arr = np.uint8(img)
    if arr.ndim == 2:
        return Image.fromarray(arr, mode="L")
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if src_is_bgr:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(arr)


# ---------------------------------------------------------------- 人脸定位
_MTCNN = None


def _boxes_of(faces, scale=1.0):
    """MTCNN 返回的 ndarray(N×5：x1,y1,x2,y2,score) -> [[x1,y1,x2,y2], ...]"""
    if faces is None or len(faces) == 0:
        return []
    return [[float(v) * scale for v in f[:4]] for f in np.asarray(faces, dtype=float)]


def detect_face_boxes(rgb):
    """检测图中所有人脸，返回 [(x1, y1, x2, y2), ...]；检测链路异常时返回 None"""
    global _MTCNN
    try:
        if _MTCNN is None:
            # 复用上游 face_detector 的 MTCNN 单例，避免重复加载 pnet/rnet/onet onnx
            from hivision.creator import face_detector as _fd

            _MTCNN = _fd.mtcnn if _fd.mtcnn is not None else _fd.MTCNN()
            _fd.mtcnn = _MTCNN
        h, w = rgb.shape[:2]
        small = cv2.resize(
            rgb, (max(1, w // 2), max(1, h // 2)), interpolation=cv2.INTER_AREA
        )
        faces, _ = _MTCNN.detect(small, thresholds=[0.8, 0.8, 0.8])
        boxes = _boxes_of(faces, 2.0)
        if len(boxes) != 1:
            faces2, _ = _MTCNN.detect(rgb)
            boxes = _boxes_of(faces2, 1.0)
        return boxes
    except Exception:
        return None


def crop_main_face(rgb, box, w_ratio=3.2, h_ratio=4.6):
    """按指定人脸为中心裁出单人照构图（头肩比例近似证件照）"""
    x1, y1, x2, y2 = box
    fw = max(1.0, x2 - x1)
    fh = max(1.0, y2 - y1)
    cx = (x1 + x2) / 2.0
    H, W = rgb.shape[:2]
    cw = min(float(W), fw * w_ratio)
    ch = min(float(H), fh * h_ratio)
    left = min(max(0.0, cx - cw / 2.0), W - cw)
    top = min(max(0.0, y1 - fh * (h_ratio * 0.185)), H - ch)
    crop = rgb[int(top):int(top + ch), int(left):int(left + cw)]
    if crop.size == 0:
        return rgb
    return np.ascontiguousarray(crop)


def crop_single_face(rgb, box):
    """由松到紧逐步收缩裁剪框，直到框内恰好只剩一张人脸；返回 (裁剪图, 人脸数)"""
    crop = rgb
    count = None
    for w_ratio, h_ratio in ((3.2, 4.6), (2.5, 3.6), (1.9, 2.8), (1.55, 2.3)):
        crop = crop_main_face(rgb, box, w_ratio, h_ratio)
        found = detect_face_boxes(crop)
        if found is None:
            return crop, None
        count = len(found)
        if count == 1:
            return crop, 1
    return crop, count


# ---------------------------------------------------------------- 推理引擎
class PhotoEngine(object):
    """与网页端 IDPhotoProcessor 等价，但输出纯数据、不依赖 Gradio"""

    def __init__(self):
        self._creator = None

    def _get_creator(self, matting_model, face_detect_model):
        if self._creator is None:
            self._creator = IDCreator()
        choose_handler(self._creator, matting_model, face_detect_model)
        return self._creator

    # ---- 参数解析
    def _resolve_size(self, o):
        mode = o["size_mode"]
        if mode == MODE_LIST:
            size = SIZE_PRESET_MAP[o["size_preset"]]
            return int(size[0]), int(size[1]), False
        if mode == MODE_BG_ONLY:
            return None, None, True
        if mode == MODE_PX:
            h, w = int(o["custom_px_h"]), int(o["custom_px_w"])
        else:  # mm
            h = int(round(float(o["custom_mm_h"]) / 25.4 * 300))
            w = int(round(float(o["custom_mm_w"]) / 25.4 * 300))
        if h < w or min(h, w) < 100 or max(h, w) > 1800:
            raise ValueError(
                _zh("size_mode", "custom_size_eror")
                or "宽度不应大于长度；长度和宽度不应小于100，不大于1800。"
            )
        return h, w, False

    def _resolve_color(self, o):
        """返回 (r, g, b)。上游 add_background 的三元组按 RGB 字节序生效，故直接给 RGB。"""
        color = o["bg_color"]
        if color == COLOR_CUSTOM_RGB:
            return tuple(int(max(0, min(255, o[k]))) for k in ("custom_r", "custom_g", "custom_b"))
        if color == COLOR_CUSTOM_HEX:
            return hex_to_rgb(o["custom_hex"])
        if color == COLOR_AMERICAN:
            return (255, 255, 255)
        return hex_to_rgb(BG_HEX_MAP[color])

    # ---- 主流程
    def process(self, input_bgr, o, log=print):
        """input_bgr 为 cv2 读入的 BGR 图像；返回的图像数组统一为 RGB 序"""
        t0 = time.time()
        size, change_bg_only = None, False
        h, w, change_bg_only = self._resolve_size(o)
        if not change_bg_only:
            size = (h, w)
        color_rgb = self._resolve_color(o)
        render_mode = RENDER_MODES.get(int(o["render_index"]), "pure_color")

        plugins = set(o.get("plugins") or [])
        face_alignment = PLUGIN_CHOICES[0] in plugins
        horizontal_flip = PLUGIN_CHOICES[1] in plugins
        layout_crop_line = PLUGIN_CHOICES[2] in plugins
        jpeg_format = PLUGIN_CHOICES[3] in plugins

        log("加载模型：%s / %s" % (o["matting_model"], o["face_detect_model"]))
        creator = self._get_creator(o["matting_model"], o["face_detect_model"])

        top_max = float(o["top_distance"])
        log("开始推理…")
        rgb_input = cv2.cvtColor(np.uint8(input_bgr), cv2.COLOR_BGR2RGB)

        # 上游只接受单人照：多脸时自动聚焦最大人脸，避免直接抛"人脸数不等于1"
        boxes = detect_face_boxes(rgb_input)
        if boxes is not None:
            if not boxes:
                raise RuntimeError("未检测到人脸，请换一张正脸清晰、光线充足的照片。")
            if len(boxes) > 1:
                main = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                cropped, rest = crop_single_face(rgb_input, main)
                if rest == 1:
                    rgb_input = cropped
                    log(
                        "检测到 %d 张人脸，已自动聚焦最大人脸（裁剪为 %d×%d）"
                        % (len(boxes), rgb_input.shape[1], rgb_input.shape[0])
                    )
                else:
                    log(
                        "检测到 %d 张人脸，已尝试聚焦最大人脸，但裁剪后仍残留多人，"
                        "将按原图继续处理" % len(boxes)
                    )
        try:
            result = creator(
                rgb_input,
                change_bg_only=change_bg_only,
                size=size,
                head_measure_ratio=float(o["head_ratio"]),
                head_top_range=(top_max, max(0.0, top_max - 0.02)),
                whitening_strength=int(o["whitening"]),
                brightness_strength=int(o["brightness"]),
                contrast_strength=int(o["contrast"]),
                sharpen_strength=int(o["sharpen"]),
                saturation_strength=int(o["saturation"]),
                face_alignment=face_alignment,
                horizontal_flip=horizontal_flip,
            )
        except (FaceError, APIError) as exc:
            raise RuntimeError(
                "人脸定位失败（%s）。已尝试自动聚焦单人主体，仍不满足单人照要求，"
                "请换一张只含一人、正脸清晰的照片。" % exc
            )

        standard = np.uint8(result.standard)
        hd = np.uint8(result.hd)

        # 背景
        if o["bg_color"] == COLOR_AMERICAN and os.path.exists(AMERICAN_BG_PATH):
            bg = imread_unicode(AMERICAN_BG_PATH)
            standard = np.uint8(add_background_with_image(standard, background_image=bg))
            hd = np.uint8(add_background_with_image(hd, background_image=bg))
        else:
            standard = np.uint8(add_background(standard, bgr=color_rgb, mode=render_mode))
            hd = np.uint8(add_background(hd, bgr=color_rgb, mode=render_mode))

        # 水印（add_watermark 返回 RGB，转回 BGR 统一）
        if o["watermark"] == WM_CHOICES[1]:
            kw = dict(
                text=o["wm_text"] or WM_DEFAULT_TEXT,
                size=int(o["wm_size"]),
                opacity=float(o["wm_opacity"]),
                angle=int(o["wm_angle"]),
                space=int(o["wm_space"]),
                color=o["wm_color"],
            )
            standard = np.uint8(add_watermark(image=standard, **kw))
            hd = np.uint8(add_watermark(image=hd, **kw))

        # 排版照
        layout = None
        if not change_bg_only and o["print_size"] in PRINT_SHAPES:
            lay_h, lay_w = PRINT_SHAPES[o["print_size"]]
            arr, rotate = generate_layout_array(
                input_height=size[0], input_width=size[1],
                LAYOUT_HEIGHT=lay_h, LAYOUT_WIDTH=lay_w,
            )
            layout = generate_layout_image(
                standard, arr, rotate,
                height=size[0], width=size[1],
                crop_line=layout_crop_line,
                LAYOUT_HEIGHT=lay_h, LAYOUT_WIDTH=lay_w,
            )

        # 模板照
        templates = []
        if not change_bg_only:
            for name in ("template_1", "template_2"):
                try:
                    templates.append(generte_template_photo(template_name=name, input_image=hd))
                except Exception as exc:  # 模板缺失不应影响主流程
                    log("模板照 %s 生成失败：%s" % (name, exc))

        elapsed = time.time() - t0
        log("完成，用时 %.1f 秒" % elapsed)
        return {
            "standard": standard,
            "hd": hd,
            "layout": layout,
            "templates": templates,
            "jpeg": jpeg_format,
            "kb": None if o["kb_mode"] == KB_CHOICES[0] else int(o["kb_value"]),
            "dpi": 300 if o["dpi_mode"] == DPI_CHOICES[0] else int(o["dpi_value"]),
            "size": size,
            "elapsed": elapsed,
        }

    # ---- 落盘
    def save(self, res, out_dir, tag="", log=print):
        os.makedirs(out_dir, exist_ok=True)
        ext = "jpg" if res["jpeg"] else "png"
        dpi = res["dpi"]
        kb = res["kb"]
        prefix = ("%s_" % tag) if tag else ""
        saved = []

        def _save(img, stem, use_kb=False):
            path = os.path.join(out_dir, "%s%s_%ddpi.%s" % (prefix, stem, dpi, ext))
            if use_kb and kb:
                path = os.path.join(out_dir, "%s%s_%ddpi_%dkb.%s" % (prefix, stem, dpi, kb, ext))
                resize_image_to_kb(img, path, kb, dpi=dpi)
            else:
                save_image_dpi_to_bytes(img, path, dpi=dpi)
            saved.append(path)
            log("已保存：%s" % os.path.basename(path))

        _save(res["standard"], "标准照", use_kb=True)
        _save(res["hd"], "高清照")
        if res["layout"] is not None:
            _save(res["layout"], "排版照")
        for i, tpl in enumerate(res["templates"] or []):
            _save(tpl, "模板照%d" % (i + 1))
        return saved


# ---------------------------------------------------------------- 现代风格 UI（customtkinter）
FONT_FAMILY = "Microsoft YaHei UI"

C_BG = ("#EDF1F7", "#0D1219")
C_CARD = ("#FFFFFF", "#1A212B")
C_SOFT = ("#F3F6FA", "#232C38")
C_SOFT_HOVER = ("#E7EDF6", "#2D3846")
C_BORDER = ("#E1E7EF", "#2B3542")
C_TEXT = ("#16202C", "#E7EDF5")
C_MUTED = ("#6B7B8D", "#98A7B8")
C_PRIMARY = ("#2563EB", "#3B82F6")
C_PRIMARY_HOVER = ("#1D4ED8", "#2E6FE0")
C_PREVIEW = ("#F1F5FA", "#1E2631")
C_LOG_BG = ("#0F1620", "#0A0F16")
C_LOG_TEXT = "#CFD8E3"
# 滚动条：轨道与滑块必须明确区分，否则滑块与背景同色看不清
C_SCROLL_TRACK = ("#E4EAF3", "#212A36")
C_SCROLL_BTN = ("#9FB0C4", "#7C8CA1")

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------- 主界面（现代风格）
class DesktopApp(ctk.CTk):
    TAB_TITLES = {"standard": "标准照", "hd": "高清照", "layout": "排版照", "template": "模板照"}
    LOG_TAB = "运行日志"

    def __init__(self):
        ctk.CTk.__init__(self)
        self.title("%s v%s" % (APP_NAME, APP_VERSION))
        self.geometry(self._initial_geometry())
        self.minsize(820, 520)
        self.configure(fg_color=C_BG)

        self.engine = PhotoEngine()
        self.img_path = None
        self.input_bgr = None
        self.result = None
        self.saved_paths = []
        self._preview_refs = {}
        self._preview_src = {}
        self._preview_sig = {}
        self._preview_jobs = {}
        self._q = queue.Queue()
        self._busy = False

        self._init_fonts()
        self._build_ui()
        self._sync_theme_button()
        self._toggle_dependent_widgets()
        self.bind("<Configure>", self._on_window_configure, add="+")
        self.after(150, self._poll_queue)

    def _ui_scale(self):
        """当前界面缩放系数（与 _apply_ui_scaling 保持一致）。"""
        try:
            from ctypes import windll
            return min(3.0, max(1.0, windll.shcore.GetScaleFactorForDevice(0) / 100.0))
        except Exception:
            return 1.0

    def _initial_geometry(self):
        w, h = 880, 573
        try:
            scale = self._ui_scale()
            sw = self.winfo_screenwidth() / scale
            sh = self.winfo_screenheight() / scale
            return "%dx%d+%d+%d" % (w, h,
                                    max(0, int((sw - w) // 2)),
                                    max(0, int((sh - h) // 3)))
        except Exception:
            return "%dx%d" % (w, h)

    # ---------------- 字体
    def _init_fonts(self):
        self.f_title = ctk.CTkFont(FONT_FAMILY, 19, "bold")
        self.f_badge = ctk.CTkFont(FONT_FAMILY, 18, "bold")
        self.f_section = ctk.CTkFont(FONT_FAMILY, 14, "bold")
        self.f_md = ctk.CTkFont(FONT_FAMILY, 13)
        self.f_bold = ctk.CTkFont(FONT_FAMILY, 13, "bold")
        self.f_small = ctk.CTkFont(FONT_FAMILY, 12)

    # ---------------- 组件工厂
    def _card(self, parent, title, subtitle=""):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=C_CARD,
                            border_width=1, border_color=C_BORDER)
        card.pack(fill="x", padx=0, pady=(0, 7))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(head, text=title, font=self.f_section, text_color=C_TEXT,
                     anchor="w").pack(side="left")
        if subtitle:
            ctk.CTkLabel(head, text=subtitle, font=self.f_small, text_color=C_MUTED,
                         anchor="e").pack(side="right")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(6, 10))
        return body

    def _caption(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=self.f_small, text_color=C_MUTED,
                     anchor="w").pack(fill="x", pady=(1, 2))

    def _entry(self, parent, var, width=80, side="left", padx=(6, 0)):
        e = ctk.CTkEntry(parent, textvariable=var, width=width, height=30, corner_radius=8,
                         font=self.f_md, fg_color=C_SOFT, border_width=1,
                         border_color=C_BORDER, text_color=C_TEXT)
        e.pack(side=side, padx=padx)
        return e

    def _option_menu(self, parent, values, var, command=None, width=300):
        m = ctk.CTkOptionMenu(
            parent, values=values, variable=var, command=command, width=width, height=30,
            corner_radius=9, font=self.f_md, dropdown_font=self.f_md, anchor="w",
            dynamic_resizing=False, fg_color=C_SOFT, button_color=C_SOFT_HOVER,
            button_hover_color=C_BORDER, text_color=C_TEXT, dropdown_fg_color=C_CARD,
            dropdown_hover_color=C_SOFT_HOVER, dropdown_text_color=C_TEXT,
        )
        return m

    def _slider(self, parent, label, var, lo, hi, step, fmt):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text=label, width=62, anchor="w", font=self.f_md,
                     text_color=C_TEXT).pack(side="left")
        val = ctk.CTkLabel(row, text=fmt.format(float(var.get())), width=44, anchor="e",
                           font=self.f_small, text_color=C_PRIMARY)
        val.pack(side="right", padx=(6, 0))

        last = [None]

        def cb(_v=None):
            try:
                txt = fmt.format(float(var.get()))
            except Exception:
                return
            if txt != last[0]:
                last[0] = txt
                val.configure(text=txt)

        steps = max(1, int(round((hi - lo) / float(step))))
        s = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, variable=var,
                          command=cb, height=16, fg_color=C_SOFT_HOVER,
                          progress_color=C_PRIMARY, button_color=C_PRIMARY,
                          button_hover_color=C_PRIMARY_HOVER)
        s.pack(side="left", fill="x", expand=True, padx=(6, 0))
        return s

    # ---------------- 布局
    def _build_ui(self):
        self._build_header()
        self._build_status()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(6, 0))

        left = self._make_scroll_area(body, 356)
        self._build_params(left)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, pady=(0, 6))
        self._build_preview(right)

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=70)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=(14, 78), pady=(9, 5))

        ctk.CTkLabel(inner, text="ID", width=42, height=42, corner_radius=12,
                     fg_color=C_PRIMARY, text_color="#FFFFFF",
                     font=self.f_badge).pack(side="left")
        box = ctk.CTkFrame(inner, fg_color="transparent")
        box.pack(side="left", padx=(14, 0))
        ctk.CTkLabel(box, text="证件照制作", font=self.f_title, text_color=C_TEXT,
                     anchor="w").pack(anchor="w")
        self.lbl_file = ctk.CTkLabel(box, text="本地离线运行 · 内置模型 · 无需联网",
                                     font=self.f_small, text_color=C_MUTED, anchor="w")
        self.lbl_file.pack(anchor="w")

        self.btn_run = ctk.CTkButton(inner, text="开始制作", width=104, height=34, corner_radius=10,
                                     font=self.f_bold, fg_color=C_PRIMARY,
                                     hover_color=C_PRIMARY_HOVER, text_color="#FFFFFF",
                                     command=self.on_run)
        self.btn_run.pack(side="right")
        self.btn_save = ctk.CTkButton(inner, text="保存当前图", width=96, height=34, corner_radius=10,
                                      font=self.f_md, fg_color=C_SOFT, hover_color=C_SOFT_HOVER,
                                      text_color=C_TEXT, state="disabled", command=self.on_save_current)
        self.btn_save.pack(side="right", padx=(0, 8))
        self.btn_open = ctk.CTkButton(inner, text="输出目录", width=88, height=34, corner_radius=10,
                                      font=self.f_md, fg_color="transparent", border_width=1,
                                      border_color=C_BORDER, hover_color=C_SOFT,
                                      text_color=C_TEXT, command=self.on_open_output)
        self.btn_open.pack(side="right", padx=(0, 8))
        self.btn_pick = ctk.CTkButton(inner, text="选择照片", width=96, height=34, corner_radius=10,
                                      font=self.f_md, fg_color=C_SOFT, hover_color=C_SOFT_HOVER,
                                      text_color=C_TEXT, command=self.on_pick)
        self.btn_pick.pack(side="right", padx=(0, 8))

        # 主题切换：月亮 / 太阳图标，置于窗体最顶端右侧（主流做法）
        self.btn_theme = ctk.CTkButton(
            bar, text="☾", width=32, height=26, corner_radius=13,
            font=ctk.CTkFont("Segoe UI Symbol", 15),
            fg_color="transparent", hover_color=C_SOFT_HOVER,
            border_width=1, border_color=C_BORDER, text_color=C_TEXT,
            command=self._toggle_theme)
        self.btn_theme.place(relx=1.0, y=2, x=-8, anchor="ne")
        self.btn_theme.bind("<Enter>", lambda e: self._theme_hint(True))
        self.btn_theme.bind("<Leave>", lambda e: self._theme_hint(False))

    def _build_status(self):
        bar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=34)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.progress = ctk.CTkProgressBar(bar, width=130, height=5, corner_radius=3,
                                           mode="indeterminate", progress_color=C_PRIMARY,
                                           fg_color=C_SOFT_HOVER)
        self.progress.pack(side="left", padx=(12, 8))
        self.progress.set(0)
        self.lbl_status = ctk.CTkLabel(bar, text="就绪", font=self.f_small, text_color=C_MUTED)
        self.lbl_status.pack(side="left")
        shown = OUTPUT_ROOT if len(OUTPUT_ROOT) <= 52 else "..." + OUTPUT_ROOT[-50:]
        ctk.CTkLabel(bar, text="输出：%s" % shown, font=self.f_small,
                     text_color=C_MUTED).pack(side="right", padx=12)

    # ---------------- 参数区
    def _build_params(self, p):
        # ---- 尺寸
        b = self._card(p, "证件照尺寸", "预设 / 像素 / 毫米")
        self.var_mode = tk.StringVar(value=MODE_LIST)
        # 模式名带「自定义(px)」这类长串，窄栏里分段控件会截字，改用四个短标签按钮
        _mode_defs = [(MODE_LIST, "预设"), (MODE_BG_ONLY, "换底"),
                      (MODE_PX, "像素"), (MODE_MM, "毫米")]
        _mode_defs = [(v, t) for v, t in _mode_defs if v]
        self._mode_buttons = []
        seg = ctk.CTkFrame(b, fg_color="transparent")
        seg.pack(fill="x", pady=(0, 7))
        for _i, (_val, _txt) in enumerate(_mode_defs):
            seg.grid_columnconfigure(_i, weight=1, uniform="mode")
            _btn = ctk.CTkButton(
                seg, text=_txt, height=30, corner_radius=8, font=self.f_small,
                fg_color=C_SOFT, hover_color=C_SOFT_HOVER, text_color=C_TEXT,
                border_width=0,
                command=lambda v=_val: self._on_mode_pick(v))
            _btn.grid(row=0, column=_i, sticky="ew", padx=(0 if _i == 0 else 6, 0))
            self._mode_buttons.append((_val, _btn))
        self._refresh_mode_buttons()

        self._caption(b, "规格预设")
        self.var_preset = tk.StringVar(value=SIZE_PRESETS[0])
        self._preset_display = [clean_preset_name(s) for s in SIZE_PRESETS]
        self.cmb_preset = self._option_menu(b, self._preset_display, self.var_preset,
                                            command=self._on_preset_pick, width=340)
        self.cmb_preset.pack(fill="x", pady=(0, 5))
        self.cmb_preset.set(self._preset_display[0])

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="像素", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        ctk.CTkLabel(row, text="高", font=self.f_small, text_color=C_MUTED).pack(side="left")
        self.var_px_h = tk.StringVar(value="413")
        self.ent_px_h = self._entry(row, self.var_px_h, 72)
        ctk.CTkLabel(row, text="宽", font=self.f_small, text_color=C_MUTED).pack(side="left", padx=(10, 0))
        self.var_px_w = tk.StringVar(value="295")
        self.ent_px_w = self._entry(row, self.var_px_w, 72)

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="毫米", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        ctk.CTkLabel(row, text="高", font=self.f_small, text_color=C_MUTED).pack(side="left")
        self.var_mm_h = tk.StringVar(value="35")
        self.ent_mm_h = self._entry(row, self.var_mm_h, 72)
        ctk.CTkLabel(row, text="宽", font=self.f_small, text_color=C_MUTED).pack(side="left", padx=(10, 0))
        self.var_mm_w = tk.StringVar(value="25")
        self.ent_mm_w = self._entry(row, self.var_mm_w, 72)

        # ---- 背景
        b = self._card(p, "背景颜色", "预设 / 自定义 / 渐变")
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x")
        self.lbl_swatch = ctk.CTkFrame(row, width=42, height=30, corner_radius=8,
                                       fg_color="#2F6FD0", border_width=1, border_color=C_BORDER)
        self.lbl_swatch.pack(side="left")
        self.lbl_swatch.pack_propagate(False)
        self.var_bg = tk.StringVar(value=BG_CHOICES[0])
        self.cmb_bg = self._option_menu(row, BG_CHOICES, self.var_bg,
                                        command=lambda v: self._toggle_dependent_widgets(), width=280)
        self.cmb_bg.pack(side="left", fill="x", expand=True, padx=(8, 0))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(5, 1))
        ctk.CTkLabel(row, text="RGB", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        self.var_r = tk.IntVar(value=255)
        self.ent_r = self._entry(row, self.var_r, 58, padx=(0, 4))
        self.var_gc = tk.IntVar(value=255)
        self.ent_g = self._entry(row, self.var_gc, 58, padx=(0, 4))
        self.var_bc = tk.IntVar(value=255)
        self.ent_b = self._entry(row, self.var_bc, 58)

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="HEX", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        self.var_hex = tk.StringVar(value="#FFFFFF")
        self.ent_hex = self._entry(row, self.var_hex, 100, padx=(0, 6))
        ctk.CTkButton(row, text="预览色", width=68, height=30, corner_radius=8, font=self.f_small,
                      fg_color=C_SOFT, hover_color=C_SOFT_HOVER, text_color=C_TEXT,
                      command=self._preview_swatch).pack(side="left")

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(5, 0))
        ctk.CTkLabel(row, text="渲染", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        self.var_render = tk.StringVar(value=RENDER_CHOICES[0])
        self.cmb_render = self._option_menu(row, RENDER_CHOICES, self.var_render, width=280)
        self.cmb_render.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # ---- 输出
        b = self._card(p, "排版与输出", "相纸 / 体积 / 精度")
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="相纸", width=62, anchor="w", font=self.f_md,
                     text_color=C_TEXT).pack(side="left")
        self.var_print = tk.StringVar(value=PRINT_CHOICES[0])
        self.cmb_print = self._option_menu(row, PRINT_CHOICES, self.var_print, width=140)
        self.cmb_print.pack(side="left", padx=(4, 0))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="KB 大小", width=62, anchor="w", font=self.f_md,
                     text_color=C_TEXT).pack(side="left")
        self.var_kb_mode = tk.StringVar(value=KB_CHOICES[0])
        self.cmb_kb = self._option_menu(row, KB_CHOICES, self.var_kb_mode,
                                        command=lambda v: self._toggle_dependent_widgets(), width=104)
        self.cmb_kb.pack(side="left", padx=(4, 0))
        self.var_kb = tk.StringVar(value="50")
        self.ent_kb = self._entry(row, self.var_kb, 72, padx=(8, 0))

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="DPI", width=62, anchor="w", font=self.f_md,
                     text_color=C_TEXT).pack(side="left")
        self.var_dpi_mode = tk.StringVar(value=DPI_CHOICES[0])
        self.cmb_dpi = self._option_menu(row, DPI_CHOICES, self.var_dpi_mode,
                                         command=lambda v: self._toggle_dependent_widgets(), width=104)
        self.cmb_dpi.pack(side="left", padx=(4, 0))
        self.var_dpi = tk.StringVar(value="300")
        self.ent_dpi = self._entry(row, self.var_dpi, 72, padx=(8, 0))

        # ---- 模型
        b = self._card(p, "AI 模型", "本地推理")
        self._caption(b, "抠图模型")
        self.var_matting = tk.StringVar(value=DEFAULT_MATTING)
        self.cmb_matting = self._option_menu(b, MATTING_MODELS, self.var_matting,
                                             command=self._on_matting_pick, width=340)
        self.cmb_matting.pack(fill="x", pady=(0, 2))
        self.lbl_matting_hint = ctk.CTkLabel(b, text="", font=self.f_small, text_color=C_MUTED,
                                             anchor="w", justify="left", wraplength=330)
        self.lbl_matting_hint.pack(fill="x", pady=(0, 5))
        self._caption(b, "人脸检测")
        self.var_face = tk.StringVar(value=DEFAULT_FACE_DETECT)
        self.cmb_face = self._option_menu(b, FACE_DETECT_MODELS, self.var_face,
                                          command=self._on_face_pick, width=340)
        self.cmb_face.pack(fill="x", pady=(0, 2))
        self.lbl_face_hint = ctk.CTkLabel(b, text="", font=self.f_small, text_color=C_MUTED,
                                          anchor="w", justify="left", wraplength=330)
        self.lbl_face_hint.pack(fill="x")
        self._refresh_model_hints()

        # ---- 构图
        b = self._card(p, "构图", "头身比 / 留白")
        self.var_head = tk.DoubleVar(value=0.2)
        self._slider(b, "头身比", self.var_head, 0.1, 0.5, 0.01, "{:.2f}")
        self.var_top = tk.DoubleVar(value=0.12)
        self._slider(b, "头顶留白", self.var_top, 0.02, 0.5, 0.01, "{:.2f}")

        # ---- 美颜
        b = self._card(p, "美颜", "强度可调")
        self.var_whitening = tk.DoubleVar(value=2)
        self._slider(b, "美白", self.var_whitening, 0, 15, 1, "{:.0f}")
        self.var_brightness = tk.DoubleVar(value=0)
        self._slider(b, "亮度", self.var_brightness, -5, 25, 1, "{:.0f}")
        self.var_contrast = tk.DoubleVar(value=0)
        self._slider(b, "对比度", self.var_contrast, -10, 50, 1, "{:.0f}")
        self.var_saturation = tk.DoubleVar(value=0)
        self._slider(b, "饱和度", self.var_saturation, -10, 50, 1, "{:.0f}")
        self.var_sharpen = tk.DoubleVar(value=0)
        self._slider(b, "锐化", self.var_sharpen, 0, 5, 1, "{:.0f}")

        # ---- 水印
        b = self._card(p, "水印", "文字 / 角度 / 透明度")
        self.var_wm = tk.StringVar(value=WM_CHOICES[0])
        self.var_wm_on = tk.BooleanVar(value=False)
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(row, text="添加水印", font=self.f_md, text_color=C_TEXT,
                     anchor="w").pack(side="left")
        ctk.CTkSwitch(row, text="", width=46, variable=self.var_wm_on, onvalue=True, offvalue=False,
                      progress_color=C_PRIMARY, button_color="#FFFFFF",
                      button_hover_color="#FFFFFF", command=self._on_wm_switch).pack(side="right")

        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="文字", width=44, anchor="w", font=self.f_small,
                     text_color=C_MUTED).pack(side="left")
        self.var_wm_text = tk.StringVar(value=WM_DEFAULT_TEXT)
        self.ent_wm_text = self._entry(row, self.var_wm_text, 156, padx=(0, 6))
        ctk.CTkLabel(row, text="颜色", font=self.f_small, text_color=C_MUTED).pack(side="left")
        self.var_wm_color = tk.StringVar(value="#FFFFFF")
        self.ent_wm_color = self._entry(row, self.var_wm_color, 92, padx=(6, 0))

        self.var_wm_size = tk.DoubleVar(value=20)
        self._slider(b, "字号", self.var_wm_size, 10, 100, 1, "{:.0f}")
        self.var_wm_opacity = tk.DoubleVar(value=0.15)
        self._slider(b, "透明度", self.var_wm_opacity, 0.0, 1.0, 0.01, "{:.2f}")
        self.var_wm_angle = tk.DoubleVar(value=30)
        self._slider(b, "角度", self.var_wm_angle, 0, 360, 1, "{:.0f}")
        self.var_wm_space = tk.DoubleVar(value=25)
        self._slider(b, "间距", self.var_wm_space, 10, 200, 1, "{:.0f}")

        # ---- 插件
        b = self._card(p, "插件", "可选增强")
        self.plugin_vars = {}
        for txt in PLUGIN_CHOICES:
            v = tk.BooleanVar(value=txt in PLUGIN_DEFAULT)
            self.plugin_vars[txt] = v
            ctk.CTkCheckBox(b, text=txt, variable=v, font=self.f_md, text_color=C_TEXT,
                            checkbox_width=20, checkbox_height=20, corner_radius=6,
                            border_width=2, border_color=C_MUTED, fg_color=C_PRIMARY,
                            hover_color=C_PRIMARY_HOVER, checkmark_color="#FFFFFF").pack(
                anchor="w", pady=3)

    # ---------------- 预览区
    def _build_preview(self, parent):
        self.tab = ctk.CTkTabview(
            parent, corner_radius=12, fg_color=C_CARD, border_width=1, border_color=C_BORDER,
            segmented_button_fg_color=C_SOFT, segmented_button_selected_color=C_PRIMARY,
            segmented_button_selected_hover_color=C_PRIMARY_HOVER,
            segmented_button_unselected_color=C_SOFT,
            segmented_button_unselected_hover_color=C_SOFT_HOVER,
            text_color=C_TEXT, command=self._on_tab_change,
        )
        self.tab.pack(fill="both", expand=True)
        self.preview_labels = {}
        self._preview_holders = {}
        for key in ("standard", "hd", "layout", "template"):
            f = self.tab.add(self.TAB_TITLES[key])
            holder = ctk.CTkFrame(f, fg_color=C_PREVIEW, corner_radius=10)
            holder.pack(fill="both", expand=True, padx=4, pady=4)
            lbl = ctk.CTkLabel(holder, text="暂无预览 · 选择照片后点击「开始制作」",
                               font=self.f_md, text_color=C_MUTED)
            lbl.pack(fill="both", expand=True, padx=5, pady=5)
            lbl.bind("<Configure>", lambda e, k=key: self._schedule_preview_fit(k))
            holder.bind("<Configure>", lambda e, k=key: self._schedule_preview_fit(k))
            self.preview_labels[key] = lbl
            self._preview_holders[key] = holder

        logf = self.tab.add(self.LOG_TAB)
        self.txt_log = ctk.CTkTextbox(logf, fg_color=C_LOG_BG, text_color=C_LOG_TEXT,
                                      font=ctk.CTkFont("Consolas", 12), corner_radius=12,
                                      wrap="word", border_width=0)
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab.set(self.TAB_TITLES["standard"])

    # ---------------- 联动
    def _on_wm_switch(self):
        self.var_wm.set(WM_CHOICES[1] if self.var_wm_on.get() else WM_CHOICES[0])
        self._toggle_dependent_widgets()

    def _on_mode_pick(self, value):
        self.var_mode.set(value)
        self._refresh_mode_buttons()
        self._toggle_dependent_widgets()

    def _refresh_mode_buttons(self):
        cur = self.var_mode.get()
        for val, btn in getattr(self, "_mode_buttons", []):
            on = (val == cur)
            btn.configure(
                fg_color=C_PRIMARY if on else C_SOFT,
                hover_color=C_PRIMARY_HOVER if on else C_SOFT_HOVER,
                text_color="#FFFFFF" if on else C_TEXT)

    def _toggle_dependent_widgets(self):
        mode = self.var_mode.get()
        self.cmb_preset.configure(state="normal" if mode == MODE_LIST else "disabled")
        for w in (self.ent_px_h, self.ent_px_w):
            w.configure(state="normal" if mode == MODE_PX else "disabled")
        for w in (self.ent_mm_h, self.ent_mm_w):
            w.configure(state="normal" if mode == MODE_MM else "disabled")

        bg = self.var_bg.get()
        for w in (self.ent_r, self.ent_g, self.ent_b):
            w.configure(state="normal" if bg == COLOR_CUSTOM_RGB else "disabled")
        self.ent_hex.configure(state="normal" if bg == COLOR_CUSTOM_HEX else "disabled")

        self.ent_kb.configure(state="normal" if self.var_kb_mode.get() == KB_CHOICES[1] else "disabled")
        self.ent_dpi.configure(state="normal" if self.var_dpi_mode.get() == DPI_CHOICES[1] else "disabled")

        on = self.var_wm.get() == WM_CHOICES[1]
        for w in (self.ent_wm_text, self.ent_wm_color):
            w.configure(state="normal" if on else "disabled")
        self._preview_swatch()

    def _preview_swatch(self):
        try:
            if self.var_bg.get() == COLOR_CUSTOM_HEX:
                r, g, b = hex_to_rgb(self.var_hex.get())
            elif self.var_bg.get() == COLOR_CUSTOM_RGB:
                r, g, b = self.var_r.get(), self.var_gc.get(), self.var_bc.get()
            elif self.var_bg.get() == COLOR_AMERICAN:
                r = g = b = 235
            else:
                r, g, b = hex_to_rgb(BG_HEX_MAP[self.var_bg.get()])
            self.lbl_swatch.configure(fg_color="#%02x%02x%02x" % (r, g, b))
        except Exception:
            self.lbl_swatch.configure(fg_color="#DDDDDD")

    def _on_preset_pick(self, choice=None):
        try:
            idx = self._preset_display.index(choice if choice is not None else self.cmb_preset.get())
        except Exception:
            return
        name = SIZE_PRESETS[idx]
        self.var_preset.set(name)
        h, w = SIZE_PRESET_MAP[name]
        self.var_px_h.set(str(h))
        self.var_px_w.set(str(w))

    def _on_matting_pick(self, value=None):
        if value is not None:
            self.var_matting.set(value)
        self._refresh_model_hints()

    def _on_face_pick(self, value=None):
        if value is not None:
            self.var_face.set(value)
        self._refresh_model_hints()

    @staticmethod
    def _hint_of(mapping, name, default="特点见名称说明"):
        for key, text in mapping.items():
            if key == name:
                return text
        for key, text in mapping.items():
            if key.lower() in str(name).lower():
                return text
        return default

    def _refresh_model_hints(self):
        if not hasattr(self, "lbl_matting_hint"):
            return
        try:
            self.lbl_matting_hint.configure(
                text="特点：%s" % self._hint_of(MATTING_MODEL_HINTS, self.var_matting.get()))
            self.lbl_face_hint.configure(
                text="特点：%s" % self._hint_of(FACE_DETECT_HINTS, self.var_face.get()))
        except Exception:
            pass

    # ---------------- 主题
    # ---------------- 主题与重绘控制
    def _hwnd(self):
        try:
            import ctypes
            return int(ctypes.windll.user32.GetAncestor(int(self.winfo_id()), 2))
        except Exception:
            return int(self.winfo_id())

    def _freeze(self, on):
        """切换主题时冻结窗口重绘，避免整窗闪烁。"""
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = self._hwnd()
            if on:
                u.SendMessageW(hwnd, 0x000B, 0, 0)
            else:
                u.SendMessageW(hwnd, 0x000B, 1, 0)
                u.InvalidateRect(hwnd, None, True)
                u.UpdateWindow(hwnd)
        except Exception:
            pass

    def _toggle_theme(self):
        dark = ctk.get_appearance_mode() == "Dark"
        target = "light" if dark else "dark"
        self._freeze(True)
        try:
            ctk.set_appearance_mode(target)
            self.configure(fg_color=C_BG)
            self._sync_theme_button()
            canvas = getattr(self, "_scroll_canvas", None)
            if canvas is not None:
                canvas.configure(bg=self._color(C_BG))
            self.update_idletasks()
        finally:
            self._freeze(False)
        # 主题色变化后按新背景重算滚动条与预览
        for key in list(getattr(self, "_preview_src", {})):
            self._preview_sig.pop(key, None)
            self._schedule_preview_fit(key, 60)

    def _sync_theme_button(self):
        """图标表示「点击后会切换到的模式」：浅色显示月亮，深色显示太阳。"""
        dark = ctk.get_appearance_mode() == "Dark"
        self._theme_tip = "切换为浅色主题" if dark else "切换为深色主题"
        try:
            self.btn_theme.configure(text="☀" if dark else "☾")
        except Exception:
            pass

    def _theme_hint(self, on):
        try:
            if on:
                self._hint_backup = self.lbl_status.cget("text")
                self.lbl_status.configure(text=self._theme_tip)
            else:
                self.lbl_status.configure(text=getattr(self, "_hint_backup", "就绪"))
        except Exception:
            pass

    def _color(self, tup):
        if isinstance(tup, tuple):
            return tup[1] if ctk.get_appearance_mode() == "Dark" else tup[0]
        return tup

    def _make_scroll_area(self, parent, width):
        """参数区滚动：原生 Canvas 承载，滚动时不再整窗重绘。"""
        host = ctk.CTkFrame(parent, fg_color=C_BG, corner_radius=0, width=width)
        host.pack(side="left", fill="y", padx=(0, 8), pady=(0, 6))
        canvas = tk.Canvas(host, bg=self._color(C_BG), highlightthickness=0, bd=0,
                           relief="flat", takefocus=0, width=width - 14)
        canvas.pack(side="left", fill="both", expand=True)
        sb = ctk.CTkScrollbar(host, command=canvas.yview, width=13, corner_radius=7,
                              button_color=C_SCROLL_BTN, button_hover_color=C_PRIMARY,
                              fg_color=C_SCROLL_TRACK)
        sb.pack(side="right", fill="y", padx=(2, 1), pady=4)
        canvas.configure(yscrollcommand=sb.set)

        inner = ctk.CTkFrame(canvas, fg_color=C_BG, corner_radius=0)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_e=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.itemconfigure(win, width=canvas.winfo_width())
            except Exception:
                pass

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)

        def _wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except Exception:
                pass

        def _bind(_e=None):
            canvas.bind_all("<MouseWheel>", _wheel)

        def _unbind(_e=None):
            canvas.unbind_all("<MouseWheel>")

        for w in (canvas, sb):
            w.bind("<Enter>", _bind, add="+")
            w.bind("<Leave>", _unbind, add="+")
        self._scroll_canvas = canvas
        return inner

    # ---------------- 日志 / 状态
    def log(self, msg):
        line = "[%s] %s\n" % (time.strftime("%H:%M:%S"), msg)
        try:
            self.txt_log.insert("end", line)
            self.txt_log.see("end")
        except Exception:
            pass

    def _set_busy(self, busy, status=None):
        self._busy = busy
        st = "disabled" if busy else "normal"
        self.btn_run.configure(state=st)
        self.btn_pick.configure(state=st)
        if busy:
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.set(0)
        if status:
            self.lbl_status.configure(text=status)

    # ---------------- 交互
    def on_pick(self):
        path = filedialog.askopenfilename(
            title="选择证件照原图",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.webp"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            img = imread_unicode(path)
        except Exception as exc:
            messagebox.showerror("无法读取图片", str(exc))
            return
        self.img_path = path
        self.input_bgr = img
        self.lbl_file.configure(text="%s  (%d×%d)" % (os.path.basename(path), img.shape[1], img.shape[0]))
        self.log("已载入原图：%s (%d×%d)" % (path, img.shape[1], img.shape[0]))
        self._show_image("standard", img, src_is_bgr=True)

    def _collect_options(self):
        plugins = [k for k, v in self.plugin_vars.items() if v.get()]
        try:
            render_index = RENDER_CHOICES.index(self.var_render.get())
        except ValueError:
            render_index = 0
        preset = self.var_preset.get()
        if preset not in SIZE_PRESET_MAP:
            preset = SIZE_PRESETS[0]
        return {
            "size_mode": self.var_mode.get(),
            "size_preset": preset,
            "custom_px_h": self.var_px_h.get().strip() or "0",
            "custom_px_w": self.var_px_w.get().strip() or "0",
            "custom_mm_h": self.var_mm_h.get().strip() or "0",
            "custom_mm_w": self.var_mm_w.get().strip() or "0",
            "bg_color": self.var_bg.get(),
            "custom_r": self.var_r.get(),
            "custom_g": self.var_gc.get(),
            "custom_b": self.var_bc.get(),
            "custom_hex": self.var_hex.get().strip(),
            "render_index": render_index,
            "print_size": self.var_print.get(),
            "kb_mode": self.var_kb_mode.get(),
            "kb_value": self.var_kb.get().strip() or "50",
            "dpi_mode": self.var_dpi_mode.get(),
            "dpi_value": self.var_dpi.get().strip() or "300",
            "matting_model": self.var_matting.get(),
            "face_detect_model": self.var_face.get(),
            "head_ratio": self.var_head.get(),
            "top_distance": self.var_top.get(),
            "whitening": self.var_whitening.get(),
            "brightness": self.var_brightness.get(),
            "contrast": self.var_contrast.get(),
            "saturation": self.var_saturation.get(),
            "sharpen": self.var_sharpen.get(),
            "watermark": self.var_wm.get(),
            "wm_text": self.var_wm_text.get().strip(),
            "wm_color": self.var_wm_color.get().strip(),
            "wm_size": self.var_wm_size.get(),
            "wm_opacity": self.var_wm_opacity.get(),
            "wm_angle": self.var_wm_angle.get(),
            "wm_space": self.var_wm_space.get(),
            "plugins": plugins,
        }

    def on_run(self):
        if self._busy:
            return
        if self.input_bgr is None:
            messagebox.showinfo("提示", "请先选择一张人像照片。")
            return
        try:
            opts = self._collect_options()
            self.engine._resolve_size(opts)
            self.engine._resolve_color(opts)
            if opts["kb_mode"] == KB_CHOICES[1]:
                v = int(opts["kb_value"])
                if not 10 <= v <= 1000:
                    raise ValueError("KB 大小需在 10 ~ 1000 之间")
            if opts["dpi_mode"] == DPI_CHOICES[1]:
                v = int(opts["dpi_value"])
                if not 72 <= v <= 600:
                    raise ValueError("DPI 需在 72 ~ 600 之间")
            if opts["watermark"] == WM_CHOICES[1]:
                hex_to_rgb(opts["wm_color"])
        except Exception as exc:
            messagebox.showerror("参数有误", str(exc))
            return

        self._set_busy(True, "正在处理，请稍候…")
        self.btn_save.configure(state="disabled")
        self.tab.set(self.LOG_TAB)
        self.log("—" * 48)
        t = threading.Thread(target=self._worker, args=(self.input_bgr.copy(), opts), daemon=True)
        t.start()

    def _worker(self, img, opts):
        try:
            def _log(msg):
                self._q.put(("log", msg))

            res = self.engine.process(img, opts, log=_log)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            tag = ""
            if res["size"]:
                h, w = res["size"]
                tag = "%dx%d" % (h, w)
            out_dir = os.path.join(OUTPUT_ROOT, "%s_%s" % (stamp, tag) if tag else stamp)
            paths = self.engine.save(res, out_dir, tag="", log=_log)
            self._q.put(("done", (res, paths, out_dir)))
        except Exception as exc:
            detail = traceback.format_exc()
            self._q.put(("error", (str(exc), detail)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self._on_done(*payload)
                elif kind == "error":
                    self._on_error(*payload)
        except queue.Empty:
            pass
        self.after(180, self._poll_queue)

    def _on_done(self, res, paths, out_dir):
        self.result = res
        self.saved_paths = paths
        self._set_busy(False, "完成：用时 %.1f 秒，已保存 %d 个文件" % (res["elapsed"], len(paths)))
        self.btn_save.configure(state="normal")
        self._show_image("standard", res["standard"])
        self._show_image("hd", res["hd"])
        if res["layout"] is not None:
            self._show_image("layout", res["layout"])
        if res["templates"]:
            self._show_image("template", res["templates"][0])
        self.log("输出目录：%s" % out_dir)
        self.tab.set(self.TAB_TITLES["standard"])

    def _on_error(self, msg, detail):
        self._set_busy(False, "处理失败")
        self.log("错误：%s" % msg)
        self.log(detail)
        messagebox.showerror("处理失败", msg)

    def _preview_cap(self, key):
        """缩放上限：标准照按比例跟随窗口；其余三版照允许放大更满。"""
        return 2.6 if key == "standard" else 4.0

    def _show_image(self, key, img, src_is_bgr=False):
        lbl = self.preview_labels.get(key)
        if lbl is None or img is None:
            return
        try:
            pil = np_to_pil(img, src_is_bgr=src_is_bgr)
            self._preview_src[key] = pil
            self._preview_sig.pop(key, None)
            self._fit_preview(key)
        except Exception as exc:
            self.log("预览失败：%s" % exc)

    def _on_tab_change(self, name=None):
        rev = {v: k for k, v in self.TAB_TITLES.items()}
        try:
            key = rev.get(name if name is not None else self.tab.get())
        except Exception:
            key = None
        if key:
            self._schedule_preview_fit(key, 40)

    def _on_window_configure(self, event=None):
        """窗口尺寸变化：所有已出图的页签一起按新尺寸重算（等比缩放）。"""
        if event is not None and event.widget is not self:
            return
        jid = getattr(self, "_win_job", None)
        if jid:
            try:
                self.after_cancel(jid)
            except Exception:
                pass
        try:
            self._win_job = self.after(110, self._refit_all)
        except Exception:
            pass

    def _refit_all(self):
        self._win_job = None
        for key in list(getattr(self, "_preview_src", {})):
            self._fit_preview_safe(key)

    def _schedule_preview_fit(self, key, delay=130):
        """窗口/页签尺寸变化后延迟重算预览，避免拖动窗口时反复重绘。"""
        jid = self._preview_jobs.pop(key, None)
        if jid:
            try:
                self.after_cancel(jid)
            except Exception:
                pass
        try:
            self._preview_jobs[key] = self.after(
                delay, lambda k=key: self._fit_preview_safe(k))
        except Exception:
            pass

    def _fit_preview_safe(self, key):
        self._preview_jobs.pop(key, None)
        try:
            self._fit_preview(key)
        except Exception as exc:
            self.log("预览缩放失败：%s" % exc)

    def _fit_preview(self, key):
        """按当前可用区域等比缩放：保持原图宽高比，随窗口大小实时变化。"""
        pil = self._preview_src.get(key)
        lbl = self.preview_labels.get(key)
        if pil is None or lbl is None or pil.width <= 0 or pil.height <= 0:
            return
        holder = self._preview_holders.get(key)
        target = holder if holder is not None else lbl
        w = target.winfo_width() - 18
        h = target.winfo_height() - 18
        if w < 60 or h < 60:
            return
        ratio = min(w / float(pil.width), h / float(pil.height), self._preview_cap(key))
        ratio = max(ratio, 0.03)
        tw = max(1, int(round(pil.width * ratio)))
        th = max(1, int(round(pil.height * ratio)))
        if self._preview_sig.get(key) == (tw, th):
            return
        prev = pil.resize((tw, th), Image.LANCZOS)
        photo = ctk.CTkImage(light_image=prev, dark_image=prev, size=prev.size)
        self._preview_refs[key] = photo
        self._preview_sig[key] = (tw, th)
        lbl.configure(image=photo, text="")

    def on_save_current(self):
        if not self.result:
            return
        rev = {v: k for k, v in self.TAB_TITLES.items()}
        key = rev.get(self.tab.get())
        if key is None:
            return
        name = self.TAB_TITLES[key]
        img = self.result["standard"] if key == "standard" else self.result.get(key)
        if key == "template":
            img = (self.result.get("templates") or [None])[0]
        if img is None:
            messagebox.showinfo("提示", "当前没有可保存的%s" % name)
            return
        ext = ".jpg" if self.result.get("jpeg") else ".png"
        path = filedialog.asksaveasfilename(
            title="保存%s" % name, defaultextension=ext,
            initialfile="%s%s" % (name, ext),
            filetypes=[("JPEG 图片", "*.jpg"), ("PNG 图片", "*.png")],
        )
        if not path:
            return
        try:
            save_image_dpi_to_bytes(img, path, dpi=self.result.get("dpi", 300))
            self.log("已另存：%s" % path)
            self.lbl_status.configure(text="已另存：%s" % os.path.basename(path))
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def on_open_output(self):
        os.makedirs(OUTPUT_ROOT, exist_ok=True)
        try:
            os.startfile(OUTPUT_ROOT)
        except Exception as exc:
            messagebox.showerror("无法打开目录", str(exc))


def _apply_ui_scaling():
    """按系统缩放比例统一 customtkinter 的窗口与控件缩放，避免高 DPI 下界面偏小。"""
    scale = 1.0
    try:
        from ctypes import windll
        scale = windll.shcore.GetScaleFactorForDevice(0) / 100.0
    except Exception:
        try:
            import tkinter as _tk
            _r = _tk.Tk()
            scale = _r.winfo_fpixels("1i") / 96.0
            _r.destroy()
        except Exception:
            scale = 1.0
    scale = min(3.0, max(1.0, float(scale)))
    # 高 DPI 下 Tk 已按系统比例放大一次，customtkinter 若再缩放一次会形成双重放大，
    # 窗体实际尺寸变成设计值的 1.5~2 倍、各处间距也随之膨胀。此处固定 1.0，
    # 只保留系统这一次放大，使窗口回到换现代皮肤前的紧凑尺寸。
    try:
        ctk.set_window_scaling(1.0)
        ctk.set_widget_scaling(1.0)
    except Exception:
        pass
    return 1.0


def _dump_ui_diag(app):
    """仅供打包产物排查：把关键控件几何写入 ui_diag.json。"""
    import json

    sb = app.tab._segmented_button
    data = {
        "window": [app.winfo_width(), app.winfo_height()],
        "screen": [app.winfo_screenwidth(), app.winfo_screenheight()],
        "tabview": [app.tab.winfo_width(), app.tab.winfo_height()],
        "segbtn": [sb.winfo_width(), sb.winfo_reqwidth()],
        "tabs": [
            {"text": b.cget("text"), "x": b.winfo_x(),
             "w": b.winfo_width(), "req": b.winfo_reqwidth()}
            for b in sb._buttons_dict.values()
        ],
        "preview": {k: [v.winfo_width(), v.winfo_height()]
                    for k, v in app.preview_labels.items()},
    }
    with open(os.path.join(APP_HOME, "ui_diag.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def main():
    _apply_ui_scaling()
    app = DesktopApp()
    if os.environ.get("HV_UIDIAG") == "1":
        app.update()
        app.update_idletasks()
        app.after(1200, lambda: (_dump_ui_diag(app), app.destroy()))
        app.mainloop()
        return
    app.log("%s v%s 启动" % (APP_NAME, APP_VERSION))
    app.log("模型目录：%s" % os.path.join(BASE_DIR, "hivision", "creator", "weights"))
    app.log("输出目录：%s" % OUTPUT_ROOT)
    app.mainloop()


def _selftest():
    """无界面自检：仅供打包产物验证，HV_SELFTEST=1 时执行"""
    import json

    report = {"frozen": FROZEN, "base_dir": BASE_DIR, "app_home": APP_HOME,
              "output_root": OUTPUT_ROOT, "ok": False, "error": ""}
    try:
        engine = PhotoEngine()
        img = imread_unicode(os.path.join(BASE_DIR, "demo", "images", "test1.jpg"))
        report["input_shape"] = list(img.shape)
        opts = {
            "size_mode": MODE_LIST, "size_preset": SIZE_PRESETS[0],
            "custom_px_h": "413", "custom_px_w": "295", "custom_mm_h": "35", "custom_mm_w": "25",
            "bg_color": BG_CHOICES[0], "custom_r": 255, "custom_g": 255, "custom_b": 255,
            "custom_hex": "#FFFFFF", "render_index": 0, "print_size": PRINT_CHOICES[0],
            "kb_mode": KB_CHOICES[0], "kb_value": "50", "dpi_mode": DPI_CHOICES[0], "dpi_value": "300",
            "matting_model": DEFAULT_MATTING, "face_detect_model": DEFAULT_FACE_DETECT,
            "head_ratio": 0.2, "top_distance": 0.12, "whitening": 2, "brightness": 0,
            "contrast": 0, "saturation": 0, "sharpen": 0, "watermark": WM_CHOICES[0],
            "wm_text": "test", "wm_color": "#FFFFFF", "wm_size": 20, "wm_opacity": 0.15,
            "wm_angle": 30, "wm_space": 25, "plugins": [],
        }
        res = engine.process(img, opts, log=lambda m: None)
        report["elapsed"] = round(res["elapsed"], 2)
        report["standard_shape"] = list(res["standard"].shape)
        report["hd_shape"] = list(res["hd"].shape)
        report["layout_shape"] = None if res["layout"] is None else list(res["layout"].shape)
        out = os.path.join(APP_HOME, "自检输出")
        files = engine.save(res, out, log=lambda m: None)
        report["saved"] = [os.path.basename(f) for f in files]
        report["ok"] = True
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
    with open(os.path.join(APP_HOME, "selftest.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    if os.environ.get("HV_SELFTEST") == "1":
        _selftest()
        sys.exit(0)
    main()
