"""Enquiry use cases: receive (from web or AI agent), notify the owner, draft and send replies.

Human-in-the-loop by design: AI can draft a reply, but only an explicit owner action sends it.
"""

from __future__ import annotations

import logging

from app.domain.errors import NotFoundError, ValidationFailed
from app.domain.models import ContactMessage, Enquiry, EnquirySource, EnquiryStatus, NewEnquiry, utcnow
from app.repositories.base import BusinessRepository, EnquiryRepository
from app.services.mailer import Mailer, OutgoingEmail
from app.services.replies import ReplyDrafter

logger = logging.getLogger(__name__)


class EnquiryService:
    def __init__(
        self,
        businesses: BusinessRepository,
        enquiries: EnquiryRepository,
        mailer: Mailer,
        drafter: ReplyDrafter,
        notify_email: str | None,
        site_name: str,
        dashboard_url: str,
    ) -> None:
        self._businesses = businesses
        self._enquiries = enquiries
        self._mailer = mailer
        self._drafter = drafter
        self._notify_email = notify_email
        self._site_name = site_name
        self._dashboard_url = dashboard_url

    async def submit(self, new: NewEnquiry) -> Enquiry:
        business = await self._businesses.get(new.business_slug)
        if business is None:
            raise NotFoundError(f"No business found with id '{new.business_slug}'.")
        unknown = [i.product_id for i in new.items if business.product(i.product_id) is None]
        if unknown:
            raise ValidationFailed(f"Unknown product id(s) for {business.name}: {', '.join(unknown)}")

        enquiry = Enquiry(**new.model_dump())
        await self._enquiries.save(enquiry)
        await self._notify_owner(business.name, enquiry)
        return enquiry

    async def _notify_owner(self, business_name: str, enquiry: Enquiry) -> None:
        if not self._notify_email:
            return
        via = "website"
        if enquiry.source is EnquirySource.AI_AGENT:
            via = f"AI assistant ({enquiry.agent_name or 'unknown'})"
        items = "\n".join(f"  - {i.quantity} x {i.product_id}" for i in enquiry.items) or "  (none listed)"
        body = (
            f"New enquiry for {business_name} via {via}\n\n"
            f"From: {enquiry.customer_name} <{enquiry.customer_email}>\n"
            f"Items:\n{items}\n"
            f"Deliver to: {enquiry.delivery_location or '-'}\n"
            f"Needed by: {enquiry.needed_by or '-'}\n\n"
            f"{enquiry.message}\n\n"
            f"Review and reply: {self._dashboard_url}\n"
        )
        try:
            await self._mailer.send(
                OutgoingEmail(
                    to=self._notify_email,
                    subject=f"New enquiry for {business_name} from {enquiry.customer_name}",
                    body=body,
                    reply_to=str(enquiry.customer_email),
                )
            )
        except Exception:
            # The enquiry is already stored and visible on the dashboard; email is best-effort.
            logger.warning("Owner notification failed for enquiry %s", enquiry.id, exc_info=True)

    async def list_recent(self, limit: int = 50) -> list[Enquiry]:
        return await self._enquiries.list_recent(limit)

    async def _get(self, enquiry_id: str) -> Enquiry:
        enquiry = await self._enquiries.get(enquiry_id)
        if enquiry is None:
            raise NotFoundError("Enquiry not found.")
        return enquiry

    async def draft_reply(self, enquiry_id: str) -> str:
        enquiry = await self._get(enquiry_id)
        business = await self._businesses.get(enquiry.business_slug)
        if business is None:
            raise NotFoundError("Business not found.")
        return await self._drafter.draft(business, enquiry)

    async def send_reply(self, enquiry_id: str, reply_text: str) -> Enquiry:
        """Send an owner-approved reply to the customer from the domain mailbox."""
        text = reply_text.strip()
        if not text:
            raise ValidationFailed("The reply is empty.")
        enquiry = await self._get(enquiry_id)
        if enquiry.status is EnquiryStatus.REPLIED:
            raise ValidationFailed("This enquiry has already been answered.")
        business = await self._businesses.get(enquiry.business_slug)
        name = business.name if business else self._site_name
        await self._mailer.send(
            OutgoingEmail(to=str(enquiry.customer_email), subject=f"Re: your enquiry to {name}", body=text)
        )
        replied = enquiry.model_copy(
            update={"status": EnquiryStatus.REPLIED, "reply_text": text, "replied_at": utcnow()}
        )
        await self._enquiries.save(replied)
        return replied

    async def send_contact_message(self, message: ContactMessage) -> None:
        """Site-wide contact form: delivered straight to the domain mailbox."""
        if not self._notify_email:
            raise ValidationFailed("The contact form is not configured yet.")
        await self._mailer.send(
            OutgoingEmail(
                to=self._notify_email,
                subject=f"[{self._site_name}] Contact form: {message.name}",
                body=f"From: {message.name} <{message.email}>\n\n{message.message}\n",
                reply_to=str(message.email),
            )
        )
