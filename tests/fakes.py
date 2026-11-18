"""Test doubles for the Anthropic client. Only the surface our code uses is implemented."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name: str, tool_input: dict[str, Any], block_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def response(*blocks: SimpleNamespace, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


@dataclass
class FakeMessages:
    create_responses: list[Any] = field(default_factory=list)
    parse_result: Any = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        # Snapshot messages: the caller keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if self.error:
            raise self.error
        return self.create_responses.pop(0)

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.parse_result)


@dataclass
class FakeAnthropic:
    messages: FakeMessages = field(default_factory=FakeMessages)
