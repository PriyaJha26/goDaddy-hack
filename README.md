# Open for Agents

**People are starting to shop by asking AI assistants. Most small shops are invisible to them.**

Open for Agents lets a home cook, tailor or local shop take a photo of their handwritten menu or price
list and, within a minute, be findable and contactable by any AI assistant, with enquiries arriving
in their own domain mailbox.

It is not a website builder. The "customer" it serves is an **AI agent**: the shop is published as an
[MCP](https://modelcontextprotocol.io) server that assistants can search, check delivery against, and send
enquiries through. A plain human page (with schema.org data for search engines) comes along for free.

## The problem

- Assistants answer "who sells mango pickle near me?" from structured, machine-readable sources.
- A home business that lives in WhatsApp photos and a handwritten board has none of that, so it doesn't exist.
- Big brands will adapt. Small and informal businesses, often run by women from home, will be left
  out, as happened with search rankings.

## What it does

| Step | Who | What happens |
|---|---|---|
| 1. Photo in | Owner | Upload a menu / price-list photo, any language, handwriting OK. |
| 2. Claude reads it | Claude Sonnet (vision + structured outputs) | Products, prices, units, English + original-script names, and search tags such as "aam ka achar" → "mango pickle". |
| 3. Owner checks | Owner | Edits anything wrong. **Nothing is published without confirmation.** |
| 4. Open for agents | Any MCP assistant | `search_products`, `get_business`, `check_delivery`, `send_enquiry` at `https://<domain>/mcp`. |
| 5. Enquiry → inbox | GoDaddy Titan mailbox | Owner is emailed; dashboard shows "via AI assistant". |
| 6. Reply | Claude Haiku drafts, owner approves | Reply is sent from `hello@<domain>` only after the owner clicks *Approve and send*. |

### Two-minute demo script

1. Open **/try** and ask: *"I need 2 kg of mango pickle delivered in Kothrud, Pune by Friday."*
   The assistant searches and finds nothing: the shop doesn't exist for AI yet.
2. Log in at **/owner** → *Add a shop from a photo* → upload a handwritten Marathi menu → review → *Publish*.
3. Ask the same question again on **/try**. The assistant now finds *Aaji's Pickles*, checks delivery to Kothrud,
   and quotes ₹450/kg. Every tool call is shown on screen.
4. Ask it to *send an enquiry* (with a name and email). It arrives in the domain mailbox and on the dashboard,
   badged **via AI assistant**.
5. Click *Draft reply with Claude* → edit → *Approve and send email*.

You can also connect a real assistant: in Claude, add `https://<domain>/mcp` as a custom connector.

## How GoDaddy and Claude are used

- **Claude Sonnet 5.5 (vision + structured outputs):** reads photos into a validated `CatalogDraft` schema.
- **Claude Haiku 5.5:** drafts short replies in the customer's language. It is cheap, fast and human-approved.
- **Claude Sonnet 5.5 (tool use):** the demo shopper agent, which calls the *same* MCP server any external assistant uses.
- **MCP (open standard from Anthropic):** the product's core interface for AI assistants.
- **GoDaddy domain + DNS:** the public identity of the storefront and its MCP endpoint.
- **GoDaddy VPS (Docker):** hosts the app and Caddy (automatic HTTPS).
- **GoDaddy Titan email:** enquiry notifications, the site contact form, and owner replies to customers.
- **Roadmap: GoDaddy Agent Name Service (ANS):** register each shop's agent endpoint with a verifiable,
  domain-bound identity so assistants can trust it.

## Architecture

```
            ┌────────────── Web (FastAPI) ───────────────┐        ┌── Agent interface ──┐
 Owner ───▶ │ /owner  onboarding · inbox · approve reply │        │  MCP server  /mcp   │ ◀── Any AI assistant
 Visitor ─▶ │ /shop/* (schema.org JSON-LD) · /contact    │        │  4 tools            │ ◀── /try demo agent
            └──────────────────────┬─────────────────────┘        └──────────┬──────────┘     (in-process)
                                   ▼                                         ▼
                     ┌──────────── Services (use cases) ─────────────────────────┐
                     │ CatalogService · EnquiryService · search_products (pure)  │
                     └───────┬──────────────────┬──────────────────┬─────────────┘
                             ▼                  ▼                  ▼
                CatalogExtractor        ReplyDrafter           Mailer           Repositories
                (Claude | Sample)   (Claude | Template)   (SMTP | Logging)   (SQLite behind Protocols)
```

### Design patterns

| Pattern | Where | Why |
|---|---|---|
| Repository | `app/repositories/` | Services depend on `Protocol`s, not SQLite; swap to Postgres without touching logic. |
| Strategy | `CatalogExtractor`, `ReplyDrafter`, `Mailer` | Claude/SMTP in production, deterministic fallbacks offline and in tests. |
| Dependency injection + composition root | `app/container.py` | All wiring in one place; tests inject fakes without monkey-patching. |
| Application factory | `app/main.py:create_app` | Isolated, fully configured app per test or process. |
| Adapter | `app/agent/` | One MCP tool definition serves both external assistants (HTTP) and the demo agent (in-process). |
| Decorator | `_tool_errors` | Maps domain errors to readable MCP tool errors. |

### Security

- **Secrets** only via environment / `.env` (git-ignored). Production refuses to start with default secrets.
- **Human in the loop:** AI never publishes a catalogue or emails a customer without an explicit owner action.
  `send_enquiry` is annotated as not read-only, and its description requires user confirmation.
- **Prompt-injection hygiene:** customer and owner text is fenced in tags and declared as data in system prompts.
  Drafts are never auto-sent.
- **Owner auth:** signed, expiring, `HttpOnly` + `SameSite=Lax` session cookie (`Secure` over HTTPS). Constant-time
  password comparison. Login is rate-limited.
- **CSRF** tokens on every owner form. **Honeypot** + rate limits on public forms, `/api/try` and `/mcp`.
- **Uploads:** size-capped, type detected from magic bytes (not the client's header), and never written to disk.
- **MCP DNS-rebinding protection:** only our own `Host`/`Origin` are accepted.
- **Headers:** strict CSP (no inline scripts), `X-Frame-Options: DENY`, `nosniff`, HSTS over HTTPS.
- **XSS:** Jinja autoescaping. JSON-LD escapes `<`. The demo UI renders tool output with `textContent` only.
- **Email header injection** blocked by collapsing header values to a single line.
- **Container** runs as a non-root user. The app port is internal; only Caddy is exposed.

## Running locally

Requires Python 3.12+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # add ANTHROPIC_API_KEY to use Claude; works without it in demo mode
uvicorn app.main:app_factory --factory --reload
# open http://localhost:8000  (owner password: OWNER_PASSWORD, "dev-owner" by default in development)
```

Without an API key the app still runs: photo reading returns sample data, replies use a template, and `/try`
explains that it needs a key.

## Tests and quality

```bash
pytest -q                          # 93 tests: domain, repositories, services, MCP tools, agent loop, web, security
ruff check . && ruff format --check .
```

Claude is never called in tests. A fake client (`tests/fakes.py`) asserts the exact requests (model, schema,
image block, tool results), and the MCP server is tested both in-process and over real HTTP.
CI (`.github/workflows/ci.yml`) runs lint, tests and a Docker build on every push.

## Deploying to a GoDaddy VPS

1. **DNS:** point `A` records for `@` and `www` to the VPS IP (`gddy dns --help`, or the GoDaddy DNS page).
2. **Server:** install Docker, clone the repo, then:
   ```bash
   cp .env.example .env   # ENVIRONMENT=production, DOMAIN, PUBLIC_BASE_URL=https://<domain>, secrets, SMTP
   docker compose up -d --build
   ```
   Caddy obtains the HTTPS certificate automatically once DNS resolves.
3. **Email:** create `hello@<domain>` in Titan, put its credentials in `.env`, and send a test via the contact form.
4. **Check:** `https://<domain>/healthz`, `/llms.txt`, and connect an assistant to `https://<domain>/mcp`.

Data lives in the `app-data` Docker volume (`/data/app.db`).

## Limitations and next steps

- Single owner account for the prototype. Next: per-shop accounts with email magic links.
- One process (in-memory rate limiter, SQLite). Next: Redis + Postgres for horizontal scaling.
- Enquiries, not payments. Next: UPI payment links in owner replies.
- Register shops with **GoDaddy ANS** so assistants can verify a shop's agent identity.
- WhatsApp onboarding: send the menu photo to a number instead of using the web form.

## Project layout

```
app/
  config.py            typed settings (pydantic-settings)
  container.py         composition root (dependency injection)
  main.py              application factory, error handling, middleware, /mcp mount
  domain/              models (Pydantic) and domain errors
  repositories/        Protocols + SQLite implementations, migrations
  services/            catalog, enquiries, search, extraction (Claude vision), replies, mailer
  agent/               MCP server (tools) and the demo shopper agent
  web/                 routes, security (sessions, CSRF, rate limits, headers), templates, static
tests/                 pytest suite with fakes
deploy/Caddyfile       HTTPS reverse proxy
Dockerfile, docker-compose.yml
```
