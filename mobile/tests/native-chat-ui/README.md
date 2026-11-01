# 真实页面代码 + 原生桥替身联调

此目录实际打包了冻结输入的 `native-chat.js`、`dialogue-page.js`、journal、transport、分层记忆和设置面板。测试只替换 `@capacitor/core`、人设/核心的外部读取及系统环境输入，不替换 journal/transport，不调用生产模型。

## 打开

已附 `lab.html`、`frame.html` 和两个 bundle，可不安装依赖直接使用。请从本目录启动：

```bash
python -m http.server 8768 --bind 127.0.0.1
```

浏览器打开 `http://127.0.0.1:8768/lab.html`，点击“开始全部检查”，或选一项情景运行。全部情景约需半分钟，其中摘要超时保留生产 18 秒定时，假桥也保留原生 16 秒停止请求时点。每项用新的 iframe 和随机数据库前缀；结果含实际 trace、逐项断言和测试库清理结果。

页面所用人物为纯色占位，不做美术验收。输入为 40 轮合成对话，人物与核心为明确标记的合成内容，第一层和第二层均有哨兵值。没有真实密钥、配对、个人库或外部模型连接。

## 重建与自动跑

在 `mobile` 目录执行已有锁文件对应的 `npm ci --ignore-scripts`，然后：

```bash
node tests/native-chat-ui/build.cjs
node tests/native-chat-ui/bridge.test.mjs
python tests/native-chat-ui/java-contract.py
```

重建使用项目已有 esbuild，没有新运行依赖；唯一 alias 是 `@capacitor/core -> capacitor-double.mjs`。`build-inputs.json` 记录被打包的实际文件与 SHA256。

若本机已有 Playwright 和 Chromium：

```bash
NATIVE_UI_RESULTS=/absolute/output node tests/native-chat-ui/run-browser.cjs
```

可选环境变量 `NATIVE_UI_CHROMIUM` 指向现有浏览器；`NATIVE_UI_VIDEO=1` 请求录屏。脚本不下载、不安装浏览器。无浏览器会写 skipped，不能当通过。Windows PowerShell 请使用 `$env:NATIVE_UI_RESULTS=...` 等等价写法。

## 范围与限制

- “visibilitychange”情景在测试 iframe 内覆写 document.hidden 并派发真实事件处理入口；“app-active=false”和 pagehide 也是合成事件。它们无法证明 Android 真实生命周期会及时派发这些事件。
- 假桥取消按 id 匹配，取消确认立即返回，但请求槽只有 I/O 退出才释放；取消不合作情景保持旧槽占用。已由原生 resolve 排队、尚未送至 JS 的结果可以晚到，这不同于假造一个取消后仍被 Java 接受的 HTTP 成功。
- Java 检查是源码合同核对，17 项文本断言，未编译或运行 Java/Android。
- `priority` 严格检查摘要启动时实际回复已在页面展示且 pending=false。源码中 native wrapper 还会 await refreshHistory，因此需要真实浏览器确定调度先后；不要在未实跑时把它记成通过，或为了过测放宽这条断言。
- 首次执行页的检查和 cleanup 都仍待浏览器运行。本交付环境只有构建、语法与假桥合同检查通过，未产生浏览器通过记录或录屏。


## 2026-10-24 当前主干复验

已按当前com/gernze/companion/LibaoChatPlugin.java路径适配源码合同检查，并重建实际输入bundle。主干Edge真实DOM/IndexedDB与假桥的12组检查通过，含保留生产18秒摘要超时；10项假桥及17项Java源码检查通过。Java/Android编译另由同轮release候选成功补验，不将模拟页面扩大为真机验证。下文旧“尚未实跑”属于原交付环境限制，当前结论以本节及本轮PHONE-CHECKS.json为准。
