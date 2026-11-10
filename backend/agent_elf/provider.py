from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx


class ProviderError(Exception):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderUsageError(ProviderError):
    pass


@dataclass(frozen=True)
class ChatResult:
    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str


class ModelProvider(Protocol):
    name: str

    async def complete(self, *, system: str, prompt: str, max_output_tokens: int) -> ChatResult: ...


class DemoProvider:
    name = "本地演示 Provider"
    model = "local-demo"

    async def complete(self, *, system: str, prompt: str, max_output_tokens: int) -> ChatResult:
        started = time.monotonic()
        content = self._respond(prompt)
        output_tokens = max(1, (len(content) + 3) // 4)
        if output_tokens > max_output_tokens:
            content = content[: max_output_tokens * 4]
            output_tokens = max_output_tokens
        return ChatResult(
            content=content,
            input_tokens=max(1, (len(system) + len(prompt) + 3) // 4),
            output_tokens=output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            model=self.model,
        )

    @staticmethod
    def _respond(prompt: str) -> str:
        if "TASK=PLAN" in prompt:
            steps = [
                (stage, title, output)
                for stage, title, output in (
                    ("S1", "整理市场假设", "标明未经来源核实的市场假设"),
                    ("S2", "分析用户需求", "用户场景、痛点与优先级"),
                    ("S3", "制定产品范围", "目标、非目标与 MVP 决策"),
                    ("S4", "制作产品原型", "自包含 HTML 原型"),
                    ("S5", "整理功能需求", "可编辑的验收需求清单"),
                    ("S6", "生成代码草案", "不执行的源代码产物"),
                    ("S7", "静态检查代码", "未执行的静态检查报告"),
                    ("S8", "编写运维安全方案", "待人工复核的方案草案"),
                )
            ]
            return json.dumps(
                {
                    "final_goal": "生成经过人工确认、可审阅的产品方案、原型、需求清单与代码草案。",
                    "assumptions": [
                        "本地演示 Provider 输出为模板示例，不是实际市场调研或模型结论。"
                    ],
                    "steps": [
                        {
                            "id": f"{stage}-01",
                            "stage": stage,
                            "title": title,
                            "mode": "independent_llm_call",
                            "inputs": [],
                            "expected_output": output,
                            "depends_on": [f"S{int(stage[1:]) - 1}-01"] if stage != "S1" else [],
                            "acceptance": f"产出可查看的{output}。",
                        }
                        for stage, title, output in steps
                    ],
                    "done_definition": "所有固定阶段的产物已保存，S5 与 S8 人工门已由用户处理。",
                },
                ensure_ascii=False,
            )
        if "TASK=REVIEW" in prompt:
            return json.dumps(
                {
                    "verdict": "pass",
                    "findings": [],
                    "summary": "演示评审：未发现需自动修订的问题。",
                },
                ensure_ascii=False,
            )
        if "TASK=REFINE" in prompt:
            marker = "DRAFT:\n"
            return prompt.split(marker, 1)[1] if marker in prompt else "演示修订稿。"
        if "TASK=S4" in prompt:
            return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>产品原型</title><style>
body{font:16px system-ui,sans-serif;background:#f4f6f1;color:#263126;margin:0;padding:40px}
main{max-width:680px;margin:10vh auto;background:white;border-radius:20px;padding:32px;
box-shadow:0 12px 40px #26312612}
button{border:0;border-radius:10px;padding:12px 18px;background:#627b54;color:white}
</style></head>
<body><main><p>产品原型 · 本地演示</p><h1>把想法变成可验证的产品</h1>
<p>这是隔离预览示例，不代表已实现或安全审查通过。</p>
<button type="button">了解更多</button></main></body></html>"""
        if "TASK=S5" in prompt:
            return json.dumps(
                [
                    {
                        "id": "REQ-001",
                        "module": "核心体验",
                        "description": "用户可以查看主要内容并执行核心操作。",
                        "priority": "P0",
                        "acceptance": "给定用户打开页面，主内容与主要操作清晰可见。",
                        "prototype_element": "主内容卡片与主要操作按钮",
                        "related_steps": ["S6-01"],
                    },
                    {
                        "id": "REQ-002",
                        "module": "反馈状态",
                        "description": "界面为用户操作提供成功或失败反馈。",
                        "priority": "P1",
                        "acceptance": "给定操作完成或失败，用户能看到对应状态说明。",
                        "prototype_element": "操作反馈区域",
                        "related_steps": ["S6-01"],
                    },
                ],
                ensure_ascii=False,
            )
        if "TASK=S6" in prompt:
            return """# 代码草案（未执行）

```python
def main() -> None:
    print("Generated application placeholder")


if __name__ == "__main__":
    main()
```

此文件仅为文本产物。Agent 精灵 P0 不会执行它，也不会声称它可运行。"""
        if "TASK=S7" in prompt:
            return "静态规则检查已完成；代码未执行，行为与运行时安全性未验证。"
        if "TASK=S8" in prompt:
            return (
                "运维与安全方案草案：按需设计认证授权、输入校验、密钥管理、审计、备份与回滚。"
                "本内容未应用、未部署，必须由具备资质的人员复核。"
            )
        stage_name = prompt.split("TASK=", 1)[1].splitlines()[0] if "TASK=" in prompt else "阶段"
        safety = (
            "演示说明：本地模板输出，没有访问实时市场来源。市场相关内容仅是待验证假设。"
            if stage_name == "S1"
            else "本地演示 Provider 只返回模板，不代表真实用户研究结论。"
        )
        return f"{stage_name} 产物草稿\n\n{prompt[-400:]}\n\n{safety}"


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = "OpenAI-compatible Provider"
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ProviderConfigurationError("非本机 OpenAI-compatible 服务必须使用 HTTPS。")
        if not parsed.scheme or not parsed.netloc:
            raise ProviderConfigurationError("AGENT_ELF_API_BASE 必须是有效的 HTTP(S) URL。")

    @classmethod
    def from_env(cls) -> OpenAICompatibleProvider | None:
        values = (
            os.getenv("AGENT_ELF_API_BASE"),
            os.getenv("AGENT_ELF_API_KEY"),
            os.getenv("AGENT_ELF_MODEL"),
        )
        if not any(values):
            return None
        if not all(values):
            raise ProviderConfigurationError(
                "外部模型配置不完整：需同时设置 API_BASE、API_KEY 与 MODEL。"
            )
        base_url, api_key, model = values
        return cls(base_url, api_key, model)

    async def complete(self, *, system: str, prompt: str, max_output_tokens: int) -> ChatResult:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": max_output_tokens,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("模型调用超时；凭据未记录。") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"模型服务返回 HTTP {exc.response.status_code}；响应正文与凭据未记录。"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("无法连接模型服务；请检查服务地址与网络。") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("模型服务响应格式无效。") from exc

        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            if not isinstance(content, str):
                raise TypeError("completion content must be text")
            if not isinstance(usage, dict) or not {
                "prompt_tokens",
                "completion_tokens",
            }.issubset(usage):
                raise ProviderUsageError("模型服务未返回完整 token 用量，无法继续保障 Run 预算。")
            input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage["completion_tokens"])
            if input_tokens < 0 or output_tokens < 0 or input_tokens + output_tokens == 0:
                raise ProviderUsageError("模型服务返回了无效 token 用量。")
            return ChatResult(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
                model=self.model,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("模型服务响应缺少必需字段。") from exc


def build_provider() -> ModelProvider:
    external = OpenAICompatibleProvider.from_env()
    return external if external is not None else DemoProvider()
