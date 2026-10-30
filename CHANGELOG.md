# 更新日志

本文件由 `scripts/gen_changelog.py` 依据仓库提交记录自动生成，请勿手工编辑。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。


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
