"""Turn an intent plus its data into a subject, an HTML part and a text part.

Infrastructure, not application: the port's contract is that a use case says
*what happened* and never composes copy. This is where the copy lives, so a
wording change is a template edit and touches nothing else.

Jinja2 rather than str.format, for one reason that matters: autoescaping. A
customer's first name reaches these templates unfiltered, and `O'Brien` or a
name containing `<` would otherwise either break the markup or inject it.

Every message carries a plain-text alternative. Not politeness — an HTML-only
message scores badly with spam filters, and the invite link has to remain
usable in a text-only client.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from app.core.display import DISPLAY_TZ
from app.domain.services.invoice_renderer import BankTransferDetails

from app.domain.entities.invite import DEFAULT_TTL
from app.domain.entities.password_reset import DEFAULT_TTL as RESET_TTL


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("app.infrastructure.email", "templates"),
        # `.txt` is deliberately excluded: escaping HTML entities into a plain
        # text part would render `&amp;` to the reader.
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
        # A missing variable must fail loudly here rather than silently send an
        # email with a hole where the name or the link should be.
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


_env = _environment()


def render_invite(
    *, first_name: str, invite_url: str, support_email: str
) -> RenderedEmail:
    """The 'an account was created for you, set a password' message.

    `expires_in_days` is read from the domain's `DEFAULT_TTL` so the copy cannot
    drift from the code. It is a known limitation that `EmailSender.send_invite`
    does not carry the token's real `expires_at` — a caller passing a custom TTL
    would make this sentence wrong. Adding `expires_at` to the port is the fix
    when a second TTL actually exists.
    """
    context = {
        "subject": "Your Cabmora account is ready",
        "preheader": "Set your password and follow your project from start to delivery.",
        "first_name": first_name,
        "invite_url": invite_url,
        "expires_in_days": DEFAULT_TTL.days,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("invite.html").render(context),
        text=_env.get_template("invite.txt").render(context),
    )


def render_password_reset(
    *, first_name: str, reset_url: str, support_email: str
) -> RenderedEmail:
    """The 'you asked to reset your password' message.

    The subject says what it is without saying who it is for: a preview line
    on a lock screen should not announce that this address has a Cabmora
    account to whoever is holding the phone.

    `expires_in_hours` is read from the domain's TTL so the copy cannot drift
    from the code, with the same limitation noted on `render_invite`.
    """
    context = {
        "subject": "Reset your Cabmora password",
        "preheader": "Choose a new password. The link expires in an hour.",
        "first_name": first_name,
        "reset_url": reset_url,
        "expires_in_hours": int(RESET_TTL.total_seconds() // 3600),
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("password_reset.html").render(context),
        text=_env.get_template("password_reset.txt").render(context),
    )


def render_gallery_ready(
    *,
    first_name: str,
    project_title: str,
    photo_count: int,
    gallery_url: str,
    support_email: str,
    note: str | None = None,
    hands_over_originals: bool = False,
) -> RenderedEmail:
    """The 'your photographs are waiting' message.

    `note` is set in the console when the photographs are shared and appears
    above the gallery button, attributed to Cabmora rather than dropped into
    the standard copy — a client should be able to tell what a person wrote
    from what the system always says. Autoescaped like every other value here,
    which is the reason these templates are Jinja2 and not str.format.
    """
    context = {
        "subject": f"Your photographs from {project_title} are ready",
        "preheader": "Look through them, comment, and ask for any changes.",
        "first_name": first_name,
        "project_title": project_title,
        "photo_count": photo_count,
        "gallery_url": gallery_url,
        "note": note,
        "hands_over_originals": hands_over_originals,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("gallery_ready.html").render(context),
        text=_env.get_template("gallery_ready.txt").render(context),
    )


def render_project_message(
    *,
    recipient_first_name: str,
    from_name: str,
    project_title: str,
    body: str,
    url: str,
    about_a_photograph: bool,
    support_email: str,
) -> RenderedEmail:
    """The 'somebody wrote to you' message, in either direction."""
    context = {
        "subject": f"{from_name} wrote about {project_title}",
        "preheader": body[:140],
        "first_name": recipient_first_name,
        "from_name": from_name,
        "project_title": project_title,
        "body": body,
        "url": url,
        "about_a_photograph": about_a_photograph,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("project_message.html").render(context),
        text=_env.get_template("project_message.txt").render(context),
    )


def render_amendment_resolved(
    *,
    first_name: str,
    project_title: str,
    request: str,
    gallery_url: str,
    support_email: str,
) -> RenderedEmail:
    """The 'the change you asked for has been made' message.

    The client's own words are quoted back. Weeks can pass between asking and
    hearing, and "your amendment has been resolved" tells somebody nothing
    about which of the four things they mentioned.
    """
    context = {
        "subject": f"Your change to {project_title} is done",
        "preheader": "Take a look and tell us if it is what you had in mind.",
        "first_name": first_name,
        "project_title": project_title,
        "request": request,
        "gallery_url": gallery_url,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("amendment_resolved.html").render(context),
        text=_env.get_template("amendment_resolved.txt").render(context),
    )


def render_invoice_issued(
    *,
    first_name: str,
    project_title: str,
    number: str,
    amount: str,
    due_at: datetime,
    invoice_url: str,
    support_email: str,
    bank: "BankTransferDetails | None" = None,
) -> RenderedEmail:
    """The 'here is your invoice' message.

    The amount and the date are in the body rather than only behind a link:
    somebody deciding whether to deal with this now should not have to sign
    in to find out what it is for and when it is due.

    The account goes in the body for the same reason. It is on the attached
    PDF, but plenty of people never open the attachment, and "how do I
    actually pay this" should not need a second email to answer.
    """
    context = {
        "subject": f"Invoice {number} from Cabmora Media",
        "preheader": f"{amount} due by {due_at.astimezone(DISPLAY_TZ):%-d %B %Y}.",
        "first_name": first_name,
        "project_title": project_title,
        "number": number,
        "amount": amount,
        "bank": bank,
        "due_date": f"{due_at.astimezone(DISPLAY_TZ):%-d %B %Y}",
        "invoice_url": invoice_url,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("invoice_issued.html").render(context),
        text=_env.get_template("invoice_issued.txt").render(context),
    )


def render_creator_application_received(
    *, first_name: str, studio_name: str, support_email: str
) -> RenderedEmail:
    """The 'we have your application' acknowledgement."""
    context = {
        "subject": "We've received your Cabmora Flow application",
        "preheader": "Someone will review it within two working days.",
        "first_name": first_name,
        "studio_name": studio_name,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("creator_application_received.html").render(context),
        text=_env.get_template("creator_application_received.txt").render(context),
    )


def render_creator_approved(
    *, first_name: str, studio_name: str, setup_url: str, support_email: str
) -> RenderedEmail:
    """The 'you're in — set a password' message."""
    context = {
        "subject": f"{studio_name} has been approved for Cabmora Flow",
        "preheader": "Choose a password and your studio workspace is ready.",
        "first_name": first_name,
        "studio_name": studio_name,
        "setup_url": setup_url,
        "expires_in_days": DEFAULT_TTL.days,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("creator_approved.html").render(context),
        text=_env.get_template("creator_approved.txt").render(context),
    )


