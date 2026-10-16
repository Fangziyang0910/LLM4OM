# Web 契约

页面职责见 [Web 开发说明](../development/web.md)。HTTP 接口复用共同应用用例，字段不包含 LLM 密钥或隐藏参考评测材料。

## 启动配置与凭据

`GET /api/bootstrap` 返回方法模板、LLM 预设、有效配置和默认密钥状态。`llm_presets` 项含 id、label、provider_plugin_id 和 base_url。默认凭据仅显示 configured 和 masked preview。

`llm_profiles` 保存预设到公开 LLM 选择的映射，`selected_llm_preset` 表示最近选择。`llm_credentials` 以端点身份映射密钥掩码。身份为 Provider ID 与去除尾斜杠的 Base URL。

预设地址只读，仅 OpenAI 兼容可改 URL。doctor/jobs 可传公开 `llm_preset`，后端核对它与实际 Provider/URL 一致。CLI/SDK 不受 Web 目录限制。

`POST /api/llm-settings` 接收 config 和 llm_preset，以及可选私有 `X-LLM4OM-Provider-Key` header。本地校验后原子保存，不请求网络；未提供 header 时保留密钥。

保存文件为 `<workspace>/.private/llm-settings.local.json`，权限 `600`，Git 忽略。密钥查询只返回状态/掩码。超过 12 字符时显示前后各 4 字符，短密钥全部遮挡。

公开 JSON 拒绝 credential 字段。后端按显式临时密钥、已保存端点密钥、匹配的 .env 默认服务解析。密钥只注入拥有的应用进程，不修改全局环境。与同一凭据引用关联的角色使用对应私有覆盖。

恢复和编辑按运行保存的端点查找密钥。默认 .env 密钥不能转发到不同端点。临时覆盖不改写供应商设置和父记录。

## 模型目录

`POST /api/llm-models` 接收公开 LLM 选择和可选预设，使用相同私有 header。查询无需先填写模型名，不创建运行或发起生成。

结果为 `models=[{id,name}]` 和 `has_more`。选择只写入 API ID。读取范围、百炼结构和认证见[LLM 契约](llm.md#目录与诊断)。页面在可见编辑器中自动获取，结果页直接打开不触发目录 POST。

## 任务与版本

`/api/jobs` 负责单问题提交和列表。`GET /api/jobs/JOB_ID` 返回状态、已校验公开产物和版本信息。无最终 bundle 时只投影有界、哈希校验且运行 ID 匹配的检查点内容，不返回检查点本体。

最终求解按 RunBundle.solve_result_ref 和 SolveResult.solution_ref 读取。前端不能把首个中间结果当成最终选择。

versions 项记录 run_id、status、parent_run_id、operation、assisted 和 saved_at。saved_at 为 bundle 的文件修改时间，不冒充创建时间。latest_run_id 与 historical 描述当前版本关系。

详情、edit-template 和 export 可指定 run_id；省略读取当前版本。指定版本必须位于该工作项的运行目录，拒绝跨工作项、目录穿越和符号链接。

edit 可指定 parent_run_id。取消、恢复和澄清作用于当前任务运行，浏览历史不改变后台任务。旧布局只读，严格恢复与编辑仍需通过身份校验。

## 数据预览与题库

`POST /api/data-preview` 接收格式与 base64 字节，复用同源/令牌与单文件 8 MiB 检查。只返回有界表格、大小和源哈希，不保存文件或运行。

已保存数据预览读取经过公开引用检查的数据视图。CSV 最多显示 20 行、16 列；JSON 最多显示 20 个顶层字段；每格最多 256 字符。页面截断与实际模型视图完整性分别呈现。

`GET /api/datasets` 返回随包目录，含 task_id、dataset_id、title、description、source_version、source_url、license 和 N_cases。工作区评测快照不混入题库。

`GET /api/datasets/TASK_ID?offset&limit` 验证题面包，返回 dataset、total 和 cases。每项含案例身份、公开问题、input 和 copy_text。默认 offset=0、limit=100，最多 200 条。

复制与带入使用相同公开输入。选择样例不提交任务，也不改变方法/模型/求解器。答案、参考解和代码不在题面包或响应中。

## 实验与导出

HTTP 保留 `/api/tasks` 和 `/api/experiments` 的公开任务、提交、状态、取消、恢复和报告导出接口。日常页面围绕单问题，批量实验使用 CLI。

实验控制绑定当前 invocation。新执行在排他锁内接受新身份，清理上一轮取消请求。完成样本复用与未完成继续分别记录。

任务通过独立 CLI 进程调用共同 Python 用例。取消先协作 SIGINT，最多等待 10 秒再清理。未保存终态时，job 保留真实失败，不能改标完成。

公开 ZIP 只收集已保存并核对的公开引用和实际 report_refs。不导出私有 archive、环境文件、完整评测 manifest 或任意服务器路径。上传、请求和导出大小上限见[Web 开发说明](../development/web.md#数据与权限)。
