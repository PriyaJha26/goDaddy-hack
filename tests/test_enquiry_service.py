import pytest

from app.domain.errors import NotFoundError, ValidationFailed
from app.domain.models import ContactMessage, EnquiryItem, EnquirySource, EnquiryStatus, NewEnquiry
from app.repositories.sqlite import SqliteBusinessRepository, SqliteEnquiryRepository
from app.services.enquiries import EnquiryService
from app.services.mailer import LoggingMailer, OutgoingEmail
from app.services.replies import TemplateReplyDrafter
from tests.conftest import make_business


class FailingMailer:
    async def send(self, email: OutgoingEmail) -> None:
        raise RuntimeError("SMTP down")


def build(business_repo, enquiry_repo, mailer=None, notify="hello@example.com") -> EnquiryService:
    return EnquiryService(
        businesses=business_repo,
        enquiries=enquiry_repo,
        mailer=mailer or LoggingMailer(),
        drafter=TemplateReplyDrafter(),
        notify_email=notify,
        site_name="Open for Agents",
        dashboard_url="https://example.com/owner",
    )


def new_enquiry(**overrides) -> NewEnquiry:
    data = {
        "business_slug": "aajis-pickles",
        "customer_name": "Priya",
        "customer_email": "priya@example.com",
        "message": "Need 2 kg by Friday",
        "items": [EnquiryItem(product_id="mango-pickle", quantity="2 kg")],
        "delivery_location": "Kothrud",
        "source": EnquirySource.AI_AGENT,
        "agent_name": "Claude",
    }
    return NewEnquiry(**{**data, **overrides})


@pytest.fixture
async def repos(business_repo: SqliteBusinessRepository, enquiry_repo: SqliteEnquiryRepository):
    await business_repo.save(make_business())
    return business_repo, enquiry_repo


async def test_submit_stores_and_notifies_owner(repos) -> None:
    mailer = LoggingMailer()
    service = build(*repos, mailer=mailer)
    enquiry = await service.submit(new_enquiry())

    assert (await service.list_recent())[0].id == enquiry.id
    [email] = mailer.sent
    assert email.to == "hello@example.com"
    assert email.reply_to == "priya@example.com"
    assert "AI assistant (Claude)" in email.body
    assert "2 kg x mango-pickle" in email.body


async def test_submit_rejects_unknown_business_and_products(repos) -> None:
    service = build(*repos)
    with pytest.raises(NotFoundError):
        await service.submit(new_enquiry(business_slug="nope"))
    with pytest.raises(ValidationFailed, match="ghee"):
        await service.submit(new_enquiry(items=[EnquiryItem(product_id="ghee", quantity="1")]))


async def test_enquiry_survives_notification_failure(repos) -> None:
    service = build(*repos, mailer=FailingMailer())
    enquiry = await service.submit(new_enquiry())
    assert (await service.list_recent())[0].id == enquiry.id


async def test_draft_then_send_reply_marks_replied(repos) -> None:
    mailer = LoggingMailer()
    service = build(*repos, mailer=mailer)
    enquiry = await service.submit(new_enquiry())
    mailer.sent.clear()

    draft = await service.draft_reply(enquiry.id)
    assert "Mango pickle" in draft and "We do deliver to Kothrud" in draft

    replied = await service.send_reply(enquiry.id, "Yes, ₹900 for 2 kg.")
    assert replied.status is EnquiryStatus.REPLIED
    [email] = mailer.sent
    assert email.to == "priya@example.com"
    assert email.subject == "Re: your enquiry to Aaji's Pickles"


async def test_send_reply_guards(repos) -> None:
    service = build(*repos)
    enquiry = await service.submit(new_enquiry())
    with pytest.raises(ValidationFailed, match="empty"):
        await service.send_reply(enquiry.id, "   ")
    await service.send_reply(enquiry.id, "ok")
    with pytest.raises(ValidationFailed, match="already"):
        await service.send_reply(enquiry.id, "again")
    with pytest.raises(NotFoundError):
        await service.send_reply("missing", "x")


async def test_contact_message_goes_to_mailbox(repos) -> None:
    mailer = LoggingMailer()
    await build(*repos, mailer=mailer).send_contact_message(
        ContactMessage(name="Asha", email="asha@example.com", message="Hello")
    )
    assert mailer.sent[0].to == "hello@example.com"
    assert mailer.sent[0].reply_to == "asha@example.com"


async def test_contact_message_requires_configured_mailbox(repos) -> None:
    service = build(*repos, notify=None)
    with pytest.raises(ValidationFailed):
        await service.send_contact_message(ContactMessage(name="A", email="a@example.com", message="x"))