def render_creator_declined(
    *, first_name: str, studio_name: str, support_email: str
) -> RenderedEmail:
    """The 'not this time' message.

    The subject deliberately does not say "rejected". Somebody scanning an
    inbox should be able to open this in their own time rather than reading
    the verdict off a lock screen.
    """
    context = {
        "subject": "Your Cabmora Flow application",
        "preheader": "An update on your application.",
        "first_name": first_name,
        "studio_name": studio_name,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("creator_declined.html").render(context),
        text=_env.get_template("creator_declined.txt").render(context),
    )


def render_consultation_reminder(
    *,
    first_name: str,
    with_name: str,
    starts_at: datetime,
    duration_minutes: int,
    meeting_url: str | None,
    support_email: str,
    now: datetime | None = None,
) -> RenderedEmail:
    """'Your call is in N minutes.'

    `minutes_away` is computed rather than hard-coded to the cron's lead time: a
    run that fires late would otherwise say "in 30 minutes" about a call in
    twelve, and the reader would trust the sentence over the clock.
    """
    moment = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    minutes_away = max(1, round((moment - reference).total_seconds() / 60))
    local = moment.astimezone(DISPLAY_TZ)

    context = {
        "subject": f"Your Cabmora call starts in {minutes_away} minutes",
        "preheader": f"{local.strftime('%-I:%M %p').lower()} with {with_name}.",
        "first_name": first_name,
        "with_name": with_name,
        "minutes_away": minutes_away,
        "when": local.strftime("%A %-d %B, %-I:%M %p").replace("AM", "am").replace("PM", "pm"),
        "duration_minutes": duration_minutes,
        "meeting_url": meeting_url,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("reminder.html").render(context),
        text=_env.get_template("reminder.txt").render(context),
    )


