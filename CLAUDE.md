# cabmora-api — instructions for Claude Code

FastAPI backend for the **Cabmora** photography & videography platform. Clean
architecture, async SQLAlchemy 2.0, Postgres in deployment (SQLite for tests).

**The frontends are a separate repo** (`cabmora-web`: public site + admin
console, sibling folder). The only thing shared between the two is the HTTP
contract, published here at `/openapi.json`. A change to a request/response
shape is a cross-repo change.

## Read these before starting work

| File | Why |
|---|---|
| `BACKEND_PLAN.md` | **The build plan.** Target domain model, slice-by-slice endpoints per phase, cross-cutting infra and the decisions that gate each |
| `../cabmora-web/docs/PRD.md` | The requirements. PRD v1.0 (28/05/2026, Ayo Ogunwole). `[M]` marks minimum-viable |
| `../cabmora-web/docs/ARCHITECTURE.md` | The shared layer conventions (documented in the web repo) |
| `../CLAUDE.md` | Shared platform context — infra, R2, storage economics, open decisions |

## The product in one paragraph

Cabmora Ltd (B2C + B2B2C) needs a greenfield platform where customers discover
services, enquire, preview and comment on media deliverables, track project
progress, approve work and pay — and where partner photographers/videographers
deliver their own clients' projects with secure links, watermarking and light
self-branding. Four principal types: customers, creators, **creators' clients**
(a tenancy question, not a role), admins. Out of scope: native mobile app,
complex multi-brand white-labelling, advanced analytics, social features.

---

## Architecture — the one rule that matters

```
app/
├── core/            cross-cutting: config, security, exceptions
├── domain/          PURE Python. No FastAPI, no SQLAlchemy imports.
│   ├── entities/    business objects (lean dataclasses)
│   └── repositories/  abstract repository interfaces (ABCs)
├── application/
│   └── use_cases/   one class per business action; depends ONLY on domain
├── infrastructure/  implementations of domain interfaces
│   ├── database.py  SQLAlchemy async engine/session
│   ├── models/      ORM models, own to_entity / from_entity
│   └── repositories/  concrete repos implementing the domain ABCs
└── api/             presentation layer
    ├── deps.py      DI wiring (session → repo → use case)
    ├── schemas/     pydantic request/response models
    └── v1/routers/  thin: validate → call use case → respond
```

**Dependency rule: `api → application → domain ← infrastructure`.**

`domain/` imports nothing outward. Infrastructure implements domain interfaces.
**Routers never touch the ORM; use cases never touch HTTP.**

`api/deps.py` importing `infrastructure` is the **composition root** — that is
correct, not a leak. Verified 2026-08-31: no cross-layer import leaks in either
direction.

### Conventions

- One use-case class per action (`RegisterUser`, `SubmitEnquiry`), a single
  `execute()` method, depending only on domain interfaces.
- Repositories: ABC in `domain/repositories`, SQLAlchemy impl in
  `infrastructure/repositories`.
- Entities are lean dataclasses; ORM models own `to_entity` / `from_entity`.
- Domain raises `DomainError` subclasses from `core/exceptions.py`; `main.py`
  maps them to HTTP codes **centrally** — don't catch-and-convert in routers.
- `Enum(str, Enum)`, **not** `StrEnum` — code has to run on Python 3.10 in some
  sandboxes even though the Docker image is 3.12.
- Async everywhere: SQLAlchemy 2.0 async, asyncpg in deployment, aiosqlite
  locally.
- Settings via pydantic-settings (`core/config.py`, `.env`).
- Tests: pytest + httpx `AsyncClient` against the app with an in-memory DB.

**Build every feature as a vertical slice through all four layers**, following
the patterns the auth and enquiry slices already establish:
entity → repo interface → ORM model → repo impl → use case(s) → schemas →
router → tests.

---

## Auth

- JWT (HS256), bcrypt hashing. `User` entity with roles
  `customer | creator | admin`.
- **Browsers get an HttpOnly cookie** (`cabmora_session`; `Secure`,
  `SameSite=Lax`) set at login. **`Authorization: Bearer` is still supported**
  for non-browser clients — mobile, CI, curl, the tests, and the Swagger UI
  (call `POST /auth/login` in `/docs` once and every later "Try it out" is
  authenticated). Both schemes are declared server-side; keep it that way.
- Guards live in `app/api/deps.py`: `CurrentUserDep`, `CurrentAdminDep`.
  `CurrentCreatorDep` still needs adding.
- CORS never engages in deployment — nginx proxies `/api` to this service so
  browser requests are same-origin, and `CORS_ORIGINS=[]`. `CORS_ORIGINS` is
  parsed as a **JSON array** by pydantic-settings:
  `CORS_ORIGINS=["https://cabmora.com"]`, not a bare string.

---

## Media must never route through the API

Browser → Railway → R2 pays Railway egress at $0.05/GB *and* holds multi-GB RAW
files in this container's memory, and Railway request timeouts will kill large
uploads.

