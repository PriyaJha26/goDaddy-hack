import anthropic
import httpx
import pytest

from app.agent.shopper import ShopperAgent
from app.container import Container
from app.domain.errors import ExternalServiceError
from tests.conftest import make_business
from tests.fakes import FakeAnthropic, response, text_block, tool_use_block


@pytest.fixture
async def mcp(container: Container):
    await container.db.migrate()
    await container.businesses.save(make_business())
    return container.mcp


async def test_runs_tool_loop_against_mcp_server(mcp) -> None:
    fake = FakeAnthropic()
    fake.messages.create_responses = [
        response(
            text_block("Let me search."),
            tool_use_block("search_products", {"query": "mango pickle", "location": "Kothrud"}),
            stop_reason="tool_use",
        ),
        response(text_block("Aaji's Pickles sells mango pickle at ₹450 per kg.")),
    ]
    agent = ShopperAgent(fake, "claude-sonnet-5-5", mcp)  # type: ignore[arg-type]

    run = await agent.run("mango pickle in Kothrud?")

    assert run.final_answer == "Aaji's Pickles sells mango pickle at ₹450 per kg."
    assert [s.kind for s in run.steps] == ["assistant", "tool_call", "tool_result", "assistant"]
    assert run.steps[2].data["results"][0]["business_id"] == "aajis-pickles"

    first_call, second_call = fake.messages.calls
    assert {t["name"] for t in first_call["tools"]} >= {"search_products", "send_enquiry"}
    tool_result = second_call["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["is_error"] is False


async def test_tool_errors_are_passed_back_to_the_model(mcp) -> None:
    fake = FakeAnthropic()
    fake.messages.create_responses = [
        response(tool_use_block("get_business", {"business_id": "nope"}), stop_reason="tool_use"),
        response(text_block("I couldn't find that shop.")),
    ]
    run = await ShopperAgent(fake, "m", mcp).run("x")  # type: ignore[arg-type]
    assert run.steps[1].is_error is True
    assert fake.messages.calls[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_stops_at_turn_limit(mcp) -> None:
    fake = FakeAnthropic()
    loop = response(tool_use_block("search_products", {"query": "pickle"}), stop_reason="tool_use")
    fake.messages.create_responses = [loop, loop]
    run = await ShopperAgent(fake, "m", mcp, max_turns=2).run("x")  # type: ignore[arg-type]
    assert "step limit" in run.final_answer


async def test_api_failure_becomes_service_error(mcp) -> None:
    fake = FakeAnthropic()
    fake.messages.error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(ExternalServiceError):
        await ShopperAgent(fake, "m", mcp).run("x")  # type: ignore[arg-type]
