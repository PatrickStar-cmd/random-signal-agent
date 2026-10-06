# 模型 API 配置向导（主分支新增）

此功能已加入仓库主分支，尚未包含在 v0.2.6 Release 部署包中。使用最新仓库代码启动即可体验。

在应用顶部展开“模型 API 配置”：

1. 选择 OpenAI、DeepSeek 或自定义兼容接口。预设服务自动填写 Base URL；自定义服务填写其提供的 API 根地址，例如 `https://服务地址/v1`，不要填写完整 `/chat/completions` 地址。
2. 输入该服务的 API Key，点击“读取模型列表”。选择可用模型；没有模型列表接口时可手动填写准确模型 ID。列表可能包含非对话模型，读取成功不代表支持文本问答。
3. 点击“测试并应用”。测试发送简短问候（可能产生少量 API 费用）；收到非空文本后才应用配置，立即生效，无需重启。连接失败保留当前已应用配置。
4. 未勾选“记住配置”时，仅在服务内存中保留，服务重启后失效。勾选后，配置和 Key 以明文保存在 `data/model-settings.sqlite3`（或 `RS_AGENT_DATA_DIR` 中），重启后仍可使用。浏览器仅保存已有会话 ID，不保存 Key。

配置按当前浏览器会话隔离。刷新页面沿用配置；换浏览器或清除站点数据会产生新的会话，不自动复制 Key。恢复/导入实验不会携带模型配置。Key 不加入聊天记录、任务载荷、快照或导出 ZIP；只显示“已有 Key”，不会返回已保存 Key 文本。修改 Base URL 后需输入新地址对应的 Key，旧 Key 不会被自动发送到其他地址。

“切回本地工具链”停用当前会话的外部模型，保留已保存的 Key。重新“测试并应用”可启用。“移除当前会话配置”删除此会话配置并恢复服务环境变量默认值；若环境变量里已配置外部模型，移除后仍会使用该默认模型。记住的停用配置在重启后仍停用；未保存的会话停用状态在重启后恢复默认值。

## 高级兼容设置

- 超时：5–120 秒，默认 45 秒。
- 输出限制参数：通用接口使用 `max_tokens`；OpenAI 预设使用 `max_completion_tokens`。不同模型支持不同参数。
- 发送温度：部分推理模型不支持自定义温度，OpenAI 预设默认不发送。自定义接口可选择“否”。
- “只应用配置，不测试”适用于不支持简单文本测试或暂时不可连通的服务；保存成功只说明字段有效，不保证真实请求成功。

本功能适配 Chat Completions 文本接口，不把模型列表中的所有模型都视为兼容。文本测试不验证工具调用；信号采集、滤波、分析和诊断继续使用本地工具链，外部模型用于问答和对话。

Key 属于部署服务保存的数据，勾选记住时请在自己信任的服务上使用。服务配置仍沿用现有部署权限：会话 ID 用于隔离数据，不替代服务器用户认证；公网部署按 DEPLOY.md 配置访问控制。HTTP API 仅允许 localhost；远程地址使用 HTTPS。接口重定向不会携带 Key 自动跟随。

## 配置与自动化接口

`config/model-providers.json` 包含预设 id、label、base_url、token_parameter、send_temperature、key_url。default_timeout=45 为默认秒数；test_tokens=128 为测试输出 token 上限；response_bytes=2097152 为非流式响应上限；max_models=500 为列表显示上限。可用模型来自服务的 `GET /models`，没有硬编码默认模型。

- `GET /api/model/settings?session_id=...` 返回脱敏配置与服务预设。
- `POST /api/model/{models,test,save,disable,clear}` 接收 JSON `{session_id, configuration}`。configuration 支持 provider、base_url、model、api_key、timeout、enabled、remember、token_parameter、send_temperature。models 可省略 model；disable/clear 无需 configuration。
- 保存后 Key 可留空沿用同地址会话 Key；不从环境变量中提取 Key 给配置表单。测试和模型列表不保存草稿。
- 配置请求使用独立端点，JSON 且同源；不进入持久化任务队列。更改配置与该会话正在进行的任务串行，其他会话可并行。

`python scripts/test_model_settings.py` 运行本地 HTTP 模拟服务验收，不调用付费 API，覆盖 10 项测试。结果覆盖写入 `logs/model-settings/latest.log`；浏览器记录为 `logs/model-settings/browser.log`。发布干净环境验证也会运行本测试。

协议参考：[OpenAI 模型列表](https://developers.openai.com/api/reference/resources/models/methods/list)、[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。
