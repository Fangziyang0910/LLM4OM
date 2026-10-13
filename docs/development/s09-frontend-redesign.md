# S09-D Workbench 前端重构(React 迁移与用户界面重做)

按[前端重构问卷](../design/frontend-redesign-questionnaire.md)的确认方向(垂直故事流、呈现优先不动后端契约、引入框架 + 构建链、浅色精修),spec [#86](https://github.com/Fangziyang0910/LLM4OM/issues/86) 拆为 #87–#93 六个实现工单与一个收尾工单,2026-10-13 全部交付。本页记录结构与验收口径;各工单的证据以对应 issue 评论为准。

## 结构

- `frontend/` 为独立前端源(React 18 + Vite 5 + TypeScript),`npm --prefix frontend run build` 先过 `tsc --noEmit`,再以**固定文件名**(`index.html`/`app.js`/`style.css`)产出到 `src/llm4om/web_assets/`,随 Python 包经 importlib.resources 分发;`emptyOutDir` 保证产物目录无手写残留。
- workbench 服务(`web.py`)的静态路由表与 CSP(`script-src 'self'`,无 CDN)完全不变,运行时零外部网络依赖。原手写 `visuals.js` 等源删除。
- 关键 DOM 契约在迁移中保持:窗口全局(`snapshot`/`currentJob`/`selectedRun`/`editParent`)、`window.UI` 命令式门面(经 flushSync 挂载,WeakMap 复用根)、`.timeline-step[data-artifact]` 仅由方法事件产物引用生成(OptiMUS 固定 6 个)。`tests/test_web_progress.py` 的资产断言从 `/visuals.js` 的 `const UI` 等价迁移为 `/app.js` 的 `window.UI`。

## 交付切片

- **#87 等价移植**(cf0f79a,复审修复 b79caca):先整体迁移并证明行为等价——旧原生实现与新 React 实现跑同一套流程测试电池,4 项通过一致,9 项以**逐字一致的失败签名**失败(依赖一次性真实历史运行数据或已漂移 fixture,与 UI 实现无关)。
- **#88 垂直故事流**(cfb2a60):方法步骤与核心运行事件渲染为顺读卡片(名称/角色/阶段/状态/耗时),展开显示该步公开输出摘要(角色发言、状态预览、候选检查反馈、时间窗匹配的调用),头部实时消耗条,结束卡衔接结果区。
- **#89 结果区结构化**(fb40ce1):无依赖 Python 语法高亮(`frontend/src/highlight.ts` 字符级扫描器,含跨三引号字符串),接入代码视图与故事流代码片段;五元素表述卡片、需求回链、决策探索与候选比较在迁移组件中行为对齐。
- **#90 起点页**(00685ba):方法解释卡与自动切换提示、不兼容求解器警示与提交门控、预算 chips、doctor 分层摘要。
- **#91 失败诊断**(8220693):错误码→人话诊断 + 建议动作 + 可展开技术详情,决策面板与故事流结束卡共享;失败步骤标记与侧栏辨识。
- **#92 视觉精修与可达性**(772c4f6):全站颜色/圆角统一为设计令牌(7 语义色 + 48 色板按色族与感知相近归并 + 4 wash/overlay + 圆角标度),`:root` 之外零散落硬编码值;计算样式抽查保证与原配色一致;新增键盘可达性验收(焦点环、无陷阱、Enter 核心路径)。
- **#93 收尾**:验收文档补前端构建与浏览器测试步骤、问卷归档、本记录与 parent spec 核对登记。
- **数学排版(#97)**:方法保存的 expression_text 经有界转换器(`frontend/src/math.tsx`,语法外输入回退纯文本)以 KaTeX 排版(∑/≤/下标);KaTeX 本地打包,字族裁剪为 Main/Math/Size1-4,woff2 以 data URI 内联进 style.css,产物保持固定三文件;CSP 增加 `font-src 'self' data:`。结构化 IR 的可点击交互表达式保持不变。

## 验收口径

- 测试缝不变:Playwright `.cjs` 流程测试跑在**构建产物**上(真实 `serve_web` + `tests/helpers/web_guidance_server.py` 确定性 Provider),命令见 [CONTRIBUTING](../../CONTRIBUTING.md)。新增用例:story / code_view / start / failure / keyboard;回归通过:clarification / model / connection / edit(需按 #87 既定 fixture 顺序准备,见 CONTRIBUTING 注)。
- 环境与 fixture 限制:#87 记录的 9 个历史数据型用例(decision/data/process/links/runtime/candidates/connectivity_check/history/model_edit)仍需另行准备真实记录工作区;`test_web_experiments.test_http_batch_real_solver` 在干净 HEAD 上同样失败(预先存在的环境问题)。
- 后端契约零改动;唯一 Python 侧变化是 #87 披露的资产断言等价迁移。Python web API 测试(`test_web_*.py`)预期零改动,实际零改动。

SDK／Worker 版本未变;无新增运行时外部依赖(React/Vite/TypeScript/Playwright 均为前端开发依赖,不进 Python 包)。
