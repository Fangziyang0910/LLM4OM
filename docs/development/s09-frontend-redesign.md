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
- **界面减噪(#98,2026-10-13)**:时间轴严格里程碑化——完成的方法步骤(如 OptiMUS 的多轮"识别业务约束")不再成卡,只有澄清、已保存产物事件(数学表述已保存/求解实现已保存/求解完成/候选评估)与正在进行的实时步骤成卡;过程消耗只在顶部消耗条汇总。删除:状态代码片段卡与"已生成的代码片段"说明、展开内的角色发言/调用 pill、`查看原始记录`折叠(`#artifact-content`)、`高级:环境与接口信息`面板、侧栏"开发者工具→实验管理"入口与其页面视图(HTTP 接口保留,见[S09-B](s09-batch-web.md))。界面不再出现任何原始 JSON:失败技术详情改为结构化 错误码/错误信息/连接诊断 字段列表,澄清修订预览改为纯文本;修订编辑器的 JSON textarea 属输入功能,保留。
- **数据集浏览(#101,2026-10-13)**:侧栏新增"浏览数据集"入口,`GET /api/datasets`(列表)与 `GET /api/datasets/<task_id>?offset&limit`(逐条详情)复用 `_tasks()` 冻结快照发现;每条按冻结引用读取公开输入与私有参考(sha256/size 校验),参考答案只在本地工作台结构化呈现(参考目标值/决策映射/探针点等),不进入方法 Context、LLM 提示或公共导出;界面零原始 JSON。验收:`tests/test_web_datasets.py` + `tests/web_datasets_flow.cjs`。

## 验收口径

- 测试缝不变:Playwright `.cjs` 流程测试跑在**构建产物**上(真实 `serve_web` + `tests/helpers/web_guidance_server.py` 确定性 Provider),命令见 [CONTRIBUTING](../../CONTRIBUTING.md)。新增用例:story / code_view / start / failure / keyboard;回归通过:clarification / model / connection / edit(需按 #87 既定 fixture 顺序准备,见 CONTRIBUTING 注)。
- 当前核心验收使用本机确定性Provider与真实HiGHS。批量HTTP测试从临时目录启动，避免误选仓库`runs/`里的旧SDK快照；严格IR编辑按story→model_edit使用`qty_A/qty_B`与容量约束fixture；连通性使用单独的metadata服务器。命令与顺序见CONTRIBUTING。
- decision/data/process/links/runtime/candidates/history是指定历史样本的手工复查脚本，不在通用guidance工作区中混跑。当前用户要求是本机后端与Web能启动、展示并继续开发，这些特定历史重放不作为本轮收尾门槛。
- React迁移保留原应用接口；后续#101增加数据集浏览接口。本轮未改生产后端契约，Python测试只修正批量服务器的工作目录。

## 本机开发收尾（2026-10-14）

- 按用户当前范围交付本机后端与Web，不增加公网多人部署、多平台适配或发布流程。旧规格的原始JSON入口与批量页面要求由#98替换。
- 修复严格IR编辑器的约束字段筛选：字段路径为`structured_ir/constraints/index/...`，恢复系数、关系与右侧值输入。浏览器测试先复现缺少输入框，再经两行修复通过；测试同时更新为当前fixture标识，并等待React完成编辑文档更新。
- 聚焦验收：批量HTTP两例通过；story、model_edit、datasets、code_view、keyboard通过。模型编辑实际HiGHS得到派生目标3，父目标13的bundle字节不变，没有新增模型请求。
- 复用同一开发基线的既有441项回归中440项通过的证据；唯一失败的批量用例因误选SDK0.25快照，已修正工作目录并聚焦通过。此前12条浏览器核心流程与干净wheel／容器HiGHS13证据继续保留，没有再跑整套回归或付费LLM。
- 本机8767后端已重启加载当前代码，页面、静态资源、数据集与运行接口均返回200；5个历史运行与工作区1262个文件的内容校验保持一致。前端构建通过，wheel包含当前三份静态资源。

SDK／Worker 版本未变;无新增运行时外部依赖(React/Vite/TypeScript/Playwright 均为前端开发依赖,不进 Python 包)。
