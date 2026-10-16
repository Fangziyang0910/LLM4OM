# 独立数据加载器示例

Purpose: verify installed public-data loading through the CLI/SDK. This engineering
adapter reverses the actual CSV view's columns. Original input bytes and Solver data
bindings remain unchanged. It is not a research modeling method or data cleaner.

Build and install with `uv build --wheel` and `uv pip install dist/*.whl` from this
directory. Configure `data_loader.plugin_id: llm4om.examples.reversed_columns` and
`data_loader.config.reverse_columns: true`. The platform owns the common `data_view`
limits and validates the resulting exposure. The factory receives admitted public
bytes and schema, without filesystem paths or evaluation materials.

接口见[DataLoader 契约](../../../docs/contracts/plugins.md#dataloader-与-dataview)。安装后仍需验证实际视图。
