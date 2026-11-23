"""What a messaging app sees when somebody pastes a gallery link.

Mounted at the **root**, not under `/api/v1`: the thing being unfurled is the
share URL itself, `https://cabmoramedia.com/s/<token>`, and a crawler asks for
exactly that. nginx proxies `/s/` here; see apps/web/nginx.conf.template.

A person who follows the link is sent on to the single-page app, which renders
the gallery as it always did. A crawler does not follow redirects for Open
Graph, reads the tags, and stops.
"""

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import get_share_preview
from app.application.use_cases.sharing.share_preview import GetSharePreview
from app.core.config import get_settings

router = APIRouter(tags=["sharing"])

#: Where a human is sent. A different path from `/s/` on purpose: nginx routes
#: `/s/` here, so sending them back to it would loop.
APP_PATH = "/gallery"


@router.get("/s/{token}/cover")
async def share_cover(
    token: str,
    use_case: Annotated[GetSharePreview, Depends(get_share_preview)],
) -> Response:
    """Redirect to the cover photograph, signing it afresh each time.

    The meta tag has to carry a stable URL — a crawler may come back hours
    later, and a signed R2 link baked into the HTML would be expired by then.
    This path never changes; the signature behind it is minted per request.
    """
    preview = await use_case.execute(token)
    if preview is None or not preview.cover_url:
        # 404 rather than a placeholder: an unfurl with no image falls back to
        # the site's own, which is the right outcome for a gallery holding
        # nothing anybody may see.
        return Response(status_code=404)
    # 302, not 301. The target is a signed URL that expires; a permanent
    # redirect would be cached by somebody's proxy long after it stopped
    # working.
    return RedirectResponse(preview.cover_url, status_code=302)


@router.get("/s/{token}", response_class=HTMLResponse)
async def share_landing(
    token: str,
    use_case: Annotated[GetSharePreview, Depends(get_share_preview)],
) -> HTMLResponse:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    preview = await use_case.execute(token)

    onward = f"{base}{APP_PATH}/{escape(token, quote=True)}"

    if preview is None:
        # A dead or revoked link still has to go somewhere a person can read.
        # The app says "this link is no longer available"; no tags are emitted,
        # so nothing about a withdrawn gallery leaks into a chat thread.
        return HTMLResponse(_document(title="Cabmora Media", onward=onward))

    title = f"{preview.project_title} — Cabmora Media"
    description = (
        f"{preview.event_type} photographs from Cabmora Media. "
        "Open the gallery to see them all."
    )
    cover = f"{base}/s/{escape(token, quote=True)}/cover" if preview.cover_url else None

    return HTMLResponse(
        _document(
            title=title,
            description=description,
            image=cover,
            image_type=preview.cover_content_type,
            canonical=f"{base}/s/{escape(token, quote=True)}",
            onward=onward,
        )
    )


def _document(
    *,
    title: str,
    description: str = "A private gallery from Cabmora Media.",
    image: str | None = None,
    image_type: str | None = None,
    canonical: str | None = None,
    onward: str,
) -> str:
    """The smallest page that satisfies an unfurl and forwards a person.

    Everything interpolated is escaped. A project title is typed by staff
    rather than by the public, but it reaches this document unescaped from the
    database otherwise, and "our own people type it" is not a security model.
    """
    tags = [
        f'<title>{escape(title)}</title>',
        f'<meta name="description" content="{escape(description, quote=True)}" />',
        f'<meta property="og:title" content="{escape(title, quote=True)}" />',
        f'<meta property="og:description" content="{escape(description, quote=True)}" />',
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="Cabmora Media" />',
    ]
    # `og:url` is the link that was pasted, not where the reader ends up. An
    # unfurler uses it to key its cache; pointing it at the onward path would
    # have it cache the app shell against this address instead.
    if canonical:
        tags.append(f'<meta property="og:url" content="{escape(canonical, quote=True)}" />')
    if image:
        tags += [
            f'<meta property="og:image" content="{escape(image, quote=True)}" />',
            # Same URL, declared twice. WhatsApp and iMessage read
            # `og:image:secure_url` in preference, and a card that renders in
            # one app and not another is almost always a missing variant
            # rather than a missing image.
            f'<meta property="og:image:secure_url" content="{escape(image, quote=True)}" />',
            '<meta property="og:image:alt" content="A photograph from this gallery" />',
            '<meta name="twitter:card" content="summary_large_image" />',
            f'<meta name="twitter:image" content="{escape(image, quote=True)}" />',
        ]
        if image_type:
            tags.append(
                f'<meta property="og:image:type" content="{escape(image_type, quote=True)}" />'
            )
    else:
        tags.append('<meta name="twitter:card" content="summary" />')

    # `noindex`: a private gallery must never reach a search result. The unfurl
    # still works — a messaging app reads Open Graph and does not obey robots
    # directives the way a search crawler does.
    tags.append('<meta name="robots" content="noindex, nofollow" />')

    safe_onward = escape(onward, quote=True)
    return (
        "<!doctype html>\n<html lang=\"en-GB\">\n<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        + "\n".join(tags)
        + f'\n<meta http-equiv="refresh" content="0; url={safe_onward}" />\n'
        "</head>\n<body>\n"
        f'<p>Opening your gallery. <a href="{safe_onward}">Continue</a>.</p>\n'
        # The meta refresh carries browsers with JavaScript disabled; this
        # makes it instant for everybody else and leaves no history entry to
        # bounce back through.
        f'<script>location.replace({_js(safe_onward)});</script>\n'
        "</body>\n</html>\n"
    )


def _js(value: str) -> str:
    """A JavaScript string literal that cannot break out of its quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\u003c") + '"'
