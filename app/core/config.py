from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The value we refuse to run with outside local. Named so this check and
# .env.example cannot drift apart silently.
DEFAULT_SECRET = "change-me-in-production"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Cabmora API"
    environment: str = "local"
    database_url: str = "sqlite+aiosqlite:///./cabmora.db"
    jwt_secret_key: str = DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Who invoices are from -------------------------------------------
    # Facts about a company rather than about this codebase, so they are
    # configuration. An invoice is a legal document and these appear on it.
    company_name: str = "Cabmora Media Ltd"
    company_address: str = "Bartle House, Oxford Court, Manchester, M2 3WQ"
    company_phone: str = "+44 77 8010 5876"
    #: Required on business correspondence once the company is registered at
    #: Companies House. Left unset until it is — an invented number is worse
    #: than none.
    company_number: str | None = None
    # Where a bank transfer should land. All unset until Clement provides
    # them: `BankTransferDetails.configured` treats a partial set as none at
    # all, so an invoice never carries half an account or an invented one.
    bank_account_name: str | None = None
    bank_name: str | None = None
    bank_sort_code: str | None = None
    bank_account_number: str | None = None
    bank_iban: str | None = None
    #: The business's Google listing, for the "share this publicly" link shown
    #: after a client rates the work. Unset until somebody supplies it, and
    #: the link simply does not appear until then.
    #:
    #: A link out, never a post. Google does not let anybody submit a review
    #: on somebody else's behalf, so "auto-post the rating to Google" can only
    #: ever mean opening their review form with our listing already chosen —
    #: see `../cabmora-web/docs/PRD.md` and CLAUDE.md §4.2.
    google_place_id: str | None = None
    #: **Only set this when the business is genuinely VAT registered.** The
    #: invoice shows a VAT line if and only if this is present: charging or
    #: displaying VAT without registration is not a formatting error.
    vat_number: str | None = None

    #: Where crashes are reported. Empty means nowhere, which is the default
    #: and is not a failure — the app must run for anyone who has not set one
    #: up. Any Sentry-protocol endpoint works, self-hosted ones included, so
    #: this is not a commitment to a particular vendor's pricing.
    sentry_dsn: str | None = None
    #: Performance tracing is separate from crash reporting and is what makes
    #: these services expensive. Off unless somebody deliberately turns it on.
    sentry_traces_sample_rate: float = 0.0
    #: Stamped on every report so a crash can be traced to the deploy that
    #: introduced it. Railway injects this; locally it is simply absent.
    railway_git_commit_sha: str | None = None

    #: Where an invite link points. The public site, not the API — the customer
    #: lands on a page, not an endpoint.
    public_base_url: str = "http://localhost:5173"
    #: "logging" writes invite links to the log instead of delivering them,
    #: which is fine locally and must not be relied on in production. Set to
    #: "mailtrap" once a token exists; the guard below refuses the combination
    #: of a real backend with no credentials.
    email_backend: str = "logging"
    mailtrap_api_token: str | None = None
    #: The From address. Must be on a domain Mailtrap has verified: two DKIM
    #: CNAMEs, a return-path CNAME and a DMARC TXT on `cabmoramedia.com`. (No
    #: root SPF record is involved — Mailtrap signs from its own return-path
    #: subdomain, so the domain's existing forwarding SPF is untouched.)
    #: `cabmora.com` is not a registered domain and must never appear here.
    #: Until verification completes the only sender that works is Mailtrap's
    #: demo domain, which delivers solely to the account owner.
    mailtrap_sender: str = "hello@cabmoramedia.com"
    mailtrap_sender_name: str = "Cabmora"
    #: Printed in every footer and set as Reply-To. Deliberately not derived
    #: from `mailtrap_sender`: the From address is constrained by what the
    #: provider will let us send as, this one by what mailbox a human reads.
    #: They coincide only once our own domain is verified. Point this at a
    #: monitored mailbox — several emails invite a reply ("tell us if the time
    #: doesn't suit"), and that reply has to land somewhere.
    support_email: str = "hello@cabmoramedia.com"
    #: "r2" hands the browser presigned URLs so bytes never touch the
    #: container. "local" writes to disk and serves through this API —
    #: development only, and refused outside it, because Railway containers are
    #: ephemeral and every upload would vanish on the next deploy.
    #:
    #: Defaults to the production-correct value deliberately. A default the
    #: validator below rejects would mean a deploy that forgets this variable
    #: never boots at all — and it would take the enquiry pipeline down with it.
    media_backend: str = "r2"
    media_root: str = "./var/media"
    r2_account_id: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    #: "eu" for a bucket created with the European Union jurisdiction, which
    #: changes the endpoint host. Empty means the default, unrestricted region.
    #: Getting this wrong produces a signature error, not a 404, so it is worth
    #: reading off the bucket's Settings page rather than guessing.
    r2_jurisdiction: str = ""

    #: From the Stripe dashboard. Both are secrets and belong in the
    #: environment, never in the repository.
    stripe_secret_key: str | None = None
    #: Shown once when the webhook endpoint is created. Without it a callback
    #: cannot be verified, and an unverified callback marks invoices paid.
    stripe_webhook_secret: str | None = None

    #: How often the API sweeps for work nobody is waiting on — previews
    #: still to be made, consultation reminders still to send. Zero turns it
    #: off, for a deployment that runs `scripts.run_scheduled` on a real cron
    #: instead.
    #:
    #: It exists because the cron did not. Previews are generated by a
    #: background task fired after each upload, and a deploy kills whatever is
    #: in flight — so without a sweep a client sits in front of a gallery that
    #: says "preparing" for ever. That has now happened twice.
    sweep_interval_seconds: int = 300

    @property
    def stripe_is_configured(self) -> bool:
        """Both halves, or neither.

        A secret key with no webhook secret is the dangerous combination: card
        payments would start and the callback confirming them could not be
        trusted, so either invoices never settle or they settle on an
        unverified body.
        """
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def media_is_configured(self) -> bool:
        """Whether uploads can actually work.

        Deliberately *not* a boot guard. Missing R2 credentials break uploads,
        which do not exist yet; refusing to start would instead break enquiries,
        bookings and invoices, which carry real money today. A misconfiguration
        should cost you the feature it configures, not the ones it does not.

        `MEDIA_BACKEND=local` outside local development stays fatal, because
        that one fails silently: writes appear to succeed and every photograph
        vanishes on the next deploy.
        """
        if self.media_backend != "r2":
            return True
        return all(
            (self.r2_account_id, self.r2_bucket,
             self.r2_access_key_id, self.r2_secret_access_key)
        )

    @property
    def r2_endpoint(self) -> str:
        """The S3-compatible endpoint, derived rather than pasted.

        The bucket's own Settings page shows this URL with the bucket name
        appended; boto3 wants it without.
        """
        prefix = f"{self.r2_jurisdiction}." if self.r2_jurisdiction else ""
        return f"https://{self.r2_account_id}.{prefix}r2.cloudflarestorage.com"
    #: "manual" records whatever the admin pasted; "google" creates the call in
    #: Cabmora's own calendar and returns its Meet link, so picking a date is
    #: the entire interaction.
    meeting_backend: str = "manual"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    #: Obtained once via `python -m scripts.google_authorize`. This is the
    #: credential: anyone holding it can write to Cabmora's calendar until it
    #: is revoked. It lasts indefinitely *only* while the OAuth consent screen
    #: is published "In production". A token minted while that screen is in
    #: "Testing" expires after seven days, cannot be renewed by the API, and
    #: announces itself solely as a booking that quietly fails to appear.
    google_refresh_token: str | None = None
    #: "primary" is the calendar of whichever account granted consent.
    google_calendar_id: str = "primary"
    #: The year Cabmora started trading, for the homepage's "years" figure.
    #: Unset simply omits it — the alternative is inventing a number about
    #: the company's history, which is what this whole change removes.
    founded_year: int | None = None
    #: Where enquiry notifications go. Without this a lead lands in a table
    #: nobody is watching.
    enquiry_notification_email: str | None = None
    #: The admin console's origin, used to deep-link a notification straight to
    #: the lead. Separate from `public_base_url`: the console is a different app
    #: on its own subdomain. Unset simply omits the link.
    admin_base_url: str | None = None

    # --- Browser session cookie ---
    # The SPA and the API are same-origin in every environment (nginx proxies
    # /api to the API container), so a plain host cookie works with no CORS
    # credentials dance. HttpOnly is the point: script cannot read it, which a
    # localStorage token could not promise.
    session_cookie_name: str = "cabmora_session"
    # Off only where there is no TLS. Browsers treat localhost as a secure
    # context, so local dev over http still works with this left on.
    cookie_secure: bool = True
    # Lax withholds the cookie from cross-site POSTs, which is the CSRF vector
    # that matters here, while still allowing normal inbound links to stay
    # signed in.
    cookie_samesite: str = "lax"


    @field_validator("database_url", mode="after")
    @classmethod
    def _use_async_driver(cls, url: str) -> str:
        """Name the async driver in the scheme, whatever the platform hands us.

        Railway's `DATABASE_URL` is `postgresql://…`. SQLAlchemy reads the
        driver from the scheme, finds none, and falls back to psycopg2 — which
        is not installed and never will be, so the container dies at boot.
        Normalising here means the platform's own variable can be referenced
        verbatim rather than hand-copied into a second one that drifts, and
        `migrations/env.py` gets the same treatment for free because it reads
        this setting rather than alembic.ini.
        """
        if url.startswith("postgresql+"):
            return url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix) :]
        return url

    @model_validator(mode="after")
    def _refuse_insecure_defaults_outside_local(self) -> "Settings":
        """Fail at startup rather than serve forgeable or exposed sessions.

        A boot crash is loud and immediate. The alternative is an API that looks
        perfectly healthy while signing tokens with a key published in the repo
        — at which point HttpOnly buys nothing, because nobody needs to steal a
        session they can mint.
        """
        if self.environment == "local":
            # The one check that belongs on *this* side of the early return.
            # The gateway is chosen by whether keys are present, not by the
            # environment name — deliberately, so staging can take test-mode
            # payments. The cost of that is a live key in a local .env would
            # quietly charge real cards from somebody's laptop.
            if (self.stripe_secret_key or "").startswith(("sk_live", "rk_live")):
                raise ValueError(
                    "STRIPE_SECRET_KEY is a live key and ENVIRONMENT is local. "
                    "Refusing to start: local development would create real "
                    "charges. Use a test key, or leave it empty for the fake "
                    "gateway."
                )
            return self

        if not self.database_url or self.database_url.startswith("sqlite"):
            raise ValueError(
                "DATABASE_URL is unset or still points at SQLite. Refusing to "
                "start: container filesystems are read-only or ephemeral, so "
                "migrations either crash with 'unable to open database file' "
                "or vanish on the next deploy. Point DATABASE_URL at Postgres "
                "(e.g. ${{Postgres.DATABASE_URL}} on Railway)."
            )
        if self.jwt_secret_key == DEFAULT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is still the shipped default — anyone with the "
                "repo could mint an admin token. Set a real secret."
            )
        if self.email_backend == "mailtrap" and not self.mailtrap_api_token:
            raise ValueError(
                "EMAIL_BACKEND=mailtrap but MAILTRAP_API_TOKEN is unset. Refusing "
                "to start: the invite flow would look healthy and deliver nothing."
            )
        if self.stripe_secret_key and not self.stripe_webhook_secret:
            raise ValueError(
                "STRIPE_SECRET_KEY is set but STRIPE_WEBHOOK_SECRET is not. "
                "Refusing to start: checkout would work and the callback "
                "confirming payment could not be verified."
            )
        if self.media_backend == "local":
            raise ValueError(
                "MEDIA_BACKEND=local outside local development serves media "
                "through the API container, which Railway will time out on and "
                "bill egress for twice. Set it to r2."
            )
        if not self.public_base_url or "localhost" in self.public_base_url:
            # Everything the public ever receives is built on this: share
            # links, invite links, and the `og:image` a messaging app fetches
            # when one is pasted. Left on the shipped default, the API is
            # perfectly healthy and every link it hands out points at a
            # machine that only exists on somebody's laptop — which looks
            # like "the preview image is broken" rather than like a missing
            # variable, and has cost a UAT round saying so.
            raise ValueError(
                "PUBLIC_BASE_URL is unset or still points at localhost. "
                "Refusing to start: share links, invite links and link "
                "previews would all be generated against an address nobody "
                "can reach. Set it to the public site, e.g. "
                "https://cabmoramedia.com."
            )
        if not self.public_base_url.startswith("https://"):
            # A messaging app fetching `og:image` over plain HTTP is the
            # other way the preview silently does not appear.
            raise ValueError(
                "PUBLIC_BASE_URL must be an https:// URL outside local "
                "development — link previews are not fetched over plain HTTP."
            )
        if self.meeting_backend == "google" and not all(
            (self.google_client_id, self.google_client_secret, self.google_refresh_token)
        ):
            raise ValueError(
                "MEETING_BACKEND=google needs GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN. Refusing to "
                "start: every booking would fail at the moment an admin makes it."
            )
        if not self.cookie_secure:
            raise ValueError(
                "COOKIE_SECURE=false outside local sends the session cookie in "
                "clear text. Set it to true."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
