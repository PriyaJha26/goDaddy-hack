"""A demo "AI shopping assistant" that uses the storefront exactly like an external assistant would.

It lists tools from the MCP server and calls them through ``MCPServer.call_tool`` (in-process),
so the demo shows the real agent interface, not a special-cased shortcut.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.domain.errors import ExternalServiceError

logger = logging.getLogger(__name__)

SHOPPER_SYSTEM_PROMPT = """\
You are a helpful AI shopping assistant. You help the user find products from small local
businesses using the tools provided, and you can send enquiries to the business owner.
- Search before answering. If a search finds nothing, say so plainly.
- Check delivery with `check_delivery` before saying a business delivers somewhere.
- Only call `send_enquiry` if the user's message explicitly asks you to send or place it AND
  includes their name and email. Otherwise summarise the options and ask them to confirm.
- When you send an enquiry, set assistant_name to "Open for Agents demo assistant".
- Be concise: prices, who sells it, delivery, and the next step."""

StepKind = Literal["assistant", "tool_call", "tool_result"]


@dataclass(slots=True)
class Step:
    kind: StepKind
    text: str = ""
    tool: str | None = None
    data: Any = None
    is_error: bool = False


@dataclass(slots=True)
class ShopperRun:
    steps: list[Step] = field(default_factory=list)
    final_answer: str = ""


class ShopperAgent:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str, server: MCPServer, max_turns: int = 8) -> None:
        self._client = client
        self._model = model
        self._server = server
        self._max_turns = max_turns

    async def _tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in await self._server.list_tools()
        ]

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, Any, bool]:
        # In-process calls raise ToolError (the HTTP transport turns it into is_error);
        # mirror the transport so the model sees the error and can recover.
        try:
            result = await self._server.call_tool(name, arguments)
        except ToolError as exc:
            return str(exc), str(exc), True
        is_error = bool(getattr(result, "is_error", False))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return json.dumps(structured, ensure_ascii=False), structured, is_error
        text = "\n".join(getattr(c, "text", "") for c in getattr(result, "content", []) or [])
        return text, text, is_error

    async def run(self, user_message: str) -> ShopperRun:
        tools = await self._tool_definitions()
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
        run = ShopperRun()

        for _ in range(self._max_turns):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=1500,
                    system=SHOPPER_SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
            except anthropic.APIError as exc:
                logger.exception("Shopper agent call failed")
                raise ExternalServiceError("The demo assistant is unavailable right now.") from exc

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    run.steps.append(Step("assistant", text=block.text.strip()))
                elif block.type == "tool_use":
                    run.steps.append(Step("tool_call", tool=block.name, data=block.input))
                    text, data, is_error = await self._call_tool(block.name, dict(block.input))
                    run.steps.append(Step("tool_result", tool=block.name, data=data, is_error=is_error))
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error}
                    )

            if response.stop_reason != "tool_use" or not tool_results:
                run.final_answer = next((s.text for s in reversed(run.steps) if s.kind == "assistant"), "")
                return run

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        run.final_answer = "I couldn't finish within the step limit. Please try a more specific request."
        return run