Use **presigned PUT** for upload and **presigned GET with a short TTL** for
delivery. This is also how the PRD's "secure, non-downloadable links"
requirement is satisfied. The API issues part URLs and finalizes; bytes go
browser ↔ R2 directly.

**Before the first upload lands, two schema decisions cannot be retrofitted:**
content-addressed object keys (hash + refcount, not `user/project/filename`),
and an append-only **usage-events** log per creator rather than a current-state
counter. Entitlements should be **grants** `{capacity_gb, tier, starts_at,
expires_at}`, not a `quota_gb` number, and storage plans belong in a **DB table**
rather than the frontend's TS fixture. Full reasoning in `../CLAUDE.md` §3.

---

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head               # schema — the app no longer creates it
uvicorn app.main:app --reload      # :8000, docs at /docs
pytest
```

### Migrations

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "what changed" # after ANY model change
alembic check                                     # do models and migrations agree?
```

`migrations/env.py` reads `DATABASE_URL` from `app.core.config`, so there is no
URL in `alembic.ini` — one source of truth with the app. `render_as_batch=True`
is on because SQLite cannot `ALTER TABLE`; it is a no-op on Postgres.

Tests build their schema with `create_all`, which reads the models directly — so
a model change with no migration would pass the whole suite and fail on deploy.
`tests/test_migrations.py` closes that hole by running `alembic check` against a
freshly migrated scratch database. **If it fails, you forgot to autogenerate.**

Docker: `docker compose up --build` — API on :8000, Postgres on :5432
(`cabmora` / `cabmora`). This is what the `cabmora-web` dev stack proxies to.

### Configuration

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` in deployment. Railway hands you `postgresql://` — **you must rewrite the scheme** |
| `JWT_SECRET_KEY` | rotate off the placeholder: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | default 60 |
| `CORS_ORIGINS` | JSON array; leave empty in deployment |
| `ENVIRONMENT` | `local` / `production` |

**Deployment gotcha:** the `CMD` must be **shell form** so `$PORT` expands
(Railway injects `PORT`). See `../CLAUDE.md` §2.

**Git:** never run `git add` / `git commit` / `git status` from a sandbox
against this folder — it leaves `.lock` files the sandbox cannot delete. Hand
git write commands to Taiwo. See `../CLAUDE.md` §5.

---

## Current state

*Checked against the code on 2026-10-05. This section was badly out of date
before that — it claimed two entities when there were seventeen, and "no
integrations wired" when R2 and Mailtrap had both been live for weeks, which
cost real time in at least two sessions. If you change what is here, change
this too.*

**114 operations across 97 paths**, counted 2026-10-26. `GET /openapi.json` is
the contract; this is the shape of it.

**Entities (19):** `access_group` · `asset` · `comment` · `consultation` ·
`creator_application` · `enquiry` · `enquiry_event` · `gallery_share` ·
`invite` · `invoice` · `issue_report` · `notification` · `password_reset` ·
`preferences` · `project` · `project_event` · `rating` · `unmatched_funds` ·
`user`

**Routers (15):** `admin` · `auth` · `billing` · `comments` · `creators` ·
`enquiries` · `enquiries_admin` · `health` · `media` · `media_local` ·
`notifications` · `projects` · `reviews` · `sharing` · `support`

**Guards in `api/deps.py`:** `CurrentUserDep`, `CurrentActiveUserDep`,
`CurrentAdminDep`, `CurrentStaffDep`, `CurrentTeamDep`. Role is only half of
it — per-project access is a **row-level** check (`Project.is_visible_to`), and
a coordinator's reach is a **permission union** (`User.reachable`) rather than
their role. See `tests/test_permissions.py`.

**34 Alembic migrations.** `create_all` on startup is gone; the Dockerfile runs
`alembic upgrade head` before uvicorn.

### Integrations — what is actually wired

