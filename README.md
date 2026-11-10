# Agent 精灵

Agent 精灵是一个本地运行、人工监督的产品构想到交付物工作流原型。当前 MVP 使用 FastAPI、SQLite 和 React + TypeScript。

## 开发环境

- Python 3.11+（推荐使用 `uv` 管理；当前开发环境使用 Python 3.12）
- Node.js 20+ 与 npm

```bash
uv sync --extra dev
cd frontend && npm install
```

后端默认只绑定回环地址：

```bash
uv run uvicorn agent_elf.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend && npm run dev
```

## 模型与隐私

未配置外部服务时，应用使用明确标记的本地演示 Provider，便于离线测试；演示输出不是模型生成或市场事实。配置 OpenAI-compatible 服务时，通过进程环境变量提供 `AGENT_ELF_API_BASE`、`AGENT_ELF_API_KEY` 和 `AGENT_ELF_MODEL`。密钥不写入数据库、浏览器、日志或产物。启用该 Provider 前应告知用户：输入与上下文会发送给配置的服务商。

每次 Run 必须提供正数 token 预算。应用在发起调用前预留保守输入估算并限制响应 token；实际 Provider 用量记账后若达到预算则暂停，不会自动继续。各 Provider 的分词/计费口径可能不同，界面和报告需区分估算与服务商回报值。

## P0 安全边界

- 默认服务仅监听 `127.0.0.1`，不可直接暴露到公网或共享网络。
- 不执行生成的应用代码，不自动部署、不应用安全配置，也不运行脚本型 Skill。
- HTML 原型先经过 DOMPurify 清洗，再在受限 iframe 与严格 CSP 中预览；这不等于验证生成应用安全。
- 运维/安全内容是待人工复核的草案，不代表安全认证或生产就绪。
- 市场调研未接入来源检索时仅为待核实假设。P0 不抓取 URL，不接受 PDF、Office 或 OCR 文件。
- 使用真实模型时，模型服务商会接收发送给它的输入。部署前必须设置真实 token 预算并确认数据处理方式。

## 验证

```bash
uv run ruff check backend tests
uv run pytest
cd frontend && npm test && npm run build
```
