# 更新日志

本文件由 `scripts/gen_changelog.py` 依据仓库提交记录自动生成，请勿手工编辑。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。


## v1.1.2 - 2026-10-31

### 问题修复

- **修复程序解压到较深目录后启动报 `DLL load failed while importing onnxruntime_pybind11_state: 文件名或扩展名太长`**
  - 根因：Windows `MAX_PATH`（260 字符）限制。`_internal\onnxruntime\capi\onnxruntime_pybind11_state.pyd`
    的完整路径一旦超限，系统加载器直接拒绝加载，PyInstaller 引导阶段就会失败
  - 根本问题在引导阶段（`python311.dll` / `base_library.zip` 也走同一条长路径），Python 层代码来不及执行，
    因此新增 **外层启动器**：`HivisionIDPhotos.exe` 改为 6KB 的 C# 启动器，先用 `GetShortPathNameW`
    把程序目录转成 8.3 短路径，再用短路径拉起真正的 `HivisionIDPhotos.real.exe`
  - 启动器在短名不可用时自动降级为原路径启动；启动失败弹出明确提示，引导用户换到较短的英文路径
  - 新增 `scripts/launcher/Launcher.cs` 与编译好的 `Launcher.exe`，由 `build_packages.py` 自动装入发行包
  - 运行期 hook `pyi_rth_shortpath.py` 保留为第二道防线（`sys._MEIPASS` 短名化 / 复制到 `%TEMP%\hidp_ort`）
  - 修复 windowed 模式下 `sys.stdout` / `sys.stderr` 为 `None`，第三方库写日志抛 `AttributeError`
    导致进程静默退出的问题（表现为「Failed to execute script desktop_app」）
  - 界面状态栏与日志在短路径运行时已还原显示用户实际解压路径（环境变量 `HV_ORIG_HOME`）
  - 「使用说明.txt」补充启动器与路径说明

### 验证

- 291 字符深路径（`onnxruntime_pybind11_state.pyd` 全路径 278 字符）下自检通过，5 张照片正常输出，GUI 正常运行


## v1.1.1 - 2026-10-31

### 问题修复

- **修复程序放在中文路径下启动即崩溃（`TypeError: 'NoneType' object is not subscriptable`）**
  - 根因：Windows 下 `cv2.imread` 只能按 ANSI 编码打开文件，遇到中文/非 ASCII 路径会静默返回 `None`，
    `hivision/plugin/beauty/whitening.py` 读取自带 LUT 时未做判空，直接下标取值导致崩溃
  - 新增 `hivision.utils.imread_unicode()`，统一改用 `np.fromfile` + `cv2.imdecode` 读取图片，彻底绕开 OpenCV 的路径编码限制
  - 替换全部运行期 `cv2.imread` 调用点：美白 LUT、模板照底图、美式背景底图
  - 美白 LUT 加载失败时不再让整个程序崩掉，降级为跳过美白并在控制台打印可定位的告警
  - 模板图片读取失败时抛出带完整路径的明确错误，便于排查


## v1.1.0 - 2026-10-30

### 新增功能

- **models**：引入模型包机制，拆分为带模型与不带模型两个发行包（`bb8cc95`）
  - 新增 app/model_bundle.py：模型包的生成、校验（manifest + sha256）与安装，支持启动时自动导入
  - desktop_app：新增「导入模型包（.zip）」「从文件夹导入权重」入口，AI 模型卡片显示本地模型就绪状态，版本升到 1.1.0
  - 新增 scripts/pack_models.py：用本地已下载权重打出 hivision-models-vX.zip
  - 新增 scripts/build_packages.py：一条命令产出 full（内置模型）/ slim（不含模型）两个发行包及 zip
  - 新增 scripts/gen_changelog.py：依据仓库提交记录自动生成 CHANGELOG.md
  - 更新 README 与使用说明：补充双发行包对照、模型包结构与三种补模型方式
  - .gitignore 排除 output/、build/、*.zip、models/

### 文档

- 项目介绍插入界面与输出截图，改为文图混编（`5afc54a`）
  - 新增 docs/images 下 8 张实机截图（主界面/载入/出图/深色/日志 + 3 张输出示例）
  - README 以图文混排重写：三步出片、界面主题、输出示例分区配图

## v1.0.6 - 2026-10-30

### 新增功能

- Models fetched online instead of bundled, add downloader (v1.0.6)（`8619791`）

## v1.0.5 - 2026-10-30

### 新增功能

- HivisionIDPhotos 桌面版 v1.0.5 源码（desktop_app 交互优化、模型下载适配、打包脚本）（`2d537c6`）
