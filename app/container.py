"""Composition root: the one place where concrete implementations are chosen and wired.

Everything else receives its dependencies through constructors (dependency injection), which
is what lets tests swap in fakes without monkey-patching.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
from mcp.server.mcpserver import MCPServer

from app.agent.mcp_server import build_mcp_server
from app.agent.shopper import ShopperAgent
from app.config import Settings
from app.repositories.sqlite import Database, SqliteBusinessRepository, SqliteEnquiryRepository
from app.services.catalog import CatalogService
from app.services.enquiries import EnquiryService
from app.services.extraction import CatalogExtractor, ClaudeCatalogExtractor, SampleCatalogExtractor
from app.services.mailer import LoggingMailer, Mailer, SmtpMailer
from app.services.replies import ClaudeReplyDrafter, ReplyDrafter, TemplateReplyDrafter


@dataclass(slots=True)
class Container:
    settings: Settings
    db: Database
    businesses: SqliteBusinessRepository
    catalog: CatalogService
    enquiries: EnquiryService
    mailer: Mailer
    mcp: MCPServer
    shopper: ShopperAgent | None


def _make_mailer(settings: Settings) -> Mailer:
    if not settings.smtp_enabled:
        return LoggingMailer()
    assert settings.smtp_username and settings.smtp_password  # narrowed by smtp_enabled
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password.get_secret_value(),
        sender=settings.mail_from or settings.smtp_username,
        sender_name=settings.site_name,
    )


def build_container(
    settings: Settings,
    *,
    mailer: Mailer | None = None,
    extractor: CatalogExtractor | None = None,
    drafter: ReplyDrafter | None = None,
    claude: anthropic.AsyncAnthropic | None = None,
) -> Container:
    if claude is None and settings.claude_enabled:
        assert settings.anthropic_api_key is not None
        claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2)

    if extractor is None:
        extractor = ClaudeCatalogExtractor(claude, settings.extraction_model) if claude else SampleCatalogExtractor()
    if drafter is None:
        drafter = ClaudeReplyDrafter(claude, settings.reply_model) if claude else TemplateReplyDrafter()
    mailer = mailer or _make_mailer(settings)

    db = Database(settings.database_path)
    businesses = SqliteBusinessRepository(db)
    enquiry_repo = SqliteEnquiryRepository(db)
    base_url = settings.public_base_url.rstrip("/")

    catalog = CatalogService(businesses, extractor)
    enquiries = EnquiryService(
        businesses=businesses,
        enquiries=enquiry_repo,
        mailer=mailer,
        drafter=drafter,
        notify_email=settings.notify_email or settings.smtp_username,
        site_name=settings.site_name,
        dashboard_url=f"{base_url}/owner",
    )
    mcp = build_mcp_server(catalog, enquiries, base_url)
    shopper = ShopperAgent(claude, settings.shopper_model, mcp) if claude else None

    return Container(
        settings=settings,
        db=db,
        businesses=businesses,
        catalog=catalog,
        enquiries=enquiries,
        mailer=mailer,
        mcp=mcp,
        shopper=shopper,
    )
