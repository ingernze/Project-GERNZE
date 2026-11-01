(() => {
  // mobile/tests/native-chat-ui/cases.mjs
  var cases = [
    ["priority", "\u56DE\u590D\u5C55\u793A\u4E0E\u53EF\u9760\u4FDD\u5B58\u5148\u4E8E\u6458\u8981\uFF0C\u6700\u591A\u4E24\u6B21"],
    ["resume", "\u4E0B\u4E00\u6B21\u53D1\u9001\u62A2\u5360\u6458\u8981\u4E14\u539F\u751F\u5355\u69FD\u4E0D\u91CD\u53E0"],
    ["disable", "\u754C\u9762\u5173\u95ED\u81EA\u52A8\u6458\u8981\u505C\u6B62\u540E\u7EED\u6279\u6B21"],
    ["session", "\u754C\u9762\u5207\u6362\u4F1A\u8BDD\u505C\u6B62\u65E7\u6458\u8981"],
    ["visibility", "visibilitychange \u540E\u53F0\u4E8B\u4EF6\u505C\u6B62\u6458\u8981"],
    ["app", "app-active=false \u505C\u6B62\u6458\u8981"],
    ["pagehide", "pagehide \u9500\u6BC1\u505C\u6B62\u6458\u8981\u4E0E\u63A5\u6536\u665A\u5230"],
    ["cancel-chat", "\u754C\u9762\u505C\u6B62\u804A\u5929\u540E\u665A\u5230\u7ED3\u679C\u4E0D\u843D\u5E93"],
    ["native-busy", "\u539F\u751F\u53D6\u6D88\u672A\u9000\u51FA\u65F6\u65B0\u53D1\u9001\u6709\u9650\u7B49\u5F85\u5E76\u8FD4\u56DE busy"],
    ["timeout", "18\u79D2\u6458\u8981\u8D85\u65F6\u4E0E\u539F\u751F\u5355\u69FD\u9000\u51FA"],
    ["save-failure", "\u539F\u6587\u4FDD\u5B58\u5931\u8D25\u4E0D\u542F\u52A8\u6458\u8981"],
    ["layers", "\u6076\u610F\u6A21\u578B\u5B57\u6BB5\u4E0D\u80FD\u6539\u7B2C\u4E00\u5C42\u6216\u7B2C\u4E8C\u5C42"]
  ];

  // mobile/tests/native-chat-ui/lab.mjs
  var frame = document.getElementById("preview");
  var result = document.getElementById("result");
  var run = document.getElementById("run");
  var select = document.getElementById("case");
  for (const [id, label] of cases) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = label;
    select.append(option);
  }
  var queue = [];
  var results = [];
  var running = false;
  var show = () => {
    result.textContent = JSON.stringify({ status: running ? "running" : results.some((r) => r.status === "failed") ? "failed" : "passed", results, realProviderCalls: 0, realAndroid: false }, null, 2);
  };
  function next() {
    if (!queue.length) {
      running = false;
      run.disabled = false;
      document.getElementById("one").disabled = false;
      window.nativeUiResults = { status: results.some((r) => r.status === "failed") ? "failed" : "passed", results, realProviderCalls: 0, realAndroid: false };
      show();
      return;
    }
    const id = queue.shift();
    document.getElementById("now").textContent = cases.find((c) => c[0] === id)[1];
    frame.src = "frame.html?case=" + encodeURIComponent(id);
  }
  function start(ids) {
    if (running) return;
    queue = ids.slice();
    results = [];
    running = true;
    window.nativeUiResults = null;
    run.disabled = true;
    document.getElementById("one").disabled = true;
    show();
    next();
  }
  run.onclick = () => start(cases.map((c) => c[0]));
  document.getElementById("one").onclick = () => start([select.value]);
  window.addEventListener("message", (e) => {
    if (e.source !== frame.contentWindow || e.data?.type !== "gernze-native-ui-result") return;
    results.push(e.data.result);
    show();
    next();
  });
  document.getElementById("download").onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(window.nativeUiResults || { status: "not-run", results }, null, 2)], { type: "application/json" })), a = document.createElement("a");
    a.href = url;
    a.download = "native-ui-browser-results.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1e3);
  };
})();
