"""Owner-only pages: login, onboarding from a photo, and the enquiry inbox."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.domain.errors import ValidationFailed
from app.domain.models import Product, slugify
from app.services.catalog import BusinessProfile, products_from_draft
from app.web.deps import ContainerDep, OwnerDep, get_sessions, rate_limited, render
from app.web.security import SESSION_COOKIE, SessionManager, passwords_match, verify_csrf

router = APIRouter(prefix="/owner")


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


@router.get("/login")
async def login_page(request: Request):
    return render(request, "owner_login.html")


@router.post("/login", dependencies=[rate_limited("login", per_minute=5)])
async def login(
    request: Request,
    container: ContainerDep,
    sessions: Annotated[SessionManager, Depends(get_sessions)],
    password: Annotated[str, Form()],
):
    if not passwords_match(password, container.settings.owner_password.get_secret_value()):
        return render(request, "owner_login.html", status_code=401, error="Incorrect password.")
    token, _ = sessions.issue()
    response = RedirectResponse("/owner", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=sessions.max_age, httponly=True, secure=sessions.secure, samesite="lax"
    )
    return response


@router.post("/logout")
async def logout(owner: OwnerDep, csrf_token: Annotated[str, Form()]):
    verify_csrf(owner, csrf_token)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("")
async def dashboard(request: Request, owner: OwnerDep, container: ContainerDep):
    businesses = {b.slug: b for b in await container.catalog.list_all()}
    return render(
        request,
        "owner_dashboard.html",
        csrf_token=owner.csrf_token,
        enquiries=await container.enquiries.list_recent(),
        businesses=businesses,
        drafts={},
    )


@router.post("/enquiries/{enquiry_id}/draft")
async def draft_reply(
    request: Request, enquiry_id: str, owner: OwnerDep, container: ContainerDep, csrf_token: Annotated[str, Form()]
):
    verify_csrf(owner, csrf_token)
    draft = await container.enquiries.draft_reply(enquiry_id)
    businesses = {b.slug: b for b in await container.catalog.list_all()}
    return render(
        request,
        "owner_dashboard.html",
        csrf_token=owner.csrf_token,
        enquiries=await container.enquiries.list_recent(),
        businesses=businesses,
        drafts={enquiry_id: draft},
    )


@router.post("/enquiries/{enquiry_id}/send")
async def send_reply(
    enquiry_id: str,
    owner: OwnerDep,
    container: ContainerDep,
    csrf_token: Annotated[str, Form()],
    reply_text: Annotated[str, Form()],
):
    verify_csrf(owner, csrf_token)
    await container.enquiries.send_reply(enquiry_id, reply_text)
    return RedirectResponse("/owner", status_code=303)


@router.get("/onboard")
async def onboard_page(request: Request, owner: OwnerDep):
    return render(request, "owner_onboard.html", csrf_token=owner.csrf_token)


@router.post("/onboard", dependencies=[rate_limited("onboard", per_minute=6)])
async def onboard_upload(
    request: Request,
    owner: OwnerDep,
    container: ContainerDep,
    csrf_token: Annotated[str, Form()],
    photo: UploadFile,
    owner_notes: Annotated[str, Form()] = "",
):
    verify_csrf(owner, csrf_token)
    limit = container.settings.max_upload_bytes
    image = await photo.read(limit + 1)
    if not image:
        raise ValidationFailed("Please choose a photo of your menu or price list.")
    if len(image) > limit:
        raise ValidationFailed(f"The photo is too large. Maximum size is {limit // (1024 * 1024)} MB.")
    draft = await container.catalog.draft_from_image(image, owner_notes)
    return render(
        request,
        "owner_review.html",
        csrf_token=owner.csrf_token,
        draft=draft,
        products=products_from_draft(draft),
    )


@router.post("/onboard/publish")
async def onboard_publish(request: Request, owner: OwnerDep, container: ContainerDep):
    form = await request.form()
    verify_csrf(owner, str(form.get("csrf_token", "")))

    names = form.getlist("product_name")
    columns = {
        key: form.getlist(key)
        for key in ("product_local", "product_description", "product_price", "product_unit", "product_tags")
    }
    if not names or any(len(col) != len(names) for col in columns.values()):
        raise ValidationFailed("The product list was incomplete. Please try again.")

    products: list[Product] = []
    for i, raw_name in enumerate(names):
        name = str(raw_name).strip()
        if not name:
            continue  # owner cleared the row to remove it
        try:
            price_minor = max(0, round(float(str(columns["product_price"][i]) or 0) * 100))
        except ValueError as exc:
            raise ValidationFailed(f"Price for '{name}' must be a number.") from exc
        draft = {
            "name": name,
            "name_local": str(columns["product_local"][i]).strip() or None,
            "description": str(columns["product_description"][i]).strip(),
            "unit": str(columns["product_unit"][i]).strip() or "each",
            "tags": [t.lower() for t in _split_list(str(columns["product_tags"][i]))][:12],
        }
        products.append(Product(id=_unique_id(name, products), price_minor=price_minor, **draft))

    if not products:
        raise ValidationFailed("Add at least one product.")

    profile = BusinessProfile(
        name=str(form.get("business_name", "")).strip(),
        city=str(form.get("city", "")).strip(),
        category=str(form.get("category", "")).strip() or "local business",
        description=str(form.get("description", "")).strip(),
        service_areas=_split_list(str(form.get("service_areas", ""))),
        owner_name=str(form.get("owner_name", "")).strip() or None,
        languages=tuple(_split_list(str(form.get("languages", "")))) or ("English",),
    )
    if not profile.name or not profile.city:
        raise ValidationFailed("Business name and city are required.")
    business = await container.catalog.publish(profile, products)
    return RedirectResponse(f"/shop/{business.slug}?published=true", status_code=303)


def _unique_id(base: str, existing: list[Product]) -> str:
    base = slugify(base, max_length=50)
    taken = {p.id for p in existing}
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate
