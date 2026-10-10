# 独立 Executor 示例

用途：演示已安装entry point接入两个真实进程profile，记录调用并复用已有执行监督。状态：工程fixture，不是自动建模方法或额外隔离环境。

在源码环境安装：

```bash
uv pip install --no-deps ./examples/plugins/fixture_executor
llm4om plugins list
```

容器配置选`llm4om.fixtures.container_executor`，保留标准network／cpu_limit／memory_limit_mb／wall_time_s，增加`receipt_path`。本机配置选`llm4om.fixtures.local_executor`，config只需`receipt_path`。路径指向本机临时记录文件，验证后删除。

命令收据证明预检与执行经过该插件；真实结果仍由Worker／Solver产生。容器示例的安装包只在可信宿主使用，不要求放入生成代码Worker。模型方法不能取得这两个低层进程接口。
