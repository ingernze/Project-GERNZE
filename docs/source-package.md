> 2026-10-23 上传准备：现行白名单为 438 项，包含作者确认的 README 和 13 个实际引用的展示文件；正式桌面入口为 `src/desktop_main.py`。展示图片并非完整运行素材包，模型与语音环境仍另行提供。下文较早的文件数量与路径属于历史快照。

> 当前公开源码白名单425项（2026-10-22），用于1.1.1发行准备。安装包与源码验证分别记录；最新说明见 [1.1.1](release-1.1.1.md)。下文旧版本记录不作为现行完成状态。

> 2026-10-20 授权已确定：本项目自有代码采用非商业许可，允许个人使用、修改和免费分享，商业使用须另行书面授权；素材与第三方内容分别处理。见 [使用范围说明](licensing.md) 和根目录 [LICENSE](../LICENSE)。

> 2026-10-20 补充：1.1.0/code29 已加入手机第四层纯文字、时间和来源编号的增量上传；电脑统一审查第三层，第二层结果回传手机。设置中可手动同步，也可设置至少1天的前台连通传输间隔。第一层和密钥仍不传。下文早期“原文不传”描述已由此要求替代。

> 当前状态（2026-10-20，1.1.0）：以 README 与 docs/release-1.1.0.md 为准。下文的旧文件数与“手机/记忆未接入”均为历史记录，不代表现行版本。

## 当前构建与资源条件

Windows：Python 3.12，安装根目录 requirements-desktop.txt 与 requirements-build.txt 后，准备匹配素材和模块清单，执行 src/build_modular_release.ps1。默认 -BuildMode public；私人模式须显式 -BuildMode private。两者使用独立生成目录，均不扫描私人数据库、不修改原人设和基础资料。

Android：Node/npm 按 mobile/package-lock.json 安装依赖（npm ci），JDK 21、Android SDK 36、Gradle 8.14.3。准备匹配且可分发的 mobile/www 资源、Android 启动图标等资源后，在 mobile 运行 npm run build:web，再运行 npx cap sync android，配置本机 SDK 路径后，在 mobile/android 用 Gradle assembleRelease 构建。源码未发布本机 local.properties、签名密钥或完整素材，因此源码导出不是开箱即用安装包。公开发行应使用 release，验证不可调试；签名由发行者自己的密钥完成，密钥不得进入 Git。不要直接改生成的 native-bridge.js 代替其 mobile/src 源码。

本轮补齐自有安装、下载缓存、配对凭据存储和扫码 Activity 源码，及 Android/npm 必要构建元信息。cap sync 生成的依赖路径使用相对 node_modules 路径。未把实际凭据、证书、SDK 路径、生成 APK 或私人配置放入白名单。

# 源码内容与验证范围

仅从 `source-files.json` 白名单导出；新文件需要审查后加入清单。`.gitignore` 默认忽略未列入清单的文件，包括个人记录、模型、环境、历史交接和未获准收录的素材。当前明确放行的单张人物图为 `src/assets/styles/style2/F00.png`。源码更新由 `tools/export_source.py` 复制并逐项校验，不扫描或读取Windows凭据。

当前源码包含模块安装／移除、动作参数、随机眨眼、睡眠与摆腿调度，以及当前声音和工作台代码。中国英语六级学习、固定场景语音、本地文字转语音的模块安装和移除已实现，支持保留个人数据；这不等于任意第三方插件都能接入。内部MCP、自动记忆与自我迭代、Codex网页监测尚未接入；2026-10-16新增的是用户主动保存、纠正和忘记的陪伴记忆源码，不等于手机同步已接入。

学习库默认空白，运行时不导入作者资料。`tests/fixtures` 与测试代码使用隔离环境生成的虚构样本，用于兼容／迁移验证，不是作者的学习记录，也不会随模块安装导入。部分遗留界面含用户主动选择的演示入口；公开前的教学界面范围仍需核对，不能将源码测试样本当成正式六级题。

## 环境与入口

当前Windows 11 x64、Python 3.12桌面链路已在开发机验证。桌面依赖见 `requirements-desktop.txt`，构建依赖见 `requirements-build.txt`。前端是原生JavaScript、CSS及HTML，无前端打包步骤；部分开发测试另需Node.js与jsdom。依赖不会因下载源码自动安装。

完整构建先准备匹配素材，再执行 `src/package_optional_modules.py --output <模块输出目录>` 生成模块清单，最后用 `src/build_modular_release.ps1 -PythonExecutable <构建Python> -ModuleCatalog <模块清单路径>` 构建。构建默认使用空白交接数据。`build_dev_release.ps1` 仅保留为旧兼容入口。

文字朗读须另装推理模块，提供配套权重和参考音频；此仓库不提供模型和GPU环境。原生观察组件由构建脚本使用Windows系统编译器编译，不读取聊天正文。

