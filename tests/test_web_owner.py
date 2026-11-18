from fastapi.testclient import TestClient

from app.container import Container
from tests.conftest import PNG_BYTES, login


def test_dashboard_requires_login(client: TestClient) -> None:
    response = client.get("/owner", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/owner/login"


def test_wrong_password_rejected(client: TestClient) -> None:
    assert client.post("/owner/login", data={"password": "nope"}).status_code == 401


def test_session_cookie_is_http_only(client: TestClient) -> None:
    response = client.post("/owner/login", data={"password": "correct horse battery staple"}, follow_redirects=False)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_post_without_csrf_token_is_forbidden(client: TestClient) -> None:
    login(client)
    response = client.post(
        "/owner/onboard", data={"csrf_token": "wrong"}, files={"photo": ("menu.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 403


def test_onboarding_rejects_non_images(client: TestClient) -> None:
    csrf = login(client)
    response = client.post(
        "/owner/onboard", data={"csrf_token": csrf}, files={"photo": ("menu.png", b"<?php evil", "image/png")}
    )
    assert response.status_code == 422


def test_onboarding_rejects_oversized_upload(client: TestClient, container: Container) -> None:
    csrf = login(client)
    big = PNG_BYTES + b"\x00" * container.settings.max_upload_bytes
    response = client.post("/owner/onboard", data={"csrf_token": csrf}, files={"photo": ("menu.png", big, "image/png")})
    assert response.status_code == 422


def test_full_onboarding_flow_publishes_shop(client: TestClient, container: Container) -> None:
    csrf = login(client)
    review = client.post(
        "/owner/onboard", data={"csrf_token": csrf}, files={"photo": ("menu.png", PNG_BYTES, "image/png")}
    )
    assert review.status_code == 200
    assert "Mango pickle" in review.text and "कैरीचे लोणचे" in review.text

    form = {
        "csrf_token": csrf,
        "business_name": "Aaji's Pickles",
        "city": "Pune",
        "category": "pickles",
        "description": "Homemade",
        "service_areas": "Kothrud, 411038",
        "languages": "Marathi, English",
        "product_name": ["Mango pickle", ""],
        "product_local": ["कैरीचे लोणचे", ""],
        "product_description": ["Raw mango", ""],
        "product_price": ["450", ""],
        "product_unit": ["per kg", ""],
        "product_tags": ["Mango Pickle, achar", ""],
    }
    published = client.post("/owner/onboard/publish", data=form, follow_redirects=False)
    assert published.status_code == 303
    assert published.headers["location"] == "/shop/aaji-s-pickles?published=true"

    business = client.portal.call(container.catalog.get, "aaji-s-pickles")
    assert business.service_areas == ["Kothrud", "411038"]
    assert [(p.name, p.price_minor, p.tags) for p in business.products] == [
        ("Mango pickle", 45000, ["mango pickle", "achar"])
    ]
    assert "is now open to AI assistants" in client.get(published.headers["location"]).text


def test_publish_rejects_bad_price(client: TestClient) -> None:
    csrf = login(client)
    form = {
        "csrf_token": csrf,
        "business_name": "X",
        "city": "Pune",
        "product_name": "Pickle",
        "product_local": "",
        "product_description": "",
        "product_price": "four hundred",
        "product_unit": "kg",
        "product_tags": "",
    }
    response = client.post("/owner/onboard/publish", data=form)
    assert response.status_code == 422
    assert "must be a number" in response.text


def test_owner_drafts_and_sends_reply(seeded_client: TestClient, container: Container) -> None:
    seeded_client.post(
        "/shop/aajis-pickles/enquire",
        data={
            "customer_name": "Priya",
            "customer_email": "priya@example.com",
            "message": "2 kg?",
            "product_id": "mango-pickle",
            "quantity": "2 kg",
            "delivery_location": "Kothrud",
        },
    )
    [enquiry] = seeded_client.portal.call(container.enquiries.list_recent)
    csrf = login(seeded_client)

    drafted = seeded_client.post(f"/owner/enquiries/{enquiry.id}/draft", data={"csrf_token": csrf})
    assert "Approve and send email" in drafted.text
    assert "Mango pickle: ₹450 per kg" in drafted.text

    sent = seeded_client.post(
        f"/owner/enquiries/{enquiry.id}/send",
        data={"csrf_token": csrf, "reply_text": "Yes! ₹900 for 2 kg."},
        follow_redirects=True,
    )
    assert sent.status_code == 200 and "Replied" in sent.text
    assert container.mailer.sent[-1].to == "priya@example.com"
