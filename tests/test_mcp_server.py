import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from app.container import Container
from app.domain.models import EnquirySource
from tests.conftest import make_business


@pytest.fixture
async def mcp(container: Container):
    await container.db.migrate()
    await container.businesses.save(make_business())
    return container.mcp


async def call(mcp, name: str, **arguments):
    result = await mcp.call_tool(name, arguments)
    return result


async def test_lists_four_tools_with_correct_safety_annotations(mcp) -> None:
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == {"search_products", "get_business", "check_delivery", "send_enquiry"}
    for read_only in ("search_products", "get_business", "check_delivery"):
        assert tools[read_only].annotations.read_only_hint is True
    assert tools["send_enquiry"].annotations.read_only_hint is False
    assert "confirmed" in tools["send_enquiry"].description


async def test_search_products(mcp) -> None:
    result = await call(mcp, "search_products", query="aam ka achar", location="Kothrud")
    assert not result.is_error
    [first, *_] = result.structured_content["results"]
    assert first["product_id"] == "mango-pickle"
    assert first["price"] == "₹450"
    assert first["page_url"] == "http://testserver/shop/aajis-pickles"


async def test_search_with_no_results_explains_why(mcp) -> None:
    result = await call(mcp, "search_products", query="mango pickle", location="Chennai")
    assert result.structured_content["results"] == []
    assert "No matching" in result.structured_content["note"]


async def test_get_business_and_check_delivery(mcp) -> None:
    business = (await call(mcp, "get_business", business_id="aajis-pickles")).structured_content
    assert [p["product_id"] for p in business["products"]] == ["mango-pickle", "lemon-pickle"]

    yes = (await call(mcp, "check_delivery", business_id="aajis-pickles", location="411038")).structured_content
    no = (await call(mcp, "check_delivery", business_id="aajis-pickles", location="Delhi")).structured_content
    assert yes["delivers"] is True and no["delivers"] is False


async def test_send_enquiry_records_agent_source_and_emails_owner(mcp, container: Container) -> None:
    result = await call(
        mcp,
        "send_enquiry",
        business_id="aajis-pickles",
        customer_name="Priya",
        customer_email="priya@example.com",
        message="2 kg please",
        items=[{"product_id": "mango-pickle", "quantity": "2 kg"}],
        assistant_name="Claude",
    )
    assert not result.is_error, result.content
    assert result.structured_content["status"] == "sent_to_owner"

    [enquiry] = await container.enquiries.list_recent()
    assert enquiry.source is EnquirySource.AI_AGENT
    assert enquiry.agent_name == "Claude"
    assert container.mailer.sent  # owner notified


@pytest.mark.parametrize(
    ("arguments", "expected_text"),
    [
        (
            {"business_id": "nope", "customer_name": "P", "customer_email": "p@example.com", "message": "m"},
            "No business",
        ),
        (
            {"business_id": "aajis-pickles", "customer_name": "P", "customer_email": "bad", "message": "m"},
            "customer_email",
        ),
    ],
)
async def test_send_enquiry_errors_are_readable_tool_errors(mcp, arguments, expected_text) -> None:
    # Expected failures surface as ToolError (shown to the model), never as a crash.
    with pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("send_enquiry", arguments)
    assert not isinstance(excinfo.value, UnexpectedToolError)
    assert expected_text in str(excinfo.value)
