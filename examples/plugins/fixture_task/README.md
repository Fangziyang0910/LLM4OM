# 独立 Task／Evaluator 示例

用途：演示可信benchmark插件通过共同Registry接入。适用于SDK0.19.0；字段见 [契约](../../../docs/plugin-contracts.md#24-s03-c2-installed-task-and-evaluator-sdk-0190)。这是工程fixture，数值比较不证明模型符合所有业务规则。

在仓库根目录构建并安装：

```bash
uv build --offline --wheel examples/plugins/fixture_task --out-dir /tmp/llm4om-task-wheel
uv pip install --no-deps /tmp/llm4om-task-wheel/llm4om_fixture_task-0.1.0-py3-none-any.whl
llm4om plugins list
```

导入配置位于原始问题和参考文件目录，例如：

```json
{
  "schema_version": "0.1.0",
  "adapter_id": "llm4om.examples.micro_task",
  "adapter_config": {"dataset_id": "my-micro-task"},
  "evaluation": {"evaluator_plugin_id": "llm4om.examples.micro_evaluator", "config": {"abs_tol": 0.000001}},
  "problem_path": "problem.json",
  "problem_sha256": "REPLACE_WITH_ACTUAL_SHA256",
  "reference_path": "reference.json",
  "reference_sha256": "REPLACE_WITH_ACTUAL_SHA256"
}
```

problem.json采用现有公开ProblemSpec；CSV文件按data_refs放置，原始hash保留。reference.json是私有数值材料，包含有限数值value，可附私有研究注释。将占位hash替换为实际文件SHA-256再执行。

```bash
llm4om doctor --task-config /path/to/import.json
llm4om import --config /path/to/import.json --output /path/to/snapshot
```

Task接收source配置及指定staging路径，发布manifest.json和public／private目录。FrozenTaskAdapter复用冻结案例读取；evaluate_outcome复用原问题与实际RunBundle核验，再调用Evaluator自身的参考比较。config_schema分别校验Adapter和Evaluator的参数；protocol_ids声明匹配范围。

插件是可信宿主代码，describe／create不得发送付费请求。方法及Worker仅获得public问题和数据；隐藏引用留在导入／评分端。导入后修改参数或包需要显式创建新snapshot，不能改写原manifest后沿用旧评测身份。
