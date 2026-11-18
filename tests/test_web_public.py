import json
import re

from fastapi.testclient import TestClient

from app.container import Container
from app.domain.models import Product
from tests.conftest import make_business

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_home_lists_shops_and_mcp_url(seeded_client: TestClient) -> None:
    page = seeded_client.get("/")
    assert page.status_code == 200
    assert "Aaji&#39;s Pickles" in page.text
    assert "http://testserver/mcp" in page.text


def test_security_headers_present(client: TestClient) -> None:
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"


def test_shop_page_has_valid_json_ld(seeded_client: TestClient) -> None:
    page = seeded_client.get("/shop/aajis-pickles")
    assert page.status_code == 200
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page.text, re.S).group(1)
    data = json.loads(raw)
    assert data["@type"] == "LocalBusiness"
    assert data["hasOfferCatalog"]["itemListElement"][0]["price"] == "450.00"


def test_json_ld_cannot_break_out_of_script_tag(client: TestClient, container: Container) -> None:
    evil = make_business(
        slug="evil", products=[Product(id="x", name="</script><script>alert(1)</script>", price_minor=1)]
    )
    client.portal.call(container.businesses.save, evil)
    page = client.get("/shop/evil").text
    assert "<script>alert(1)" not in page
    assert "\\u003c/script>" in page


def test_unknown_shop_is_404(client: TestClient) -> None:
    assert client.get("/shop/missing").status_code == 404


def test_enquiry_form_stores_and_notifies(seeded_client: TestClient, container: Container) -> None:
    response = seeded_client.post(
        "/shop/aajis-pickles/enquire",
        data={
            "customer_name": "Priya",
            "customer_email": "priya@example.com",
            "message": "Hi",
            "product_id": "mango-pickle",
            "quantity": "2 kg",
        },
    )
    assert response.status_code == 200 and "Enquiry sent" in response.text
    [enquiry] = seeded_client.portal.call(container.enquiries.list_recent)
    assert enquiry.items[0].quantity == "2 kg"
    assert container.mailer.sent[-1].to == "hello@example.com"


def test_enquiry_form_validation_and_honeypot(seeded_client: TestClient, container: Container) -> None:
    bad = seeded_client.post(
        "/shop/aajis-pickles/enquire", data={"customer_name": "P", "customer_email": "nope", "message": "Hi"}
    )
    assert bad.status_code == 422
    bot = seeded_client.post(
        "/shop/aajis-pickles/enquire",
        data={"customer_name": "Bot", "customer_email": "b@example.com", "message": "spam", "website": "x"},
    )
    assert bot.status_code == 200
    assert seeded_client.portal.call(container.enquiries.list_recent) == []


def test_contact_form_sends_to_mailbox(client: TestClient, container: Container) -> None:
    response = client.post("/contact", data={"name": "Asha", "email": "asha@example.com", "message": "Hello"})
    assert response.status_code == 200
    assert container.mailer.sent[-1].reply_to == "asha@example.com"


def test_contact_form_is_rate_limited(client: TestClient) -> None:
    data = {"name": "A", "email": "a@example.com", "message": "x"}
    statuses = [client.post("/contact", data=data).status_code for _ in range(25)]
    assert statuses[0] == 200 and statuses[-1] == 429


def test_llms_txt_points_to_mcp(seeded_client: TestClient) -> None:
    text = seeded_client.get("/llms.txt").text
    assert "http://testserver/mcp" in text
    assert "[Aaji's Pickles](http://testserver/shop/aajis-pickles)" in text


def test_mcp_endpoint_over_http(seeded_client: TestClient) -> None:
    init = seeded_client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    assert init.status_code == 200
    call = seeded_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "mcp-protocol-version": "2025-06-18"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_products", "arguments": {"query": "achar"}},
        },
    )
    assert call.status_code == 200
    assert "mango-pickle" in call.text


def test_mcp_tool_errors_reach_client_as_is_error(seeded_client: TestClient) -> None:
    call = seeded_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "mcp-protocol-version": "2025-06-18"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_business", "arguments": {"business_id": "nope"}},
        },
    )
    result = call.json()["result"]
    assert result["isError"] is True
    assert "No business found" in result["content"][0]["text"]


def test_mcp_rejects_foreign_host_header(seeded_client: TestClient) -> None:
    response = seeded_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "host": "evil.example"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code in (400, 403, 421)


def test_try_api_without_key_explains(client: TestClient) -> None:
    response = client.post("/api/try", json={"message": "find pickle"})
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["error"]
