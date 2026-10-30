# HivisionIDPhotos Desktop

把 [HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos) 的证件照制作能力，做成一个 **Windows 原生桌面程序**（Tk + CustomTkinter），不依赖浏览器、不需要 Gradio，双击即用。

> 本项目是面向 Windows 的**独立桌面封装发行版**，不是上游仓库的 fork。
> 上游代码以 Apache-2.0 许可使用，版权归原作者 Zeyi-Lin 及贡献者所有；本项目仅新增桌面 UI 层、打包工程与模型在线获取逻辑。

## 特性

| 能力 | 说明 |
| --- | --- |
| 尺寸 | 尺寸列表 / 只换底 / 自定义 px / 自定义 mm |
| 背景 | 预设色 + 自定义 RGB / HEX + 美式背景 |
| 渲染 | 纯色 / 上下渐变 / 中心渐变 |
| 排版 | 六寸 / 五寸 / A4 / 3R / 4R，可加裁剪线 |
| 输出 | 自定义 KB、自定义 DPI、JPEG |
| 模型 | 4 种抠图模型 + 2 种人脸检测可切换，本地推理 |
| 调整 | 美颜（美白 / 亮度 / 对比度 / 饱和度 / 锐化）、头身比、头顶留白、人脸旋转对齐、水平翻转 |
| 其他 | 水印（文字 / 颜色 / 字号 / 透明度 / 角度 / 间距）、模板照 2 款 |

## 模型：在线获取，不随仓库分发

仓库与安装包里**都不包含 onnx 权重**，避免仓库膨胀与许可混乱。程序首次需要某个模型时提示用户确认后从官方源下载，之后完全离线推理。

| 模型 | 用途 | 大小 | 来源 |
| --- | --- | --- | --- |
| hivision_modnet | 抠图（默认，最快） | 24.7MB | 上游 Release `pretrained-model` |
| modnet_photographic_portrait_matting | 抠图（发丝更细） | 24.7MB | 上游 Release `pretrained-model` |
| rmbg-1.4 | 抠图（半透明边缘更强） | 168MB | HuggingFace `briaai/RMBG-1.4`（非商用） |
| birefnet-v1-lite | 抠图（质量最高、最慢） | 213.6MB | `ZhengPeng7/BiRefNet` Release v1 |
| retinaface-resnet50 | 人脸检测（小脸 / 侧脸） | 104.4MB | 上游 Release `pretrained-model` |

* MTCNN 人脸检测由 `mtcnn-runtime` 包自带，无需单独下载。
* 权重落盘位置：`app/hivision/creator/weights/`（RetinaFace 在 `app/hivision/creator/retinaface/weights/`），已被 `.gitignore` 排除。

### 命令行预下载

```bat
python scripts\download_models.py                 :: 只下默认必需（hivision_modnet）
python scripts\download_models.py --all           :: 全部 5 个（约 535MB）
python scripts\download_models.py --model rmbg-1.4 birefnet-v1-lite
python scripts\download_models.py --list
```

国内网络可先设置镜像前缀（可选，仅拼接在官方 URL 前）：

```bat
set HV_MODEL_MIRROR=https://ghfast.top/
```

## 运行

源码运行需要 Python 3.10+ 及上游依赖：

```bat
pip install -r app\requirements.txt -r app\requirements-app.txt
python app\desktop_app.py
```

或直接双击根目录 `启动.bat`（使用项目内置 `runtime\python.exe`，需自行准备）。

## 目录结构

```
HivisionIDPhotos-Desktop/
├─ app/
│  ├─ desktop_app.py          # 桌面版主程序（UI + 引擎封装）
│  ├─ model_manager.py        # 模型在线下载 / 完整性校验
│  ├─ demo/                   # 上游 Gradio 演示与文案（复用其尺寸/配色数据）
│  └─ hivision/               # 上游算法核心（抠图、人脸检测、排版、水印）
├─ scripts/
│  └─ download_models.py      # 命令行模型下载
├─ 启动.bat / 启动-调试.bat
└─ 使用说明.txt
```

## 打包（PyInstaller）

```bat
runtime\python.exe -m PyInstaller --noconfirm --windowed --name HivisionIDPhotos-Desktop ^
  --add-data "app\assets;assets" --add-data "app\demo;demo" ^
  --add-data "app\hivision;hivision" --icon app\assets\hivisionai.ico app\desktop_app.py
```

打包产物**不含模型权重**，分发体积约几十 MB；用户首次运行时按需下载。若要做完全离线绿色包，可在打包后把 `weights` 目录手工复制进 `_internal\hivision\creator\weights`。

## 许可

* 本项目新增代码：Apache-2.0
* 上游 HivisionIDPhotos：Apache-2.0（见 `app/LICENSE`）
* RMBG-1.4 权重为 **非商用** 许可，商用请改用其他抠图模型
* BiRefNet 权重遵循其原仓库许可（MIT）

## 致谢

[Zeyi-Lin/HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos)、[ZHKKKe/MODNet](https://github.com/ZHKKKe/MODNet)、[briaai/RMBG-1.4](https://huggingface.co/briaai/RMBG-1.4)、[ZhengPeng7/BiRefNet](https://github.com/ZhengPeng7/BiRefNet)。
