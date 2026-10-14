# S09-A：本地优化建模工作台

用途：记录SDK／Worker0.23.0的本地Web功能与实际运行。工作项为 [#49](https://github.com/Fangziyang0910/LLM4OM/issues/49)。规范来源为 [详细设计](../design/experiments-and-interfaces.md#dd-08-cli-与-web-共用应用接口)及 [需求规格](../requirements/v1.0.md)。功能代码已实现，浏览器视觉与剩余交互验收继续完善，包未发布。

## 启动与使用

在项目根目录执行：

```bash
uv sync --locked --extra solve --extra gurobi
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om serve --workspace runs/web --port 8767
```

打开输出的本地URL。远程启动：

```bash
uv run --locked llm4om serve --host 0.0.0.0 --workspace runs/web --port 8767
```

远程浏览器访问 `http://服务器IP:8767`。当前工作台为单用户工具，远程监听用于可信网络访问。

输入自然语言，添加公开CSV／JSON，选择方法、Provider、模型、建模后端和求解器。可导入ProblemSpec或编辑完整RunConfig；CSV未声明schema时保持原始字符串和允许空值，不推断业务唯一键。导入规格的原始hash必须匹配上传bytes。OptiMUS需要明确的params／labels JSON；CoE参数和预算可在完整配置中编辑。

首版凭据由服务端环境或当前目录.env读取。2026-10-14补充页面协议／地址／模型名／Key 配置，Key 独立传给服务端并只保留会话内存，详见[当前配置与恢复行为](s09-llm-settings.md)。检查环境与兼容性复用prepare_run，实际提交复用run_problem。当前页可看阶段、五元素／原生表述、代码、候选、原始绑定、决策、终止状态、Token和未知费用；事件轮询来自核心记录。取消、恢复、澄清回答和明确派生重跑复用已有应用接口。重启服务仍可查看已保存工作。编辑问题／代码的完整派生工作流与实验比较由后续S09-B继续补齐。

默认绑定127.0.0.1；远程访问使用 `--host 0.0.0.0`，通过服务器 IPv4 地址和端口打开页面。校验Host／同源Origin和进程内请求token。公开下载仅包含run_public引用及其hash／size校验后的内容，不遍历Provider私有archive、环境文件或任意宿主路径。上传单文件8 MiB、JSON请求24 MiB、公开导出64 MiB；本地并发2、最多8个排队或活动工作。

## 实际运行证据

网页HTTP接口提交原始生产问题和CSV，调用指定deepseek-v4-pro-0813并由真实容器HiGHS求解。运行6c076a446e0a41e9bb96147906f02f38得到x_A3／x_B2／目标13／optimal，原始CSV的独立整数域／容量／利润检查通过。实际一次模型请求、一次求解、7299 Tokens；提供方费用未知，保留null。公开ZIP37项，完成后通过网页接口恢复不增加请求或预算。

先前一次试运行3e679450a3eb4daa974181d78454dbd8遇到连接错误与超时，两次真实attempt的结果未知，保留26222 Tokens预留和未知费用。随后显式新运行使用直接网络、0重试和90s请求时限成功；没有把失败隐藏或复用为成功。

本次以功能代码和实际运行优先；39模块类型检查与JS语法检查通过，没有新增整套回归。0.30.0已通过本机Chrome实际观察和用户流程检查，见 [用户界面记录](s09-user-experience.md)。取消／异常来源／全部交互和独立Standards／Spec审阅尚需继续验收，不能据此称完整1.0完成。
