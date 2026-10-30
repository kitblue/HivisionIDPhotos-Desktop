# -*- coding: utf-8 -*-
"""PyInstaller 运行时 hook（最早执行）：规避 Windows MAX_PATH(260) 限制。

现象：把程序解压到较深/较长的目录后，启动报
    DLL load failed while importing onnxruntime_pybind11_state: 文件名或扩展名太长。
原因：_internal\\onnxruntime\\capi\\onnxruntime_pybind11_state.pyd 的完整路径超过 260 字符，
      Windows 加载器直接拒绝加载（ERROR_FILENAME_EXCED_RANGE）。

做法：
  1. 计算关键 pyd 的完整路径长度，未超限则什么都不做，零开销；
  2. 超限时把 sys._MEIPASS 换成 Windows 8.3 短路径（GetShortPathNameW），
     同步改写 sys.path / PATH / os.add_dll_directory，使后续 import 走短路径；
  3. 若该卷禁用了 8.3 短名，兜底把 onnxruntime 目录复制到 %TEMP%\\hidp_ort 短目录，
     再把该目录插到 sys.path 首位。
"""
import os
import sys

# windowed（无控制台）模式下 sys.stdout / sys.stderr 为 None，
# 任何第三方库在 import 或运行时写日志都会抛 AttributeError("NoneType has no attribute write")
# 并导致进程直接退出（表现为“Failed to execute script”）。这里兜底到 devnull。
if sys.stdout is None or sys.stderr is None:
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

_PYD_TAIL = ("onnxruntime", "capi", "onnxruntime_pybind11_state.pyd")
_LIMIT = 259  # Windows 保证可用上限 260，含结尾 \0 余量


def _ort_pyd(base):
    for tail in (_PYD_TAIL, ("_internal",) + _PYD_TAIL):
        p = os.path.join(base, *tail)
        if os.path.exists(p):
            return p
    return os.path.join(base, *_PYD_TAIL)


def _short_path(path):
    try:
        import ctypes

        fn = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        fn.restype = ctypes.c_uint
        for size in (512, 4096, 32768):
            buf = ctypes.create_unicode_buffer(size)
            n = fn(path, buf, size)
            if 0 < n < size:
                return buf.value
    except Exception:
        pass
    return None


def _replace_in_env(base, short):
    path = os.environ.get("PATH", "")
    if not path:
        return
    parts = path.split(os.pathsep)
    out = []
    nb = os.path.normcase(base)
    for p in parts:
        if p and os.path.normcase(p).startswith(nb):
            out.append(short + p[len(base):])
        else:
            out.append(p)
    os.environ["PATH"] = os.pathsep.join(out)


def _fallback_copy(base):
    """8.3 短名不可用时的兜底：把 onnxruntime 复制到短的 TEMP 目录"""
    import shutil

    src = os.path.join(base, "onnxruntime")
    if not os.path.isdir(src):
        return None
    temp_root = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Windows\Temp"
    dst = os.path.join(temp_root, "hidp_ort")
    try:
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        for name in ("vcruntime140.dll", "vcruntime140_1.dll",
                     "msvcp140.dll", "MSVCP140_1.dll", "concrts140.dll"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                try:
                    shutil.copy2(p, os.path.join(dst, name))
                except OSError:
                    pass
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(dst)
            except OSError:
                pass
        if dst not in sys.path:
            sys.path.insert(0, dst)
        return dst
    except Exception:
        return None


def _main():
    if os.name != "nt":
        return
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    try:
        pyd = _ort_pyd(base)
        if len(pyd) <= _LIMIT:
            return
        short = _short_path(base)
        if short and len(short) < len(base) and len(os.path.join(short, *_PYD_TAIL)) <= _LIMIT:
            nb = os.path.normcase(base)
            for i, p in enumerate(sys.path):
                if p and os.path.normcase(p).startswith(nb):
                    sys.path[i] = short + p[len(base):]
            _replace_in_env(base, short)
            try:
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(os.path.join(short, "_internal")
                                          if os.path.isdir(os.path.join(short, "_internal"))
                                          else short)
            except OSError:
                pass
            sys._MEIPASS = short
            os.environ["HV_ORIG_HOME"] = base
            return
        # 短名不可用 / 仍超限 -> 兜底
        dst = _fallback_copy(base)
        if dst:
            os.environ["HV_ORIG_HOME"] = base
        else:
            os.environ["HV_LONGPATH_WARN"] = "1"
    except Exception:
        pass


_main()
