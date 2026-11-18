"""The agent-facing storefront: an MCP server any AI assistant can connect to.

This is the single source of truth for the agent tools. External assistants reach it over
Streamable HTTP at ``/mcp``; the built-in demo shopper (``app.agent.shopper``) calls the very
same server in-process, so the demo exercises exactly what real assistants use (Adapter pattern).
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field, ValidationError

from app.domain.errors import DomainError
from app.domain.models import Business, EnquiryItem, EnquirySource, NewEnquiry
from app.services.catalog import CatalogService
from app.services.enquiries import EnquiryService

SERVER_INSTRUCTIONS = """\
Open for Agents lists small, often home-based Indian businesses (food, pickles, tailoring,
baking and more) that are not on big marketplaces. Use `search_products` to find products,
`get_business` for full details, `check_delivery` before promising delivery, and
`send_enquiry` to contact the owner. Owners reply by email, usually within a day.
Never send an enquiry without the user's explicit confirmation of its contents."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _tool_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn expected domain failures into readable tool errors instead of crashes."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        except ValidationError as exc:
            fields = ", ".join(sorted({".".join(map(str, e["loc"])) for e in exc.errors()}))
            raise ToolError(f"Invalid value for: {fields}") from exc

    return wrapper


def business_summary(business: Business, base_url: str) -> dict[str, Any]:
    return {
        "business_id": business.slug,
        "name": business.name,
        "category": business.category,
        "city": business.city,
        "service_areas": business.service_areas,
        "page_url": f"{base_url}/shop/{business.slug}",
    }


def build_mcp_server(catalog: CatalogService, enquiries: EnquiryService, base_url: str) -> MCPServer:
    server = MCPServer(
        name="open-for-agents",
        title="Open for Agents: small-business directory",
        instructions=SERVER_INSTRUCTIONS,
        website_url=base_url,
        version="0.1.0",
    )

    @server.tool(annotations=READ_ONLY)
    @_tool_errors
    async def search_products(
        query: Annotated[str, Field(description="What the user wants, e.g. 'mango pickle' or 'blouse stitching'")],
        location: Annotated[
            str | None, Field(description="City, locality or PIN code to deliver to; omit to search everywhere")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=20, description="Maximum results")] = 5,
    ) -> dict[str, Any]:
        """Search products from small local businesses. Matches English names, local-language names
        and common synonyms. Returns product ids, prices and the business that sells each one.
        If `location` is given, only businesses that serve that location are returned."""
        hits = await catalog.search(query, location, limit)
        return {
            "results": [
                {
                    "business_id": h.business.slug,
                    "business_name": h.business.name,
                    "city": h.business.city,
                    "product_id": h.product.id,
                    "product_name": h.product.name,
                    "local_name": h.product.name_local,
                    "price": h.product.price_display,
                    "unit": h.product.unit,
                    "page_url": f"{base_url}/shop/{h.business.slug}",
                }
                for h in hits
            ],
            "note": None if hits else "No matching products. Try a broader term or omit the location.",
        }

    @server.tool(annotations=READ_ONLY)
    @_tool_errors
    async def get_business(
        business_id: Annotated[str, Field(description="The business_id from search results")],
    ) -> dict[str, Any]:
        """Get a business's full profile and complete catalogue with prices and availability."""
        business = await catalog.get(business_id)
        return {
            **business_summary(business, base_url),
            "description": business.description,
            "languages": business.languages,
            "products": [
                {
                    "product_id": p.id,
                    "name": p.name,
                    "local_name": p.name_local,
                    "description": p.description,
                    "price": p.price_display,
                    "unit": p.unit,
                    "available": p.available,
                }
                for p in business.products
            ],
        }

    @server.tool(annotations=READ_ONLY)
    @_tool_errors
    async def check_delivery(
        business_id: Annotated[str, Field(description="The business_id from search results")],
        location: Annotated[str, Field(description="City, locality or PIN code")],
    ) -> dict[str, Any]:
        """Check whether a business delivers to a location. Call this before telling the user
        that delivery is possible."""
        business = await catalog.get(business_id)
        return {
            "business_id": business.slug,
            "location": location,
            "delivers": business.delivers_to(location),
            "service_areas": [business.city, *business.service_areas],
        }

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
    @_tool_errors
    async def send_enquiry(
        business_id: Annotated[str, Field(description="The business_id from search results")],
        customer_name: Annotated[str, Field(description="The user's name")],
        customer_email: Annotated[str, Field(description="The user's email; the owner replies here")],
        message: Annotated[str, Field(description="The enquiry, in the user's own language")],
        items: Annotated[
            list[EnquiryItem] | None, Field(description="Products and quantities, using product_id values")
        ] = None,
        delivery_location: Annotated[str | None, Field(description="Where to deliver")] = None,
        needed_by: Annotated[str | None, Field(description="When it is needed, e.g. 'Friday 22 Nov'")] = None,
        assistant_name: Annotated[str | None, Field(description="Name of the AI assistant sending this")] = None,
    ) -> dict[str, Any]:
        """Send an order enquiry to the business owner, who replies to the user by email.
        This contacts a real person: only call it after the user has confirmed the details and
        given their name and email. It does not place a binding order or take payment."""
        enquiry = await enquiries.submit(
            NewEnquiry(
                business_slug=business_id,
                customer_name=customer_name,
                customer_email=customer_email,
                message=message,
                items=items or [],
                delivery_location=delivery_location,
                needed_by=needed_by,
                source=EnquirySource.AI_AGENT,
                agent_name=assistant_name,
            )
        )
        return {
            "enquiry_id": enquiry.id,
            "status": "sent_to_owner",
            "next_step": f"The owner will reply to {enquiry.customer_email} by email.",
        }

    return server