## 验证边界

首次162文件源码快照已检查逐项一致、ZIP完整、Python与前端语法及108项选定测试；108项测试临时使用空白交接模板，测试后已移除。随后用户在 `6090fe9` 中加入一张 F00.png，白名单共163个文件。原162文件ZIP和验证报告是历史快照，不包含后来新增的图片。涉及PNG、WAV、视频、真实模型或桌面窗口的测试需要补齐资源，不能把骨架验证描述成完整成品验收。已有远程提交：`c6b369e` 为首次源码上传，`6090fe9` 为用户亲自操作的待机图上传。本次状态修订仅涉及文档，没有新增训练或下载模型。

GitHub项目说明、截图、素材授权及许可证留到公开前由作者决定；本次不代写正式项目介绍。


## 移动端评估交接（2026-10-09）

现行运行源码经本地导入关系核对已包含在白名单中。新增两份结构与迁移文档后白名单为165文件；F00仍是唯一人物图，供另一个AI阅读结构而非直接启动手机应用。未纳入的package_frontend_handoff.py是旧前端交接打包器，当前入口不引用。语音接入源码已收录，GPT-SoVITS引擎本体、GPU环境和权重另行准备；它们不因本次交接而上传。


## 操作指南（2026-10-09）

新增 `docs/user-guide.md`，说明当前Windows启动版的日常使用、学习保存、动作设置、固定录音、文字朗读、声音API、音色导入、模块安装移除与备份边界。已按源码按钮及保存规则核对，没有新增或改动运行功能。白名单由165增加到166项；原165文件移动端交接ZIP保留为当时的已上传快照。两处固定语音窗口的旧画风／缺睡眠提示和模块完成提示的按钮称呼差异，已在指南中明确，不因文档修订重新构建EXE。


## 制作与学习记录的分发范围（2026-10-17）

`docs/development-log.md` 是面向仓库读者的制作日志，本轮加入源码导出白名单；参考组件与设计来源仍集中在 `docs/reuse-and-attribution.md`。它们记录的是本地制作快照，不自动意味着文档、运行代码或安装包已经提交/推送。

维护AI与作者共用的 `local-notes/` 只保留在本机，未列入 `source-files.json`，并由 `.gitignore` 明确排除。该排除适用于普通Git操作与现有白名单导出器；显式强制添加或另外手工打包仍可绕过，发布前不要用整目录打包替代白名单导出。


## 基础人设与空白记忆（2026-10-18）

源码只分发src/workbench/companion_persona.example.md基础角色模板；完整companion_persona.md和所有个人记忆/会话库留在本机，不在白名单。干净源码缺少本机完整人设时，加载器自动用基础模板；自行定制可在本机建立companion_persona.md，该文件保持忽略。基础模板不预填用户档案或共同经历。不要用git add -f将私人版本或数据库加入提交。


## 2026-10-19 骨架与可选插件分开下载

用户确认：同一GitHub项目提供骨架与独立可选插件；默认下载只取得骨架，不携带或自动下载Codex接入插件。README及Release说明先放电脑/手机骨架入口，下方另列可选模块，各文件独立下载，标明适用平台、兼容骨架版本、依赖、安装及卸载方法。固定场景录音仍属于骨架，API语音/文字朗读按现有模块边界另行分发；不因本次决定重新拆分人物场景。

GitHub Releases支持多份独立附件及每份附件的直达下载链接。仓库自带的Source code ZIP包含该版本已提交的全部源码，不是仅骨架安装包；不能把绿色Code/Download ZIP作为普通用户的默认安装入口。下载插件ZIP也不等于Codex已安装插件，正式发布须补齐宿主插件清单、依赖准备与安装/卸载验证。

Codex接入继续复用agent-bridge现有MCP与Skill，不另做聊天模型、不自动收集未授权对话。公开包只包括通用代码、基础角色模板及空白资料；私人人设、第一层个人资料、第二至四层用户库、settings.local.json、密钥和配对凭据不发布。运行状态与个人配置应放在插件缓存目录以外，卸载默认保留个人资料；不改写宿主全局配置以冒充可卸载插件。已有手工注册的gernze连接与全局Skill需在迁移时核对重复，当前不删除或更换。

本轮只确认分发方案并补充说明和精确白名单；没有生成正式插件安装包，没有实测宿主安装/卸载，没有提交或发布GitHub。后续发布前检查骨架附件不包含插件文件，独立插件包可启动且卸载保留数据；最终GitHub提交由用户执行。

依据：[GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)、[独立附件链接](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)、[Codex插件打包](https://developers.openai.com/plugins/build/plugins)、[插件安装与移除命令](https://learn.chatgpt.com/docs/developer-commands)。
