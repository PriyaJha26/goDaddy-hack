"""Public, human-facing pages plus machine-readable discovery endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import PlainTextResponse
from markupsafe import Markup
from pydantic import ValidationError

from app.domain.models import Business, ContactMessage, EnquiryItem, EnquirySource, NewEnquiry
from app.web.deps import ContainerDep, rate_limited, render

router = APIRouter()


def business_json_ld(business: Business, base_url: str) -> Markup:
    """schema.org structured data, so search engines and AI crawlers can read the catalogue."""
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": business.name,
        "description": business.description,
        "url": f"{base_url}/shop/{business.slug}",
        "address": {"@type": "PostalAddress", "addressLocality": business.city, "addressCountry": "IN"},
        "areaServed": [business.city, *business.service_areas],
        "knowsLanguage": business.languages,
        "hasOfferCatalog": {
            "@type": "OfferCatalog",
            "name": f"{business.name} catalogue",
            "itemListElement": [
                {
                    "@type": "Offer",
                    "price": f"{p.price_minor / 100:.2f}",
                    "priceCurrency": business.currency,
                    "availability": "https://schema.org/" + ("InStock" if p.available else "OutOfStock"),
                    "itemOffered": {"@type": "Product", "name": p.name, "description": p.description},
                }
                for p in business.products
            ],
        },
    }
    # Escape "<" so catalogue text can never close the <script> element.
    return Markup(json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))  # noqa: S704


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
async def home(request: Request, container: ContainerDep):
    return render(request, "home.html", businesses=await container.catalog.list_all())


@router.get("/shop/{slug}")
async def shop(request: Request, slug: str, container: ContainerDep, published: bool = False):
    business = await container.catalog.get(slug)
    base_url = container.settings.public_base_url.rstrip("/")
    return render(
        request, "shop.html", business=business, json_ld=business_json_ld(business, base_url), published=published
    )


@router.post("/shop/{slug}/enquire", dependencies=[rate_limited("enquire")])
async def enquire(
    request: Request,
    slug: str,
    container: ContainerDep,
    customer_name: Annotated[str, Form()],
    customer_email: Annotated[str, Form()],
    message: Annotated[str, Form()],
    product_id: Annotated[str, Form()] = "",
    quantity: Annotated[str, Form()] = "",
    delivery_location: Annotated[str, Form()] = "",
    website: Annotated[str, Form()] = "",  # honeypot: humans never fill this hidden field
):
    business = await container.catalog.get(slug)
    if website:
        return render(request, "message.html", title="Thank you", body="Your enquiry has been sent.")
    try:
        new = NewEnquiry(
            business_slug=business.slug,
            customer_name=customer_name,
            customer_email=customer_email,
            message=message,
            items=[EnquiryItem(product_id=product_id, quantity=quantity or "1")] if product_id else [],
            delivery_location=delivery_location or None,
            source=EnquirySource.WEB_FORM,
        )
    except ValidationError:
        return render(
            request,
            "message.html",
            status_code=422,
            title="Please check the form",
            body="Name, a valid email address and a message are required.",
        )
    await container.enquiries.submit(new)
    return render(
        request, "message.html", title="Enquiry sent", body=f"{business.name} will reply to {customer_email} by email."
    )


@router.post("/contact", dependencies=[rate_limited("contact")])
async def contact(
    request: Request,
    container: ContainerDep,
    name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    message: Annotated[str, Form()],
    website: Annotated[str, Form()] = "",
):
    if website:
        return render(request, "message.html", title="Thank you", body="Your message has been sent.")
    try:
        contact_message = ContactMessage(name=name, email=email, message=message)
    except ValidationError:
        return render(
            request,
            "message.html",
            status_code=422,
            title="Please check the form",
            body="Name, a valid email address and a message are required.",
        )
    await container.enquiries.send_contact_message(contact_message)
    return render(request, "message.html", title="Message sent", body="Thanks! We'll get back to you by email.")


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt(container: ContainerDep) -> str:
    """Plain-text guide for AI crawlers and assistants (llms.txt convention)."""
    base = container.settings.public_base_url.rstrip("/")
    lines = [
        f"# {container.settings.site_name}",
        "",
        "> A directory of small, often home-based Indian businesses that AI assistants can search and contact.",
        "",
        f"MCP server (Streamable HTTP): {base}/mcp",
        "Tools: search_products, get_business, check_delivery, send_enquiry",
        "",
        "## Businesses",
    ]
    lines += [f"- [{b.name}]({base}/shop/{b.slug}): {b.category}, {b.city}" for b in await container.catalog.list_all()]
    return "\n".join(lines) + "\n"