def _first_name(full_name: str) -> str:
    """The part a greeting should use. Falls back rather than greeting nobody.

    Capitalised, because people type their name into a form however they like
    and "Thank you, clement." went out to a real person. Only the first letter
    is touched and the rest is left as typed, so "McDonald" and "O'Brien"
    survive — lower-casing first would flatten them.
    """
    parts = full_name.strip().split()
    if not parts:
        return "there"
    first = parts[0]
    return first[0].upper() + first[1:]


def render_consultation_booked(
    *,
    name: str,
    starts_at: datetime,
    duration_minutes: int,
    meeting_url: str | None,
    support_email: str,
) -> RenderedEmail:
    """'Your call is booked for <when>.'

    The subject carries the day and time rather than the word "confirmed", so
    the slot is checkable from a notification without opening anything — which
    is the whole point of sending this at booking time instead of leaving the
    reminder to break the news.
    """
    moment = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
    local = moment.astimezone(DISPLAY_TZ)
    when = local.strftime("%A %-d %B, %-I:%M %p").replace("AM", "am").replace("PM", "pm")

    context = {
        "subject": f"Your Cabmora call is booked — {when}",
        "preheader": "Reply if the time doesn't suit and we'll move it.",
        "first_name": _first_name(name),
        "day": local.strftime("%A %-d %B"),
        "when": when,
        "duration_minutes": duration_minutes,
        "meeting_url": meeting_url,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("consultation_booked.html").render(context),
        text=_env.get_template("consultation_booked.txt").render(context),
    )


def render_enquiry_received(
    *,
    name: str,
    email: str,
    phone: str | None,
    event_type: str,
    event_date: datetime | None,
    message: str,
    admin_url: str | None,
    support_email: str,
) -> RenderedEmail:
    """The internal 'a lead arrived' notification."""
    local_date = None
    if event_date is not None:
        moment = (
            event_date
            if event_date.tzinfo
            else event_date.replace(tzinfo=timezone.utc)
        ).astimezone(DISPLAY_TZ)
        local_date = moment.strftime("%A %-d %B %Y")

    context = {
        # The subject carries the name and type so a phone lock screen is enough
        # to triage it.
        "subject": f"New enquiry — {name} ({event_type})",
        "preheader": f"{email}{' · ' + phone if phone else ''}",
        "name": name,
        "email": email,
        "phone": phone,
        "event_type": event_type,
        "event_date": local_date,
        "message": message,
        "admin_url": admin_url,
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("enquiry_received.html").render(context),
        text=_env.get_template("enquiry_received.txt").render(context),
    )


def render_enquiry_acknowledgement(
    *, name: str, event_type: str, support_email: str
) -> RenderedEmail:
    """The 'we have it' reply to whoever filled in the form.

    The wording is Cabmora's own, supplied 2026-09-30. `event_type` is no
    longer read: their copy says "your consultation request" for every enquiry
    rather than naming the event back, so the parameter stays for the callers
    that pass it and is deliberately unused.
    """
    context = {
        "subject": "We've received your enquiry — Cabmora",
        "preheader": "Someone will be in touch within one working day.",
        "first_name": _first_name(name),
        "support_email": support_email,
    }
    return RenderedEmail(
        subject=context["subject"],
        html=_env.get_template("enquiry_ack.html").render(context),
        text=_env.get_template("enquiry_ack.txt").render(context),
    )