| | State |
|---|---|
| **Cloudflare R2** | **Live.** `infrastructure/storage/r2_media_storage.py`, boto3, presigned multipart upload + confirm. `LocalMediaStorage` stands in when `MEDIA_BACKEND=local`, and the config guard refuses that outside local development. |
| **Mailtrap** | **Live.** `infrastructure/email/mailtrap_email_sender.py`, over httpx — no SDK. `LoggingEmailSender` prints instead of sending, locally only. **Sending mode:** a test action delivers real email. |
| **Stripe** | **Live.** `infrastructure/payments/stripe_payment_gateway.py`, over httpx — no SDK, same choice as Mailtrap. Hosted Checkout plus a signature-verified webhook at `POST /webhooks/stripe`. `FakePaymentGateway` survives for local only: `get_payment_gateway` **raises** outside local when `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are absent, rather than quietly taking no money. Also **Stripe bank transfers** (`customer_balance` / `gb_bank_transfer`): each customer is issued their own account number and Stripe reconciles what arrives, so those settle from a webhook like a card. Needs the `gb_bank_transfer_payments` capability — code-complete without it, but Stripe returns an intent with no instructions and `_funding` refuses rather than showing a blank account. A transfer to Cabmora's *own* account (`BANK_*`) is a different method and is still confirmed by hand. Money Stripe cannot place against any invoice — paid early, or paid short — is recorded as `UnmatchedFunds` from `cash_balance.funds_available` and raised on the bell, because every part of that failing is silent otherwise. |
| **Bird (SMS)** | Not referenced anywhere. |

### Notifications — two channels, not one

Added 2026-10-07 for UAT #7 ("show notification for all on admin & client
portal"). **Email and the in-app bell are separate channels and neither is
derived from the other.** Get this wrong and the bugs are silent.

- `Notification` is one row **per recipient**, written when the event happens.
  The audience is resolved then, so "every admin" means the admins who were
  there — not whoever holds the role when the bell is next opened.
- `application/use_cases/notifications/notifier.py` is where audiences live. It
  is **not** a port (nothing external implements it) and **not** a decorator on
  `EmailSender`, which was the tempting shortcut. Two reasons, both in its
  docstring: the sender knows an *address* and staff mail goes to one configured
  inbox, so "tell every admin" cannot be expressed through it; and the
  preference gate sits on that chain, so a client muting invoice *email* would
  have silenced their own bell.
- `NotificationKind` (in `preferences`) gates **email only**. It is a different
  enum from `NotificationTopic` on purpose — three things you may decline by
  mail, eight things that can happen. Do not merge them.
- **Announcing must never fail the thing it announces.** Every `Notifier` method
  swallows and logs. A captured lead must not become a 500 because a row would
  not insert.
- `url` on a notification is a **path**, validated in the entity, and `//host`
  is refused as well as `https://host` — a protocol-relative URL passes a
  `startswith("/")` check and still walks somebody off to another origin.

### Things that are built and easy to miss

- **Media** is content-addressed with a reference count, and `StorageEvent` is
  an append-only usage log. Both of the "cannot be retrofitted" decisions in
  `../CLAUDE.md` §3 are done.
- **Video uploads** (2026-10-05). `image/*` and `video/*`, 2 GB and 10 GB
  ceilings. A video skips rendition generation entirely — it has no watermarked
  copy to make, and `storage.read` would pull the whole film into this process
  to find that out. `content_type` travels with every asset link so a gallery
  knows to draw a player. **Transcoding still does not exist**, so a ProRes
  master stores correctly and will not play in a browser.
- **Notification preferences are enforced at the boundary.**
  `PreferenceAwareEmailSender` wraps the configured sender, and `EmailSenderDep`
  hands out the wrapped one — so honouring a mute is the default rather than
  something each new feature remembers. `NotificationKind` is the complete list
  of what can be declined; everything absent from it is unmutable by
  construction, including password resets and "your photographs are ready".
- **A customer sees every project that is theirs, at any stage** — drafts
  included, since 2026-10-05. Ownership is the whole rule.
- **PEP 649.** Local Python is 3.14 and defers annotation evaluation; the
  Docker image is 3.12 and evaluates eagerly. This has caused **two production
  outages**. `tests/test_annotations_evaluate.py` guards it — do not delete it,
  and do not name a method after something its own later annotations subscript.

**Known gaps:**

1. **No transcoding**, so camera-native video does not play back. Costed
   before it is committed to — it is the largest unpriced item on the platform.
2. **No storage plans or entitlements.** Usage is computable
   (`MediaRepository.usage_bytes`); the allowance it would be measured against
   does not exist. Blocked on the pricing decision in `../CLAUDE.md` §3, not on
   engineering.
3. **Sessions are stateless.** A JWT in a cookie that the server keeps no
   record of — so there is nothing to list as a logged-in device and nothing to
   revoke. 2FA and "sign out everywhere" both need server-side sessions first.
4. **Nobody can change an email address.** `PATCH /auth/me` refuses it by
   design, and `PATCH /admin/users/{id}` only does role and status.
5. `README.md` still lists "no role-based authorisation" as a gap. Stale —
   see the guards above.

## What to build next

Judgement call each time, but the standing order of preference:

1. **Whatever is lying to a user.** A control that reports success and does
   nothing is worse than one that is absent — the fake 2FA toggle and the fake
   password form were both found this way, and both had been shipped.
2. **Transcoding**, once priced. It unblocks video playback and the 4K ProRes
   claim the marketing site already makes.
3. **Storage plans**, once priced. Table, not a TS fixture; grants, not a
   `quota_gb`.
4. **Bird (SMS)** and **Google Reviews**, neither started.

Open with Ayo in `../cabmora-web/docs/PRD.md` §Q&A: whether creators require
approval, where portfolio URL / specialty / studio name are stored, and whether
"auto-post rating to Google" means a deep link (it has to — you cannot post as
somebody else).
