# GERNZE 1.1.9 源码更新

2026-11-08，Android 构建 56。公开可直接下载安装的版本仍是 [1.1.2](https://github.com/ingernze/Project-GERNZE/releases/tag/v1.1.2)。

| 变化 | 当前范围 |
| --- | --- |
| 手机对话 | 全屏、底部输入框、回到原页面和草稿保留。书架引用和网页来源随回复折叠。 |
| 手机记忆 | 长对话接近本地预算时提前整理旧轮次。最近六轮及完整原文保留，已同步的普通书架可按话题有限取材。课程资料单独只读。 |
| 手机语音与网页 | 点击麦克风进行本地语音识别，文字可编辑后发送。支持兼容连接按需搜索公开网页，实际搜索和费用取决于服务。 |
| 手机书架 | 按年月从左到右排列，选书时保留邻书点击区域，书架控件避开 Android 系统栏。 |
| 配对更新 | 有匹配基线时优先传差量，手机重建并验证安装包。准备时显示状态，确认下载方式后再显示实际传输量。 |

## Android 构建

在具备 JDK 21、Android SDK 36、Gradle 8.14.3 和匹配的授权美术资源时，在 mobile 运行 npm ci、npm run build:web、npx cap sync android，再进入 android 执行 Gradle assembleRelease。额外通过 -PlibaoSherpaAar 指定 [sherpa-onnx 2.0.1 官方 Android AAR](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1) 中的静态链接 ONNX Runtime 版本。项目按 app/build.gradle 中锁定的 SHA-256 核对。语音模型按需用 -PlibaoSpeechModelDir 指定 Android assets 根目录，目录和文件摘要见 SherpaModelAssets.java。模型和 AAR 分开获取。

默认网页构建使用基础角色模板及空白个人核心。素材、签名和配对配置按 [源码与分发说明](source-package.md) 准备。浏览器示例和 Android 构建检查覆盖主要改动，手机型号、键盘与系统栏显示以及语音响应时间仍需要实机确认。
