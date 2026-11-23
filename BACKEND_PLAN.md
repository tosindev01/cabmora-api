# Cabmora — Backend Build Plan

Source: **PRD v1.0** (28/05/2026, Ayo Ogunwole) + current `backend/` scaffold. This plan is derived entirely from the PRD's in-scope features, so it does **not** depend on the UI designs being finished — the data model, endpoints, and business rules come from requirements, not screens. When designs land they affect the frontend and some request/response shapes, not the backend's structure.

Stack (already decided): **FastAPI + async SQLAlchemy 2.0 + Postgres (SQLite locally)**, clean architecture (`api → application → domain ← infrastructure`), JWT auth. Build every feature as a vertical slice through the four layers, following the patterns the auth/enquiry slices already establish.

---

## 1. What already exists (Phase 0 — done)

- **Auth**: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`; JWT (HS256), bcrypt hashing; `User` entity with roles `customer | creator | admin`.
- **Enquiries**: `POST /enquiries` (public), `GET /enquiries` (admin) — the public contact/enquiry feature.
- **Infrastructure**: async engine + session, `Base`, repository pattern (ABC in domain, SQLAlchemy impl in infrastructure), DI wiring in `api/deps.py`, domain exceptions centrally mapped to HTTP codes, CORS, `create_all` on startup (Alembic to come).
- **Auth guards ready to reuse**: `CurrentUserDep`, `CurrentAdminDep` (and we'll add `CurrentCreatorDep`).

This foundation proves the architecture end-to-end. Everything below is "add more slices the same way."

---

## 2. Target domain model

The PRD implies these entities. `User` and `Enquiry` exist; the rest are to build. Keep entities lean dataclasses; put ORM mapping in `infrastructure/models`, interfaces in `domain/repositories`.

| Entity | Purpose (PRD driver) | Key fields |
|---|---|---|
| **User** ✅ | Accounts for customers, creators, admins | email, full_name, hashed_password, role, is_active |
| **CreatorProfile** | Partner branding + storage account | user_id, studio_name, logo_url, brand_color, storage_plan_id |
| **Project** | A media job/booking a customer collaborates on ("[M] dashboard, progress tracking") | title, customer_id, creator_id (or Cabmora), status, event_type, event_date |
| **ProjectStatusEvent** | Progress timeline ("[M] monitor progress") | project_id, status, note, created_at |
| **MediaAsset** | A photo/video deliverable ("[M] upload media, preview") | project_id, kind (photo/video), storage_key, preview_key, watermarked, downloadable, size_bytes, status |
| **Comment** | Feedback / amendment request ("[M] comment, request amendments") | project_id, asset_id?, author_id, body, kind (comment/amendment), resolved |
| **Approval** | Acceptance of a deliverable/project ("[M] accept work") | project_id, approved_by, approved_at |
| **Rating** | Deliverable rating → Google Review ("[M] rate → post to Google") | project_id, stars, text, google_review_linked |
| **ShareLink** | Encrypted non-download preview link ("[M] share with friends/family, registered, non-download") | project_id, token, created_by, recipient_user_id?, expires_at, revoked |
| **Payment** | Pay for accepted work ("[M] make payment") | project_id, amount, currency, provider, provider_ref, status |
| **StoragePlan** | Creator space tiers ("[M] 3/5/7GB purchase") | name, size_gb, price, billing_period |
| **StorageSubscription** | A creator's active plan + usage metering | creator_id, plan_id, used_bytes, status, renews_at |
| **PromoBanner** | Admin event/promo banner ("[M] display banner") | title, body, image_url, link, active, starts_at, ends_at |
| **PortfolioItem** | Public portfolio showcase ("[M] portfolio") | title, media_url, category, featured, published |
| **Review** (Google) | Display Google reviews ("[M] Google review section") | source, author, stars, text, external_id (or fetched live/cached) |
| **Package / Deal** | Pricing packages (non-[M] website content) | name, price, features[], kind (package/deal) |

Roles & tenancy note: a **creator** owns projects and their customers; a **customer** sees only their own projects; **share-link guests** get scoped read-only preview. Decide the access model early (row-level ownership checks in use cases vs. a tenant column) — recommend ownership checks in use cases to start, since volumes are small.

---

## 3. Backend build, by phase

Ordered to match the PRD phasing. Each slice = entity + repo interface + repo impl + ORM model + use case(s) + router + tests.

### Phase 1 — Public Website MVP (backend support)
Everything the marketing site needs to be dynamic instead of hardcoded.

| Slice | Use cases | Endpoints |
|---|---|---|
| Enquiries ✅ (extend) | Notify admin on new enquiry (email) | (exists) + email side-effect |
| Portfolio | List/Get published items; admin CRUD | `GET /portfolio`, `GET /portfolio/{id}`, admin `POST/PATCH/DELETE` |
| Promo banner | Get active banner; admin CRUD | `GET /banner/active`, admin CRUD |
| Google Reviews | Fetch + cache reviews (Google Places API) | `GET /reviews` |
| Packages/Deals | List packages/deals; admin CRUD | `GET /packages`, admin CRUD |

### Phase 2 — Customer Portal MVP (the core of the platform)
This is where the real product value is; it's the biggest phase.

| Slice | Use cases | Endpoints |
|---|---|---|
| Accounts (extend auth) | Wire the new login/signup UI; guest access; forgot/reset password; email verification | `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/verify-email` |
| Projects | List my projects; get project + status timeline | `GET /projects`, `GET /projects/{id}` |
| Media preview | List/stream asset previews (signed, non-download) | `GET /projects/{id}/assets`, `GET /assets/{id}/preview` |
| Comments / amendments | Add comment, request amendment, resolve | `POST /assets/{id}/comments`, `GET /projects/{id}/comments` |
| Approval | Accept a deliverable / whole project | `POST /projects/{id}/approve` |
| Ratings | Rate deliverable → generate Google review deep-link | `POST /projects/{id}/rating` |
| Secure sharing | Create/revoke encrypted non-download share link; guest preview via token | `POST /projects/{id}/share`, `GET /share/{token}` |
| Payments | Create payment intent, handle webhook, mark paid | `POST /projects/{id}/pay`, `POST /webhooks/payments` |

### Phase 3 — Creator (Partner) Platform
Turns customers-only into B2B2C.

| Slice | Use cases | Endpoints |
|---|---|---|
| Storage plans | List plans; purchase/subscribe; meter usage | `GET /storage/plans`, `POST /storage/subscribe`, `GET /storage/usage` |
| Media upload | Initiate multipart/resumable upload; finalize; organise per project | `POST /assets/upload-init`, `POST /assets/{id}/complete` |
| Client access | Invite/manage customer access to a project; configure permissions | `POST /projects/{id}/access`, `PATCH/DELETE` |
| Delivery | Toggle watermarking, mark deliverable ready | `PATCH /assets/{id}` (watermark/downloadable flags) |
| Branding | Set studio logo/colours (simple white-label) | `GET/PUT /creator/branding` |

### Phase 4 — Administration
| Slice | Use cases | Endpoints |
|---|---|---|
| User management | List/suspend/change-role users | admin `GET/PATCH /admin/users` |
| Project & content mgmt | Manage projects, portfolio, banners, packages | admin CRUD (reuse Phase 1/2 use cases with admin guard) |

---

## 4. Cross-cutting infrastructure (and the decisions that gate each)

These are shared services, not single slices. Several need a call from Kenny before building — flagged **⚑**.

1. **Object storage + signed URLs** ⚑ — S3 / Cloudflare R2 / GCS. Every `MediaAsset` stores a `storage_key`; previews served via short-lived signed URLs. Underpins "[M] secure, non-downloadable links." *Decision: provider + region + CDN.*
2. **Watermarking pipeline** ⚑ — on-upload (bake a watermarked preview rendition) vs on-the-fly. Recommend on-upload for previews, keep originals clean. Needs a background worker.
3. **Video preview / transcoding** ⚑ — progressive MP4 renditions vs HLS. Large-file handling per PRD. Background worker + storage.
4. **Background jobs** — upload finalize, watermark, transcode, email, review sync. Add a task queue (e.g. Celery/RQ/Arq) or FastAPI background tasks for the cheap ones.
5. **Payments** ⚑ — provider (Stripe recommended); one-off project payments (Phase 2) + recurring creator storage plans (Phase 3). Needs webhook endpoint + secrets.
6. **Google Reviews integration** ⚑ — Places API for display; "auto-post rating to Google" is almost certainly a deep-link into Google's review flow (you can't post on a user's behalf), so `Rating` stores the link, not a posted review. Confirm interpretation.
7. **Email / notifications** — enquiry alerts, verification, reset, "gallery ready." Provider (SES/Resend/Postmark).
8. **Resumable uploads** — multipart/presigned-part uploads direct to storage for large media; backend issues part URLs and finalizes.
9. **Migrations** — add **Alembic** now (before the schema grows); stop relying on `create_all`.
10. **AuthZ hardening** — add `CurrentCreatorDep`, per-project ownership checks in use cases, and share-token validation. Rate-limit auth + enquiry + share endpoints.
11. **Config/secrets** — extend `Settings` for storage, payment, email, Google keys; per-environment `.env`.
12. **Testing** — keep the pytest + `AsyncClient` + in-memory DB pattern; add fixtures for authenticated customer/creator/admin.

**Non-functional (PRD):** WCAG 2.2 AA (frontend), encrypted non-download links, scalable media storage, phased delivery.

---

## 5. Recommended next slice

Build **Projects + ProjectStatusEvent** first (Phase 2 core): it's the spine everything else hangs off (media, comments, approval, rating, sharing, payment all reference a project), it needs no external-provider decision, and it lets you wire the real dashboard + connect the stubbed login/signup to actual data. Sequence: `Project` entity → repo interface → ORM model → `ListMyProjects` / `GetProject` use cases → router with `CurrentUserDep` ownership check → tests. Then layer `MediaAsset` (with a storage decision) on top.

Parallel low-risk track while storage/payments decisions are pending: **Portfolio + PromoBanner + Packages** (Phase 1) — pure CRUD, no external deps, makes the marketing site fully dynamic and gives the admin surface something to manage.

---

## Appendix — conventions to keep (from `docs/ARCHITECTURE.md`)

- One use-case class per action, single `execute()`; depends only on domain interfaces.
- Repositories: ABC in `domain/repositories`, SQLAlchemy impl in `infrastructure/repositories`.
- Domain raises `DomainError` subclasses; `main.py` maps them to HTTP centrally.
- `Enum(str, Enum)` (not `StrEnum` — sandbox is Python 3.10). Async everywhere.
- Entities are lean dataclasses; ORM models own `to_entity` / `from_entity`.
- Wire session → repo → use case in `api/deps.py`; routers stay thin.
