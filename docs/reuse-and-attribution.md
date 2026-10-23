# 莉宝：参考与复用清单

整理日期：2026-10-17。本页只维护来源、用途、实际取用和限制；制作经过见[制作日志](development-log.md)，代码入口见[结构地图](architecture.md)。本地工程、已发布源码和完整运行包范围不同，本页不是完整依赖许可审计或发布完成声明。

## 主要项目速览

更新：2026-10-23。这里先用简单的话介绍主要来源。项目名可点击进入原仓库；“实际使用”与“思路参考”分别列出，详细版本、来源和许可记录保留在下文。

### 角色陪伴与功能设计参考

| 项目或作品 | 简单介绍 | 与莉宝的关系 |
| --- | --- | --- |
| [Project AIRI](https://github.com/moeru-ai/airi) | 面向 AI 虚拟角色与日常陪伴的项目，结合角色展示、对话和工具能力。 | 参考人物场景、界面分层、服务配置与记忆组织。 |
| [Neuro-sama](https://www.youtube.com/@Neurosama) | AI 虚拟主播与角色作品；这里链接的是官方频道。 | 为 AI 角色与长期陪伴方向提供启发，不是本项目使用的代码库。 |
| [VPet](https://github.com/LorisYounger/VPet) | 提供桌面角色展示、动作与互动的虚拟桌宠项目。 | 参考本地互动和动作播放的组织方式，未采用其 C#／WPF 底座。 |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 将大语言模型、语音交互和虚拟形象结合的 AI 角色项目。 | 参考角色对话、历史保存与记忆相关思路，未整体接入该项目。 |
| [SillyTavern（酒馆）](https://github.com/SillyTavern/SillyTavern) | 面向大语言模型对话的前端，提供角色、用户资料和提示组织能力。 | 参考角色设定与用户资料的分块、常驻信息和上下文预算。 |
| [ZerolanLiveRobot](https://github.com/AkagawaTsurunaki/ZerolanLiveRobot) | 结合模型、语音和其他工具能力的 AI 虚拟主播项目。 | 参考人物设定、示例问答与服务分离，以及展示端协议的组织方式。 |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | 以插件扩展能力的 Agent 项目。 | 相关 Agent 生态参考；莉宝对它的接入适配尚未实装。 |
| [dsh-bili-humanism](https://github.com/InariNGT-Ofiicial/dsh-bili-humanism) | 让 DSH 获取 B 站内容、积累外部见闻与反思的扩展项目。 | 参考字幕来源、事实与观点区分、认识修正等机制；莉宝对应能力仍为独立候选，未纳入 1.1.1。 |
| [LangMem](https://github.com/langchain-ai/langmem) | 为 AI 应用提供记忆提取、整理与检索工具。 | 参考原文与摘要分离、结构化提取和反馈组织；未安装其框架。 |
| [Letta](https://github.com/letta-ai/letta) | 面向有状态 Agent 和长期记忆的项目。 | 参考常驻记忆块和只读边界，未引入 Letta 服务。 |
| [Mem0](https://github.com/mem0ai/mem0) | 为 AI 应用与 Agent 提供记忆层的项目。 | 参考记录编号、提取、修订、删除和来源追踪，未安装其 SDK。 |
| [LocalSend](https://github.com/localsend/localsend) | 在同一局域网内跨设备传输文件的工具。 | 参考传输阶段、身份与确认机制；莉宝沿用自己的配对传输通道，未接入 LocalSend 协议或复制其代码。 |

### 实际使用的主要组件与引擎

| 项目 | 简单介绍 | 在莉宝中的用途 |
| --- | --- | --- |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 支持音色微调与文本转语音的项目。 | 可选声音模块使用其本地推理引擎；引擎、环境、音色权重及参考音频与基础程序分开处理。 |
| [PixiJS](https://github.com/pixijs/pixijs) | 在网页中绘制和组织二维图像的渲染库。 | 工作台的分层人物显示与动画，现有版本为 6.5.10。 |
| [Capacitor](https://github.com/ionic-team/capacitor) | 把 Web 界面与手机原生系统能力连接起来的框架。 | Android 宿主与应用生命周期、本地通知等能力的连接。 |
| [Matter.js](https://github.com/liabru/matter-js) | 网页使用的二维物理引擎。 | 小莉宝的下落、碰撞与堆叠互动，现有版本为 0.20.0。 |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | 用 Python 构建 MCP 工具服务和客户端的官方工具包。 | 可选 Agent 接入插件与相关独立候选的通信，现有版本为 1.27.0。 |
| [ZXing Android Embedded](https://github.com/journeyapps/zxing-android-embedded) 与 [ZXing](https://github.com/zxing/zxing) | 二维码等条码的识别组件。 | 手机扫描电脑发布器的配对二维码。 |
| [python-qrcode](https://github.com/lincolnloop/python-qrcode) | 生成二维码的 Python 库。 | 电脑更新发布器生成配对二维码。 |
| [cryptography](https://github.com/pyca/cryptography) | 提供常用密码学功能的 Python 库。 | 既有热点更新链路的证书与加密支持。 |

这些组件在本地工程中的采用，不表示每个下载包都包含它们；具体以对应包的说明与随附许可为准。

### 供手机适配者选用的辅助工具

| 工具 | 简单介绍与用途 | 当前关系 |
| --- | --- | --- |
| [Maestro](https://github.com/mobile-dev-inc/Maestro) | 按预设流程自动点击、输入和切换页面，帮助重复验证操作。 | 提供参考入口，未捆绑到莉宝。 |
| [Mobile MCP](https://github.com/mobile-next/mobile-mcp) | 向 AI 提供手机截图、界面观察和操作工具。 | 供有需要的开发者自行选择，未作为莉宝运行依赖。 |
| [Appium UiAutomator2](https://github.com/appium/appium-uiautomator2-driver) | 用于 Android 界面自动化测试的驱动。 | 供较深入的界面定位与测试参考，需满足相应调试条件。 |
| [Android ADB](https://developer.android.com/tools/adb) | 连接与调试 Android 设备的官方工具。 | 可用于安装调试包、读取日志；使用者自行配置并授权设备连接。 |

其他较小范围的机制参考、历史候选、素材处理工具及具体许可入口，继续见下方登记。

## 登记规则

先有实际需求，再找成熟实现，取用能解决问题的最小部分。每项能力保持一个主要实现，已有成果优先接回；候选示例能跑不等于主干采用。状态使用“已采用组件”“外部引擎”“设计参考”“待选候选”“当前不采用”。仅收藏和下载不登记成采用。

实际采用要记版本/提交、用途、位置、修改和许可入口；只参考要写清借鉴机制及没有拿哪些代码。下表按整理时的证据记录，不承诺之后版本行为相同。阶段测试与状态变化写制作日志，来源研究快照留本地，不整份装进运行包。

## 已采用组件与外部引擎

| 项目与版本 | 实际用途及位置 | 状态与边界 |
|---|---|---|
| [PixiJS 6.5.10](https://github.com/pixijs/pixijs/tree/v6.5.10)、同版 @pixi/unsafe-eval | 工作台分层人物渲染；src/workbench/static/scene | 已采用运行组件。MIT全文与原版权见同目录LICENSE-PixiJS.txt，组件说明见THIRD_PARTY_NOTICES.txt；已有局部衣料形变不是Cubism正式绑定 |
| [Capacitor](https://github.com/ionic-team/capacitor) core/android 8.5.3、App 8.1.2、Local Notifications 8.3.1 | 手机网页与Android原生通知、应用生命周期等桥接；mobile/package.json、Capacitor插件接入 | 已用于手机工程；版本来自本地package.json，core包标明MIT，各插件与传递依赖按各自文件核对。移动工程不因这张表自动加入现行源码白名单 |
| [ZXing Android Embedded 4.3.0](https://github.com/journeyapps/zxing-android-embedded/tree/v4.3.0)、[ZXing core 3.4.1](https://github.com/zxing/zxing/tree/zxing-3.4.1) | 手机设置中的电脑配对扫码；Android原生桥接 | 已接入构建，不依赖Google Play Services；Apache-2.0声明随APK的updates-notices.txt提供。相机/华为真机实际情况与构建检查分开 |
| [python-qrcode 8.2](https://github.com/lincolnloop/python-qrcode) | 电脑更新发布器生成二维码矩阵，用Tkinter显示；mobile/update-publisher/vendor | 已采用小型生成器副本；保留BSD-3-Clause声明。没有引入Pillow、云服务或二维码Web服务框架 |
| [cryptography](https://github.com/pyca/cryptography)，该接收轮本机版本48.0.0 | 既有热点更新发布链路证书/加密支持 | 沿用现有环境；不是新增一套服务，也不把外部候选环境的其他版本冒充本机。具体分发与其依赖声明在实际打包时核对 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 本地文字转语音外部引擎，engine_worker.py导入独立推理实现 | 现有外部引擎。主项目MIT不替其他子组件、权重和录音授权；现行GitHub源码白名单不包含完整引擎、权重、录音或GPU环境 |

上表是本轮涉及的主要组件，不替代requirements、package/lock文件、发行包内LICENSE/NOTICE与完整依赖检查。本轮没有新增、升级或重新打包这些组件。源码仅白名单导出；声明“本机已使用”不等于“GitHub已包含全部运行依赖”。

## 设计参考与取舍

| 来源 | 实际借鉴的内容 | 取用程度与决定 |
|---|---|---|
| [Hello-Agents 第八章](https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter8/第八章%20记忆与检索.md)、[第九章](https://github.com/datawhalechina/hello-agents/blob/main/docs/chapter9/第九章%20上下文工程.md) | 当前对话/事件/偏好分层、相关资料选择与预算 | 设计参考，未复制教程代码或安装其记忆/ContextBuilder框架；教程与独立组件的许可分别看 |
| [awesome-llm-apps 共享记忆](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/advanced_llm_apps/llm_apps_with_memory_tutorials/multi_llm_memory) | 换API仍使用独立记忆层 | 设计参考，不直接采用。示例双密钥与将AI回答写入记忆的方式不直接适用于莉宝 |
| [awesome-llm-apps 引文核对](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/rag_tutorials/agentic_typed_rag_pydanticai) | 资料出处与原文片段核对 | 后续候选，未安装或复制；引文存在不证明整份答案正确 |
| [LangMem反馈组织](https://github.com/langchain-ai/langmem/blob/main/src/langmem/prompts/prompt.py)、[优化器](https://github.com/langchain-ai/langmem/blob/main/src/langmem/prompts/optimization.py)、[摘要示例](https://langchain-ai.github.io/langmem/guides/summarization/) | 规则/反馈/示例分离，近期原文与滚动摘要分开 | 设计参考。六级提示词采用分层思路，长聊摘要仍待候选交回；未安装LangGraph/LangMem或启用自动训练 |
| [Mem0 storage.py](https://github.com/mem0ai/mem0/blob/main/mem0/memory/storage.py)、[main.py](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py) | 记录编号、修订、删除与来源追踪 | 只参考机制，手动记忆用现有sqlite3实现；未安装SDK/向量库。关于[旧会话删除问题](https://github.com/mem0ai/mem0/issues/7452)、[历史正文](https://github.com/mem0ai/mem0/issues/6512)只作检查线索，不是主干复现结论 |
| [AIRI人物场景](https://github.com/moeru-ai/airi/blob/main/apps/stage-pocket/src/pages/index.vue)、[Tachie](https://github.com/moeru-ai/airi/tree/main/packages/stage-ui-tachie)、[providers](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui/src/stores/providers/config.ts) | 背景/人物/交互分层，少量表情回退，API供应商与人物展示分离 | 设计参考，未复制Vue/Pinia、云同步或迁移其底座；缺失表情回退不等于连续转头能力 |
| [VPet MainDisplay](https://github.com/LorisYounger/VPet/blob/main/VPet-Simulator.Core/Display/MainDisplay.cs) | 本地交互、动作播放与结束回调 | 只参考组织思路，未复制C#/WPF业务代码 |
| [Ionic按钮](https://github.com/ionic-team/ionic-framework/blob/main/core/src/components/button/button.scss)、[Primer展开模式](https://primer-docs-preview.github.com/product/components/details/) | 按钮交互状态、原生details/summary展开边界 | 仅设计参考，没有新增Ionic UI或Primer组件依赖；与实际使用的Capacitor桥接区别登记 |
| 碧蓝档案、赛马娘界面 | 人物占屏、上下导航与信息层次 | 视觉设计参考，未取用其游戏资产；v11调整过于相似的顶部组合，不据此宣称最终界面已获认可 |
| [ZerolanLiveRobot](https://github.com/AkagawaTsurunaki/ZerolanLiveRobot/tree/aad29d093295eef351da03a0bbe6ffac5539716d) | 人设/示例问答与服务分离 | 已研究，只参考。历史超限重置不满足长聊；不引入整套直播、游戏和Agent依赖，也不直接采用其记忆分支 |
| [ZerolanPlayground](https://github.com/AkagawaTsurunaki/ZerolanPlayground/tree/fb23d1ed7345d51c73e82d72b1f27750c2e62961) | 展示端协议与受控动作消息 | 仅结构参考，当前不采用Unity/AR。未确认通用仓库许可，未复制源码；加载已有Live2D模型不等于自动建模 |
| [Wenku8_Flutter](https://github.com/mikufoxxx/Wenku8_Flutter/tree/bc9a0381c3001a823b6f9f993ce4a82dc93452e6) | 缓存去重/在用保护、同步范围、不可变安装交接 | 已研究，只参考，不复制其Dart/Kotlin源码，不改写成Flutter；组合版本的GPL等声明见其NOTICE，不能把时间戳合并替换成莉宝纠错因果合并 |
| [LocalSend](https://github.com/localsend/localsend)、[Obtainium](https://github.com/ImranR98/Obtainium) | 配对身份、流式传输与系统安装状态组织 | 更新候选采用组织思路，未复制其GPL代码或引入Flutter/Rust，复用项目已有传输/安装候选 |
| [Codex压缩说明](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)、[Compaction](https://developers.openai.com/api/docs/guides/compaction) | 长任务状态保留与上下文预算 | 机制比较，未接其压缩端点或复制实现，不承诺跨供应商复用不透明项或达到同等保持能力 |

上述研究不自动产生一项新功能。缓存到实际增长时再做，示例问答需作者认可，未通过表情不因参考项目支持就启用；长聊和实际双端同步分别接回。

## 官方技术依据

- PixiJS局部形变参考 [SimplePlane 6.5.10](https://pixijs.download/v6.5.10/docs/PIXI.SimplePlane.html)；睡眠时序参考 [AnimatedSprite源码](https://api.pixijs.io/@pixi/sprite-animated/src/AnimatedSprite.ts.html) 与 [Issue6536](https://github.com/pixijs/pixijs/issues/6536)，未复制外部播放器或升级组件。
- 浏览器提前解码参考 [HTMLImageElement.decode](https://developer.mozilla.org/en-US/docs/Web/API/HTMLImageElement/decode)，画布重建边界参考 [canvas.width](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/width)。这类预加载不补齐美术中间姿势。
- 通用聊天首接参考 [DeepSeek Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)，地址/模型可配置；本地持久化参考 [SQLite事务](https://www.sqlite.org/lang_transaction.html)。
- Cubism准备参考 [PSD导入](https://docs.live2d.com/en/cubism-editor-manual/psd-import/)、[ArtMesh](https://docs.live2d.com/en/cubism-editor-manual/concept-of-artmesh/)、[眼珠XY](https://docs.live2d.com/en/cubism-editor-manual/keyform-xydirection/)、[顶点移动](https://docs.live2d.com/en/cubism-editor-manual/edit-vertices/)、[眨眼教程](https://docs.live2d.com/en/cubism-editor-tutorials/eye-blink/)。导入/网格准备不等于模型可用。
- 导出引用检查参考 [CubismWebFramework模型配置读取](https://github.com/Live2D/CubismWebFramework/blob/develop/src/cubismmodelsettingjson.ts)；参数和呼吸思路参考 [CubismWebSamples lappmodel](https://github.com/Live2D/CubismWebSamples/blob/develop/Samples/TypeScript/Demo/src/lappmodel.ts) 与 [cubismbreath.ts](https://github.com/Live2D/CubismWebFramework/blob/develop/src/effect/cubismbreath.ts)。未因这些参考复制SDK；历史参考播放器涉及pixi-live2d-display/Core时须另核对实际版本和许可，不能算当前分层场景已经使用完整Cubism模型。

## 什么情况需要说明来源

判断依据是实际取用了什么、如何分发以及其许可证，不是文件后缀，也不是改动百分比。

- 只学习思想或方法、独立写出实现：软件著作权不保护思想、处理过程、操作方法或数学概念本身。可在“参考”中致谢；不要把改写他人具体代码、文档、图表误记为只借鉴思想。
- 复制具体代码、函数、模块、文档或资源并修改：按原许可证处理；改名、改变量、改界面、转换语言或编译不能自动消除义务。
- 随EXE、APK、ZIP或GitHub仓库分发第三方代码/运行库：源码与二进制都可能有分发条件；运行包也要带适用的许可和声明，不能只在GitHub README写一句感谢。
- 只调用外部服务API且未分发其程序：这不同于把引擎装进发行包；仍按服务条款处理，若另外分发SDK，再核对SDK许可。
- 模型权重、人物图、Live2D模型和录音：各看自己的授权。买到使用权不等于获得公开上传、再分发或去署名的权限。

## 常见许可的实际区别

- MIT：分发软件副本或实质部分时，保留版权声明和许可文本。没有统一要求必须把作者名字放在应用首页。
- Apache-2.0：随分发提供许可文本，保留相关声明；修改文件注明修改。上游有NOTICE时按其第4节保留适用的声明。它也适用于对象/二进制形式。
- GPL：分发受其约束的程序时，适用对应源码、许可等要求；不能只写致谢代替。具体组合和链接方式要按实际许可核对。
- CC BY-NC-SA：适用作品的分享/改编有署名、非商业及相同方式共享条件。Hello-Agents教程仓库采用此许可；不能将“开源免费”理解为无条件商用。另一个代码组件若有独立许可，则核对该组件的范围。
- 没有许可证：公开可见不等于允许任意复制、修改和分发；先取得授权或选有明确许可的替代品。

## 莉宝声音的具体边界

GitHub现行源码只包含莉宝维护的声音接入代码及空白模板，未包含GPT-SoVITS引擎、推理环境、音色权重或录音。这是当前白名单与目录说明，不是对整个发行包的许可审计结论。

若以后把完整声音模块提供给别人，分别登记接入代码、GPT-SoVITS及其依赖、模型权重、参考音频/固定录音的来源与授权。上游GPT-SoVITS的MIT不能替其他权重、录音或依赖授权。仅改音色、改名、改色或编译均不作为省略声明的依据。

## 发布时放在哪里

作者已选择本项目自有代码采用非商业许可，见[使用范围说明](licensing.md)与根目录[LICENSE](../LICENSE)；第三方许可证不能被这份LICENSE替换。复制采用的组件保留原文件许可头和随附LICENSE/NOTICE，在THIRD_PARTY_NOTICES里登记来源、版本、用途及修改；发行包携带相应文件。只参考思路的项目列在参考区，不冒称已安装。

本页不改变仓库可见性，不上传GitHub；自身代码许可按作者已确认的非商业范围记录；内部讨论的分流不改变实际复用登记。

## 核对来源

- [计算机软件保护条例，第3、6条](https://ipc.court.gov.cn/zh-cn/news/view-407.html)
- [MIT许可原文](https://opensource.org/license/mit)
- [Apache-2.0，第4节](https://www.apache.org/licenses/LICENSE-2.0)
- [GPLv3原文](https://opensource.org/license/gpl-3.0)
- [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- [GitHub：仓库许可证](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [GPT-SoVITS主项目许可证](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/LICENSE)



## 2026-10-17 状态栏背景适配 1.0.9

继续采用现有 AndroidX Activity 1.11.0 的 EdgeToEdge/SystemBarStyle 以及 Core 1.17.0 的 WindowInsetsCompat；无新依赖。实读本机 Capacitor 8.5.3 SystemBars.java：WebView<140时原生上下padding回退会阻断背景延伸。核对 https://github.com/ionic-team/capacitor/issues/8416 、https://github.com/ionic-team/capacitor/issues/8466 与 https://developer.android.com/develop/ui/views/layout/edge-to-edge-manually ，问题报告仅作定位线索，未据此宣称复现所有版本故障。既有版本的 disable 分支确实提前return，无报告中旧版监听残留，因此保留SystemBars的DARK图标设置，关闭其Insets处理；MainActivity调用现有EdgeToEdge公开接口并把系统栏/缺口尺寸传给现行CSS变量，不再给整个WebView加系统栏padding。系统栏Insets归零传给网页，IME信息仍交原Android/WebView流程，避免另加一次键盘padding。只做本项目必需接入，无第三方代码复制。窗景和其他页面蓝底自然画到状态栏后，启动主题仍用深底。编译、签名、打包与浏览器安全区模拟通过；手机状态栏与键盘弹出仍待真机复核。


## 2026-10-17 1.0.10 小莉宝交互

沿用现有网页渲染、导航和浏览器内置Web Animations API（https://developer.mozilla.org/en-US/docs/Web/API/Element/animate），参考现有导航轻缩放方式，未安装动画库或复制第三方代码。只对左上角图标做短暂transform；页面不活动及prefers-reduced-motion时停止。移除今日计划展开卡，直接复用现行学习页，不改状态栏/人物素材/聊天。录屏白点根据画面及华为录屏支持说明 https://consumer.huawei.com/cn/support/content/zh-cn16001708/ 判断为系统触摸提示，未在应用内伪造移除结果。

## 2026-10-17 长聊核心与人设接回状态

作者委派的长聊候选与人设候选已采用到主干源码，原notes模块原样保留。继续使用Python标准库SQLite、线程、urllib，无新增依赖。前述LangMem增量摘要、Mem0来源失效问题与Zerolan角色规则组织仍只作为机制参考，没有安装框架或复制这些项目源码；本轮接回不是对其维护状态的新核验。原候选来源和读取哈希保留在主干审阅包的docs/source-provenance.json，公开机制说明见[LangMem摘要示例](https://langchain-ai.github.io/langmem/guides/summarization/)、[Mem0存储实现](https://github.com/mem0ai/mem0/blob/main/mem0/memory/storage.py)及[Zerolan固定版本提示管理](https://github.com/AkagawaTsurunaki/ZerolanLiveRobot/blob/aad29d093295eef351da03a0bbe6ffac5539716d/manager/llm_prompt_manager.py)。

主干独立执行合成/假HTTP检查并修复新人设与默认估算预算不兼容。摘要模型适配仍未采用，真实聊天与运行程序发布仍待完成；不把独立候选的可运行结果等同于全产品上线。

## 2026-10-17 摘要适配采用范围

作者委派摘要候选的summary_adapter.py已原样接入源码，主干添加适配现行预算的接线工厂；运行server暂未启用。继续使用标准库urllib/http.client/SQLite，无新增SDK或框架。参考来源仍见前述统一登记；接回示例未作为模型服务实际容量或费用依据。12项候选新增检查与1项主干组合检查通过，真实模型和手机未验收。

## 2026-10-17 双端互通任务参考补充（未采用新组件）

实读[LocalSend协议v2.2](https://raw.githubusercontent.com/localsend/protocol/main/README.md)的预备/传输/取消与校验示例；只作为阶段边界参考，沿用莉宝现有认证TLS通道，不复制其发现、认证或反向HTTP下载。实读[Capacitor本地通知官方接口](https://capacitorjs.com/docs/apis/local-notifications)与已安装8.3.1类型定义、项目现行native-reminders.js；事件通知候选要求复用现有组件，区分收取电脑事件与手机展示本地通知。阅读[ntfy Android发行页](https://github.com/binwiederhier/ntfy-android/releases)关于断网恢复、耗电和重复连接的说明，未读完整接收实现，未安装或复制其代码，不记作已选底座。外包须对新增部分继续核对真实实现、问题及许可，不能仅据参考链接声称已完成选型。

## 2026-10-17 自然待机：Live2D方法参考与现行Pixi复用

实读Live2D官方[变形器](https://docs.live2d.com/en/cubism-editor-manual/deformer/)和[物理](https://docs.live2d.com/en/cubism-editor-manual/physics-operation/)说明，阅读[WebSamples lappmodel.ts](https://raw.githubusercontent.com/Live2D/CubismWebSamples/develop/Samples/TypeScript/Demo/src/lappmodel.ts)的呼吸参数及物理updater组织、[CubismBreath](https://raw.githubusercontent.com/Live2D/CubismWebFramework/develop/src/effect/cubismbreath.ts)的周期参数更新；develop是可变分支，未固定其commit，不作为已采用依赖。只参考层级、参数映射与身体输入带动裙摆等附属的方法，未复制Live2D实现或引入SDK/Core。

运行仍复用本地Pixi6.5.10/unsafe-eval6.5.10及原MIT许可；实读[同标签Container.ts](https://raw.githubusercontent.com/pixijs/pixijs/v6.5.10/packages/display/src/Container.ts)的父子结构和绘制排序。SimplePlane.ts同标签raw读取失败，未称已读；当前项目已在character.js使用SimplePlane与顶点位置缓冲，候选优先扩展既有方法。阶段计划不是效果验证，不承诺与完整Cubism模型同等效果。

## 2026-10-18 双端候选采用边界

作者委派的记忆持久化与设备事件候选已接回主干源码，沿用Python标准库SQLite、现有浏览器IndexedDB及Capacitor LocalNotifications 8.3.1，不新增框架或复制LocalSend/ntfy实现。主干增加IndexedDB严格持久化能力拒绝护栏，并修正Windows测试句柄清理；现有配对TLS认证未替换。LocalSend、ntfy及前述记忆项目仍为思路参考。

实读本机已安装LocalNotificationsPlugin.kt的schedule/scheduleAfterPermission路径，确认未授权时可能自动请求权限，因此事件通知默认关闭，需原生护栏后再接回。浏览器存储验证不能代表手机WebView及系统通知许可行为；未发布EXE/APK或宣称真实双端同步完成。


## 2026-10-18 睡眠短过渡的方法参考

实读[Motion keyframes.ts](https://raw.githubusercontent.com/motiondivision/motion/main/packages/motion-dom/src/animation/generators/keyframes.ts)、[cubic-bezier.ts](https://raw.githubusercontent.com/motiondivision/motion/main/packages/motion-utils/src/easing/cubic-bezier.ts)、[Tween.js Interpolation.ts](https://raw.githubusercontent.com/tweenjs/tween.js/main/src/Interpolation.ts)，比较分段时间与缓动；Motion动态速度Issue #2395只作相关反馈，不作透明混合问题已解决证据。main均未固定commit，只参考方法，没有复制实现或安装框架。继续采用已有Canvas与requestAnimationFrame，短过渡不新增整套依赖。浏览器Canvas transform/globalAlpha官方接口见本轮RESULT.md。MP4仅用用户已安装Cubism附带FFmpeg转换，不捆绑它到发行包。外包任务随附现有Pixi6.5.10及原MIT声明，未含购买参考模型或私人数据。


## 2026-10-18 手臂刚性旋转小样
沿用现有Pixi6.5.10及原rotate函数，只核对rotation/pivot官方说明：https://pixijs.download/v6.5.10/docs/PIXI.DisplayObject.html#rotation 。未引入骨骼框架、复制外部代码或新增依赖；刚性旋转小样不等于完整Live2D。


## 2026-10-18 手机版抓取与前台摇晃
实际采用Square Seismic单文件ShakeDetector.java，Apache-2.0，commit b25fa2e424d843ce5ac573561cac8b5813dabee6，原始SHA256 d06a1d2ed0d08847ce65b151aecf8eb2027d6cd1f9b8b8384d54c6e0ae76aef5。来源https://github.com/square/seismic ，已约1.3k Star且2024-11-26归档；维护者说明允许fork或直接复制单文件，不把它说成持续维护的新依赖。保留源版权和mobile/licenses/LICENSE-Seismic.txt，手机开源许可入口已有Apache全文并补来源。唯一检测器改动为registerListener失败时不虚报成功，生命周期、UI采样提示和冷却由自有Capacitor薄适配负责。
比较过官方Capacitor Motion（Android实现转到web.ts，仍依赖devicemotion）和shake.js（已归档，Issue #43为旧Android WebView不触发报告）；不把该旧报告推广成所有新设备都不支持，也不新增其JS依赖。官方读取：https://raw.githubusercontent.com/ionic-team/capacitor-plugins/main/motion/src/web.ts 、https://github.com/alexgibson/shake.js/issues/43 、https://developer.android.com/develop/sensors-and-location/sensors/sensors_overview 。浏览器事件接线与算法轨迹已检查，真机感应/电量未测。


## 2026-10-18 手机独立聊天接入

沿用已安装Capacitor 8.5.3，不新增HTTP/Agent框架。读取现有Android CapacitorHttp及HttpRequestHandler实际源码、[官方HTTP接口说明](https://github.com/ionic-team/capacitor/blob/main/core/http.md)与[流式阻塞反馈7890](https://github.com/ionic-team/capacitor/issues/7890)：当前公共接口不直接提供单请求取消，先选非流式完整回复，并在自有窄桥中使用Android标准HttpsURLConnection实现断开、超时、大小限制与隐藏密钥，不复制外部HTTP实现。凭据包装依照[Android Keystore官方文档](https://developer.android.com/privacy-and-security/keystore)，使用平台AES/GCM；不是自创加密算法，也不宣称所有设备均为硬件级密钥。默认模型名按[DeepSeek官方Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)核对，兼容端点/模型可替换，真实服务商尚未调用。标准IndexedDB仅用于独立会话原文，不新装记忆框架。


## 2026-10-18 手机记忆接线：复用本项目与原生IndexedDB

复用主干CompanionMemory字段/限制、删除墓碑与memory_merge修订图格式，以及已采用event-storage.mjs的事务完成和strict durability护栏，不引入新的记忆框架。只实现手机本地记录与失效接线；未来认证scope与双端合并仍须现有配对/合并核心，不能把本机UUID当认证。实读[idb README](https://github.com/jakearchibald/idb)的升级与事务注意事项及[database-extras.ts](https://raw.githubusercontent.com/jakearchibald/idb/main/src/database-extras.ts)关于写请求与事务完成均须成功的实现，作为方法核对；未复制或安装idb。原生事务durability选项对照[IndexedDB transaction说明](https://developer.mozilla.org/en-US/docs/Web/API/IDBDatabase/transaction)。main未固定commit，不作为已引入依赖；Issue #197本轮读取失败，不引用其内容或推断已解决问题。既有原生实现足够当前窄接线，不增同职责封装。


## 2026-10-18 摘要、同步与余额

实际复用本项目summary_adapter、memory_merge、PersistentMemory及既有配对证书TLS协议；手机用既有Capacitor、Android标准HTTPS、IndexedDB，未增加Agent/同步框架。实读[LangMem短期摘要代码](https://github.com/langchain-ai/langmem/blob/main/src/langmem/short_term/summarization.py)，只参考保留近期消息与摘要回填方法；未复制安装，main未固定commit。重读[LocalSend协议](https://github.com/localsend/protocol)，只参考局域网交换边界；继续现有配对TLS，不引入LocalSend进程或声称协议兼容。DeepSeek余额沿用本项目DeepSeekProvider字段与金额验证，对照[官方余额接口](https://api-docs.deepseek.com/api/get-user-balance/)，固定GET /user/balance；无真实余额调用。实际构建与测试范围见制作日志。


## 2026-10-18 三层记忆：参考核对，尚未采用新代码

| 来源 | 本轮实际阅读与用途 | 限制/状态 |
|---|---|---|
| [AIRI memory store](https://github.com/moeru-ai/airi/blob/d70ab4dd329f451fc17eca9b894662d186c3b95d/packages/stage-ui/src/stores/memory.ts)、[tools](https://github.com/moeru-ai/airi/blob/d70ab4dd329f451fc17eca9b894662d186c3b95d/packages/stage-ui/src/tools/memory.ts)、[tests](https://github.com/moeru-ai/airi/blob/d70ab4dd329f451fc17eca9b894662d186c3b95d/packages/stage-ui/src/stores/memory.test.ts)、[PR2748](https://github.com/moeru-ai/airi/pull/2748) | 读当前实现/挂载及提交测试，核对模型受限作用域和用户通用区 | MIT；主项目本轮约50470 Star，模块2026-10-15才合并，不能称长期稳定。同名角色记忆优先于通用，与莉宝相反。设计参考，无复制/安装 |
| [Letta只读memory block文档](https://docs.letta.com/v1-sdk/memory/memory-blocks) | 核心常驻、read_only、供回答读取而不让模型改写 | 官方V1 legacy文档机制参考；当前仓库不含原block.py位置，未核对旧引擎现行实现，不新增服务/云依赖 |
| [Open-LLM-VTuber BasicMemoryAgent](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/src/open_llm_vtuber/agent/agents/basic_memory_agent.py)、[Issue126](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/issues/126) | 实读system/历史恢复与长期记忆讨论，区分历史保存和自动提取 | 约14165 Star，直接LICENSE核对MIT（示例模型另约），主分支最近推送2026-05-15；旧Issue不等于现状结论。仅参考，无代码采用 |
| [Mem0提取提示](https://github.com/mem0ai/mem0/blob/main/mem0/configs/prompts.py)、[memory实现](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py) | 实读事实提取、add/update/delete路径，作为第三层提取候选 | main未固定；本轮元数据/问题列表读取失败，不补写Star/维护/许可结论。未安装或复制，不宣称已有人工批准三层机制 |

VPet本轮核对主仓库与目录；主项目约6992Star、Apache-2.0，但未核到满足三层权限的现成聊天记忆模块，不按本体Star替插件能力背书。更具体的选型与来源可见memory-design.md。AIRI旧讨论1354/1363是2026年3月的过渡思路，新PR已在10月合并，不能再据旧讨论断言AIRI仍只有计划。现有SQLite/IndexedDB与配对TLS继续复用；本轮文档不代表运行程序已经改造。

## 2026-10-18 第一层框架研究补充（仅参考，外包待回传）

本轮实读[SillyTavern Character Design](https://docs.sillytavern.app/usage/core-concepts/characterdesign/)、[Personas](https://docs.sillytavern.app/usage/core-concepts/personas/)与[Prompt Manager](https://docs.sillytavern.app/usage/prompts/prompt-manager/)，核对角色核心与用户资料分块、常驻内容和例句的不同保留方式、提示预算成本；仅用于框架研究，不引入角色卡系统、复制代码或安装依赖。重读Letta官方V1 memory blocks，确认默认读写、可设read_only；不能将核心常驻等同不可改写。AIRI旧固定快照本轮网络访问失败，留待独立复核。框架建议由独立研究任务回传后审阅，尚未修改运行方案或私人设定。

## 2026-10-19 聊天历史与设置收起（仅参考，无新依赖）

本轮读取[Matrix ScrollPanel实际代码](https://github.com/matrix-org/matrix-react-sdk/blob/develop/src/components/structures/ScrollPanel.tsx)，参考默认跟随最新、往前补消息时保持原阅读位置的职责划分；未复制React组件、引入Matrix或更改许可依赖。分支未固定commit，相关Issue读取失败，不据此声称已核实所有上游问题或性能。设置沿用工程原生details/summary；核对[Shoelace仓库](https://github.com/shoelace-style/shoelace)已转向Web Awesome，不为几个现有表单增加Lit/整套组件依赖。实际验证仅对应本项目浏览器合成数据，见制作日志。

## 2026-10-19 桌面记忆书架接回（沿用交付，不增加运行库）

复用作者交回的桌面适配及书架组件，生产文件memory-books.js/css与封面由完整候选提供；候选说明将来源标为作者确认的v10书架交付（原ZIP SHA256 6897b7f8f1fd2653e58d3b623f168c00a2dc39a720e5c0ee684a4b30dcebb5bd，主干本轮未重新取得原ZIP核验）。主干核对完整交付234项哈希及CRC，保留10—12月已确认范围；其他九个月花仍是原提案，不提升为美术定稿。SQLite事务、现有ConversationStore、ContextManager和原生DOM继续复用，无新运行时依赖；测试夹具未进入产品数据。


## 2026-10-19 手机书架复用与自动化候选

手机复用当前主干memory-books.js/css与已有createMemorySource、ChatJournal及分层archive；不增加UI框架。真实存储与纯视觉月册之间保持只读数据接口，预览夹具不进入APK。

按作者截图研究[Mobile MCP](https://github.com/mobile-next/mobile-mcp)、[Maestro](https://github.com/mobile-dev-inc/Maestro)、[Appium UiAutomator2](https://github.com/appium/appium-uiautomator2-driver)、[Mobilerun](https://github.com/droidrun/mobilerun)及openatx/uiautomator2。均为自动化工具候选，未安装/接入。Mobile MCP可通过ADB操作Android真机，但[路线图](https://github.com/mobile-next/mobile-mcp/blob/main/ROADMAP.md)专门WebView支持仍计划中；实读mobile-device.ts的UI树递归及截图/点击转发，并对照[#399](https://github.com/mobile-next/mobile-mcp/issues/399)历史缺失子节点问题，当前代码已有递归，不能继续当现存Bug。仍有混合应用[#175](https://github.com/mobile-next/mobile-mcp/issues/175)及中文输入等反馈，不能保证华为即插即用。

Maestro支持MCP与YAML固定流程、Windows本地安装、混合应用，为首轮验证候选；[#3497](https://github.com/mobile-dev-inc/Maestro/issues/3497)报告WebView150+输入框可访问性变化、[#3019](https://github.com/mobile-dev-inc/Maestro/issues/3019)报告devtools输入首字问题，需结合作者设备确认。Appium明确支持NATIVE/WEBVIEW切换，但要求可调试WebView与匹配Chromedriver，作为DOM定位不足的备选；不为正式发行版默认开启调试。Mobilerun支持多模型/手机Agent，但需Portal及无障碍，暂不为UI验收增加一套规划执行框架。开源许可分别Apache-2.0（Mobile MCP/Maestro/Appium driver）、MIT（Mobilerun/openatx），实际采用前固定版本并补许可证。仅调研和建议，不作为已选型或已完成工具安装。


## 2026-10-19 手机适配工具的公开入口（仍未采用）

再次核对[Maestro README](https://github.com/mobile-dev-inc/Maestro)、[Mobile MCP README](https://github.com/mobile-next/mobile-mcp)及[WebView路线图](https://github.com/mobile-next/mobile-mcp/blob/main/ROADMAP.md)、[Appium UiAutomator2上下文机制](https://github.com/appium/appium-uiautomator2-driver#context-management)、[ADB官方说明](https://developer.android.com/tools/adb)。README提供链接及适配流程供有需要者按需取得工具和项目源码，未捆绑、复制或安装外部组件，不新增运行依赖。Maestro/Mobile MCP/Appium采用Apache-2.0，Android SDK工具按Google相应许可使用，不将工具参考视为取得人物素材再分发授权。


## 2026-10-19 电脑版场景候选接回

采用随电脑版交付包提供的Matter.js 0.20.0（MIT，Liam Brummitt），源码 https://github.com/liabru/matter-js ，复用随包的本地构建与完整许可证。已读取上游softBody示例与本次适配源码；小莉宝物理交互由该组件提供，页面离开时清理。候选关于历史Issues的描述属于供应方报告，本轮未据此宣称全部问题已复核。未加载用户提供的物理JSON，不新增运行时网络依赖。

书架使用作者提供并确认的手机金色书板、框架、茶杯、原月册封面，以及既有memory-books只读数据接口；电脑端按最新要求移除平放样式。brand-jelly.js沿用已交付版本。资源的个人项目使用与公开再分发授权分开，不能由本地接回推导公开许可。来源索引和MIT许可随src/workbench/static/vendor保留。


## 2026-10-20 分层同步与可选Codex插件

分层同步复用已有memory_merge.py因果图、删除墓碑与明确决策机制，以及既有配对TLS/SQLite/IndexedDB；仅为二三层加带来源的适配，不引入新的同步框架。摘要及元数据与因果节点的SHA256绑定，第一层和原始会话不在交换包。

可选插件按[OpenAI官方插件规范](https://developers.openai.com/plugins/build/plugins)打包已有stdio MCP和Skill，复用MCP Python SDK 1.27.0。完成提醒采用[官方Stop事件](https://learn.chatgpt.com/docs/hooks)，仅取session_id/turn_id，不读取transcript_path或消息正文。宿主会要求首次信任；本地marketplace仅发现插件，不自动信任钩子。通知复用Capacitor LocalNotifications 8.3.1和已交付事件收件箱。没有执行本轮安装/卸载功能验收或真机验证，不能把上游支持记为本机已通过。


## 2026-10-20 联网浏览交付接收与Codex适配

接收外包的标准库只读候选，研究说明列OpenBiliClaw/Agent-Reach/OpenCLI/browser-use为参考，未安装或复制整套框架；本轮主干没有重新把其Stars/实测宣称当作自身证据。Codex薄适配复用项目已使用的[官方MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)1.27.0（MIT）及现有FastMCP/ClientSession调用方式；仅可选适配依赖该SDK，未升级、未新增模型服务或复制SDK源码。真实MCP握手和公开B站搜索已在独立候选验证，正式宿主插件接回仍待统一合并。

## 2026-10-20：记忆同步原子提交修复（已实现，验收见版本说明）

参考 [IndexedDB IDBTransaction 规范接口](https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction) 和 [Dexie 事务实现](https://github.com/dexie/Dexie.js/blob/master/src/classes/transaction/transaction.ts) 的同事务提交/中止边界，仅参考机制，未复制其源码或新增依赖。复用本项目 IndexedDB 和 SQLite：同库独立 object stores，共同 readwrite 事务，异步哈希在事务外完成，事务内重新核对全快照。避免跨库分步写入及进程内 Promise 队列不能约束其他窗口的问题。

## 2026-10-20：手机第四层增量上传（已采用项目既有组件）

参考 [Joplin Synchronizer](https://github.com/laurent22/joplin/blob/dev/packages/lib/Synchronizer.ts) 的分批、确认和可续传边界，并复核 [SQLite 事务说明](https://www.sqlite.org/lang_transaction.html)。不复制 Joplin 代码、不引入整套同步依赖；复用本项目配对TLS、SQLite事务、摘要来源索引与书架投影，新增纯文字归档接线。Joplin为机制参考，本项目无Joplin兼容或全量同步承诺。


## 2026-10-22 电脑自动审核第三层（独立候选）

复核 LangMem src/langmem/knowledge/extraction.py 的结构化记忆结果与存储处理职责分离，仅参考机制，不安装框架或复制代码。实际复用既有 SummaryAdapter 有界HTTP、MemoryLayers 事务/收据、SQLite 和分层同步。版本保护不等于语义准确保证；真实模型语义、正式运行程序尚未验收。来源：https://github.com/langchain-ai/langmem/blob/main/src/langmem/knowledge/extraction.py 。


## 2026-10-22 电脑版入场动画清晰度增强第三版

已采用本地生成结果，未将超分工具、模型或FFmpeg捆绑进程序。使用 [Real-ESRGAN NCNN Vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) 官方20220424 Windows发行包，模型 realesrgan-x4plus-anime 原生4倍后缩至1984×1248；工具仓库MIT，Real-ESRGAN主项目BSD-3-Clause，人物原素材授权仍独立处理。发行包SHA-256：abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d。

复用本机已有FFmpeg n5.1.6-21-gc0067757ab的 [CAS滤镜](https://ffmpeg.org/ffmpeg-filters.html#cas)，strength=0.8；[AMD FidelityFX CAS](https://github.com/GPUOpen-Effects/FidelityFX-CAS)为算法来源参考，无另行复制其代码。模型RGB与原视频alpha分别处理，最终VP9 CRF12。工具和逐帧缓存已清理；本轮实际验证是本地媒体解码、浏览器播放及用户视觉确认，不宣称恢复真实丢失纹理或新增运行时AI能力。

## 2026-10-23 浏览取证与外部见闻（独立0.2小样）

参考 [dsh-bili-humanism](https://github.com/InariNGT-Ofiicial/dsh-bili-humanism/tree/22cbb1d8d44a95d325bf4fcf916792b773cf1e17) 的字幕来源、时间覆盖、事实/作者观点/推测/认识修正分栏。已阅读其读取、人格摘句、预算、定时获取代码及Issues 5/7；仅设计参考，未复制其Node/DSH bundle，未采用自动人格写入、账号操作或ASR。本次复用原只读浏览候选的固定HTTPS传输、取消预算、同源会话保护及现有MCP Python SDK；独立SQLite外部见闻，不写主程序四层记忆。可选抽帧只调用本机已存在的FFmpeg，未捆绑工具、模型或新增下载依赖。候选不属于正式1.1.1发行附件，许可继续按项目及THIRD_PARTY分别处理。

## 2026-10-23 当前Codex自主探索附加模块（0.3试装）

复用本项目浏览候选、MCP Python SDK 1.27.0、SQLite和现有可选插件打包结构，不另开模型、读取Codex认证或新增Agent框架。参考 [AutoGen终止机制](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/termination.html) 及其 _terminations.py 的用量/时间/目标满足停止区分，仅参考、不复制源码；其Token计量不等于本机Codex五小时额度。宿主额度字段按 [OpenAI App Server](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt) 的account/rateLimits/read核对，实际接线由宿主get_usage_limits提供最小快照。dsh-bili-humanism的UTF-8字节估计不用于账号额度换算。本轮只作可选试装，不纳入已准备的1.1.1发行附件。

## 2026-10-23 自主探索闭环增强接回

接收供应方SOURCE_DESIGN.md中的MediaWiki Search/TextExtracts及Wikimedia User-Agent/复用说明研究，未引入上游代码或新依赖；主干审阅固定参数HTTPS传输、来源绑定、取消和默认关闭。Wikipedia导言适配仍为停用候选，真实可达性与许可/署名接入未完成，不记为正式采用或视频理解。现有MCP SDK/SQLite继续复用。


## 2026-10-23 自主探索额度与无正文收尾接回

接收供应方对[AutoGen终止源码](https://github.com/microsoft/autogen/blob/main/python/packages/autogen-agentchat/src/autogen_agentchat/conditions/_terminations.py)、教程及Issue #6826的有限研究，仅参考有限事件计数与停止后拒绝动作；未复制代码或引入框架。主干本轮核验实际改动与离线回归，不把供应方研究当作平台成功率或额度预测依据。安装说明另外按[OpenAI插件打包文档](https://developers.openai.com/plugins/build/plugins)与本机CLI核对，发现/缓存/加载分开处理；原有SDK和SQLite依赖不变。
