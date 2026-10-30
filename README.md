# HivisionIDPhotos Desktop

把 [HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos) 的证件照制作能力，做成一个 **Windows 原生桌面程序**（Tk + CustomTkinter）：不装浏览器、不起 Gradio 服务，双击就能出片。所有推理都在本机完成，照片不上传。

<img src="docs/images/ui-main.png" width="880" alt="HivisionIDPhotos 桌面版主界面">

> 本项目是面向 Windows 的**独立桌面封装发行版**，不是上游仓库的 fork。
> 上游代码以 Apache-2.0 许可使用，版权归原作者 Zeyi-Lin 及贡献者所有；本项目新增桌面 UI 层、打包工程与模型在线获取逻辑。

## 三步出片

<table>
<tr>
<td width="50%"><img src="docs/images/ui-loaded.png" alt="载入照片"></td>
<td width="50%"><img src="docs/images/ui-result-standard.png" alt="一键出图"></td>
</tr>
<tr>
<td><b>1. 选照片、调参数</b><br>左侧一栏搞定尺寸、底色、排版、美颜、水印；右侧实时预览原图，参数改动即时反映。</td>
<td><b>2. 一键制作</b><br>点「开始制作」，本地推理自动完成抠图、换底、裁剪、排版，标准照 / 高清照 / 排版照分页签预览。</td>
</tr>
</table>

图片缩放会跟随窗口自适应：标准照按原比例缩放，高清照、排版照、模板照占满可用空间，换尺寸不用重新出图。

## 功能一览

| 模块 | 能力 |
| --- | --- |
| 尺寸 | 尺寸列表 / 只换底 / 自定义 px / 自定义 mm |
| 背景 | 预设色 + 自定义 RGB / HEX + 美式背景 |
| 渲染 | 纯色 / 上下渐变 / 中心渐变 |
| 排版 | 六寸 / 五寸 / A4 / 3R / 4R，可加裁剪线、JPEG 输出、自定义 KB 与 DPI |
| 模型 | 4 种抠图模型 + 2 种人脸检测可切换，选择时下方实时提示模型特点 |
| 调整 | 美颜（美白 / 亮度 / 对比度 / 饱和度 / 锐化）、头身比、头顶留白、人脸旋转对齐、水平翻转 |
| 其他 | 文字水印（颜色 / 字号 / 透明度 / 角度 / 间距）、2 款模板照、多脸照片自动聚焦最大人脸 |

## 输出示例

<table>
<tr>
<td align="center"><img src="docs/images/out-standard.png" width="180"><br><sub>标准照 295×413</sub></td>
<td align="center"><img src="docs/images/out-hd.png" width="180"><br><sub>高清照 600×844</sub></td>
<td align="center"><img src="docs/images/out-layout.png" width="420"><br><sub>六寸排版照（含裁剪线）</sub></td>
</tr>
</table>

一次制作同时产出五张图（标准照、高清照、排版照、模板照 ×2），文件名带日期与尺寸前缀，默认落在程序目录的 `照片输出/` 下；目录不可写时自动回退到「图片」文件夹。

## 界面与日志

<table>
<tr>
<td width="50%"><img src="docs/images/ui-dark.png" alt="深色主题"></td>
<td width="50%"><img src="docs/images/ui-run-log.png" alt="运行日志"></td>
</tr>
<tr>
<td>右上角 ☾ / ☀ 一键切换浅色 / 深色皮肤，配色与滚动条同步换装。</td>
<td>每个步骤的耗时、模型加载、输出路径都写在日志页签里，出问题一眼定位。</td>
</tr>
</table>

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
* 界面「AI 模型」卡片内有 **下载 / 补齐模型** 按钮，缺什么补什么。

### 命令行预下载

```bat
python scripts\download_models.py                 :: 只下默认必需（hivision_modnet）
python scripts\download_models.py --all           :: 全部 5 个（约 535MB）
python scripts\download_models.py --model rmbg-1.4 birefnet-v1-lite
python scripts\download_models.py --list
```

国内网络可先设置镜像前缀（可选，仅拼接在官方 URL 前，官方源仍作兜底）：

```bat
set HV_MODEL_MIRROR=https://ghfast.top/
```

## 运行

源码运行需要 Python 3.10+ 及上游依赖：

```bat
pip install -r app\requirements.txt -r app\requirements-app.txt
python app\desktop_app.py
```

或直接双击根目录 `启动.bat`（使用项目内置 `runtime\python.exe`，需自行准备运行时）。

## 目录结构

```
HivisionIDPhotos-Desktop/
├─ app/
│  ├─ desktop_app.py          # 桌面版主程序（UI + 引擎封装）
│  ├─ model_manager.py        # 模型在线下载 / 完整性校验
│  ├─ demo/                   # 上游演示与文案（复用其尺寸、配色数据）
│  └─ hivision/               # 上游算法核心（抠图、人脸检测、排版、水印）
├─ scripts/
│  └─ download_models.py      # 命令行模型下载
├─ docs/images/               # 本文档所用界面与输出示例图
├─ 启动.bat / 启动-调试.bat
└─ 使用说明.txt
```

## 打包（PyInstaller）

```bat
runtime\python.exe -m PyInstaller --noconfirm --windowed --name HivisionIDPhotos-Desktop ^
  --add-data "app\assets;assets" --add-data "app\demo;demo" ^
  --add-data "app\hivision;hivision" --icon app\assets\hivisionai.ico app\desktop_app.py
```

打包产物**不含模型权重**，分发体积约几十 MB；用户首次运行时按需下载。若要做完全离线绿色包，可在打包后把 weights 目录手工复制进 `_internal\hivision\creator\weights`。

## 许可

* 本项目新增代码：Apache-2.0
* 上游 HivisionIDPhotos：Apache-2.0（见 `app/LICENSE`）
* RMBG-1.4 权重为 **非商用** 许可，商用请改用其他抠图模型
* BiRefNet 权重遵循其原仓库许可（MIT）

## 致谢

[Zeyi-Lin/HivisionIDPhotos](https://github.com/Zeyi-Lin/HivisionIDPhotos)、[ZHKKKe/MODNet](https://github.com/ZHKKKe/MODNet)、[briaai/RMBG-1.4](https://huggingface.co/briaai/RMBG-1.4)、[ZhengPeng7/BiRefNet](https://github.com/ZhengPeng7/BiRefNet)。
