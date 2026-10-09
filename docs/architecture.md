# 赫宝现行结构与阅读入口

核对日期：2026-10-09。基线为已部署的Windows桌面程序及已上传的源码，不是旧源码候选目录。先读本页，再沿目标功能阅读；不要求先通读全仓库。

## 系统边界

```text
Windows桌面宿主（Tkinter＋Win32）
  ├─角色渲染与动作调度：PNG清单、锚点、定时回调
  ├─工作台宿主：本机HTTP服务 → 浏览器HTML/CSS/JS
  │   └─有限JSON命令 → 数据与设置逻辑 → SQLite／JSON
  └─声音控制
      ├─固定录音 → Windows播放
      └─后台任务 → 独立GPT-SoVITS推理进程 → WAV → 播放
```

工作台仅监听127.0.0.1，端口由系统分配；每次服务启动生成会话凭据。外部聊天API是声音功能的可选配置，与本机工作台会话凭据分开。应用没有自动长期对话记忆，也没有内部MCP。

## 按任务找文件

以下路径相对仓库根目录。

| 功能 | 先读 | 然后按任务读取 | 主要验证 |
| --- | --- | --- | --- |
| 桌面启动、单实例、退出 | `src/deepseek_trial.py`、`src/app.py` | `src/tray_win32.py`、`src/win_bridge.py` | `src/tests/test_bridge_dispatch.py` |
| 人物美术、缩放与切换 | `src/style_resources.py`、`src/style_controls.py` | `src/app.py`中的帧加载和播放 | `src/tests/test_style_resources.py`（需要图片） |
| 眨眼、睡眠、摆腿与参数 | `src/activity_timing.py`、`src/autonomous_actions.py` | `src/idle_blink.py`、`src/foot_sway.py`、`src/manual_actions.py` | `src/tests/test_activity_timing.py`、`src/tests/test_foot_sway.py` |
| 拖拽、惯性、走路 | `src/grab_sway.py`、`src/hebao_inertia.py` | `src/walk_trial.py`、`src/walk_controls.py` | `src/tests/test_inertia.py`、`src/tests/test_fourway_walk.py` |
| 浏览器窗口与服务生命周期 | `src/workbench_host.py`、`src/workbench_window.py` | `src/workbench/server.py`、`src/workbench/entrance.py` | `src/tests/test_workbench_window.py`、`src/tests/test_entrance_session.py` |
| 工作台页面和导航 | `src/workbench/static/index.html`、`src/workbench/static/app.js` | `modules.js`（页面）、`runtime.js`（注册及释放）、`frame.js`／`layout.js`／`style.css` | `src/workbench/tests/` |
| 工作台接口 | `src/workbench/server.py`中的CONTROL、`src/workbench/bridge.py`中的CONTRACTS | Handler、validate_call及Bridge.call | `src/tests/test_paper_study.py`、`src/tests/test_activity_timing.py` |
| 六级提示词与汇报 | `src/hebao_modules/daily_study.py` | `prompts.py`、`handoff.py`、`security.py` | `src/tests/test_daily_study.py`、`src/tests/test_paper_study.py` |
| SQLite、项目记录、提醒 | `src/hebao_modules/core.py` | `registry.py`、`reminders.py`、`capabilities.py` | `src/tests/test_local_snapshot.py`、`src/tests/test_daily_study.py` |
| 固定语音、音量、场景绑定 | `src/scene_voice.py` | `src/voice_bindings_window.py` | `src/tests/test_scene_voice.py`、`src/tests/test_voice_volume.py` |
| 文字转语音、取消与模型选择 | `src/voice_module.py` | `src/voice_text_window.py`、`Hecate_Voice_Module/voice_backend.py`、`engine_worker.py` | `src/tests/test_voice_module.py`、`src/tests/test_workbench_voice.py` |
| 可选模块安装与移除 | `src/optional_modules.py` | `src/module_packages_window.py`、`src/package_optional_modules.py` | `src/tests/test_optional_modules.py` |
| 打包发行、隐私边界 | `src/build_modular_release.ps1`、`source-files.json` | `tools/export_source.py`、`.gitignore`、`docs/source-package.md` | 文件清单与导出校验 |

## 两条典型调用链

保存动作设置：`modules.js`收集参数 → `app.js`向`/api/call`提交`behavior.set` → `server.py`校验 → 桌面事件桥通知`app.py` → 保存JSON并调整定时任务。源码中同名命令与参数契约是迁移依据。

保存学习汇报：`modules.js` → `app.js` → `bridge.py`的`daily.save` → `daily_study.py`解析／保存 → `core.py`的SQLite事务。教学提示词与历史参考是数据，不能作为宿主指令执行。

## 生命周期与命名

界面更新归Tk主线程；耗时声音任务在后台执行，模型在独立进程加载。取消与退出使旧结果失效，防止延迟补播。声音空闲约120秒结束自有引擎。前端Scope与AbortController负责切页释放事件、请求与清理函数。

美术第一套是插画，内部ID仍为style2；第二套是像素备用，内部ID为original。不要按旧ID猜展示顺序。声音第一／第二套是另一个编号体系。`deepseek_trial.py`虽保留历史文件名，仍是当前正式桌面入口。`MemoryModule`和`memory.*`是现有项目记录接口，不等于自动对话记忆。

## 测试与素材边界

Python桌面依赖见根目录requirements文件。前端运行无需npm构建；DOM测试需要Node.js和jsdom，`daily_study.test.cjs`还调用Python夹具，通过HEBAO_PYTHON指定解释器。本仓库尚无jsdom锁版本及package-lock。

涉及真实PNG、WAV、视频、Tk窗口、Win32或GPU的测试需相应资源和平台。独立数据测试与API夹具不能被当成手机版验收。完整人物动作、声音模型、推理引擎依赖和运行环境不在仓库中；当前只有一张F00人物示例图。
