# fixture_store

独立安装的 ArtifactStore 集成 fixture。`create(config)` 返回 `run_store/0.1.0` opener：先向 `receipt_path` 追加一条打开记录，再按标准文件系统契约打开 RunStore。用于验证 `llm4om.plugins` 注册、admission 身份保存与 `RunConfig.store` 独立替换，不引入新的持久化语义。

```bash
uv build examples/plugins/fixture_store --wheel --out-dir dist/fixtures
uv pip install --no-deps --target <target> dist/fixtures/llm4om_fixture_store-0.1.0-py3-none-any.whl
PYTHONPATH=src:<target> python -m llm4om plugins list
```
