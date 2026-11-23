"""The Mailtrap adapter, against a stubbed transport.

No network, no token, no account: the point of the port is that delivery can be
verified without any of them.
"""

import httpx
import pytest

from app.infrastructure.email.mailtrap_email_sender import (
    SEND_URL,
    MailtrapEmailSender,
)


def _sender(handler) -> MailtrapEmailSender:
    return MailtrapEmailSender(
        api_token="test-token",
        sender_email="hello@cabmoramedia.com",
        sender_name="Cabmora",
        support_email="hello@cabmoramedia.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.anyio
async def test_an_invite_is_posted_with_both_parts(client):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("Api-Token")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    await _sender(handler).send_invite(
        to="sofia@example.com", first_name="Sofia", invite_url="https://x.test/accept?token=abc"
    )

    assert seen["url"] == SEND_URL, "must be the Sending API, not the Testing sandbox"
    assert seen["token"] == "test-token"
    body = seen["body"]
    assert body["to"] == [{"email": "sofia@example.com"}]
    assert body["from"] == {"email": "hello@cabmoramedia.com", "name": "Cabmora"}
    assert "Sofia" in body["html"] and "Sofia" in body["text"]
    assert "https://x.test/accept?token=abc" in body["html"]
    # A text part is not politeness: HTML-only scores badly with spam filters
    # and the link must survive a text-only client.
    assert body["text"].strip()


@pytest.mark.anyio
async def test_a_rejection_is_logged_not_raised(client, caplog):
    """The account already exists by now. Raising would fail a request whose
    side effects have happened."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized: bad token")

    with caplog.at_level("ERROR"):
        await _sender(handler).send_invite(
            to="sofia@example.com", first_name="Sofia", invite_url="https://x.test/accept?token=abc"
        )

    logged = caplog.text
    assert "401" in logged
    assert "Unauthorized: bad token" in logged, "Mailtrap's reason must reach the log"
    assert "https://x.test/accept?token=abc" in logged, "the link must stay recoverable"


@pytest.mark.anyio
async def test_a_network_failure_is_also_survivable(client, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with caplog.at_level("ERROR"):
        await _sender(handler).send_invite(
            to="sofia@example.com", first_name="Sofia", invite_url="https://x.test/accept?token=abc"
        )
    assert "https://x.test/accept?token=abc" in caplog.text


@pytest.mark.anyio
async def test_html_is_escaped_in_the_delivered_body(client):
    """Autoescaping holds through the adapter, not just the renderer."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    await _sender(handler).send_invite(
        to="x@example.com",
        first_name="<script>alert(1)</script>",
        invite_url="https://x.test/a?b=c&d=e",
    )
    assert "<script>" not in seen["body"]["html"]
    assert "&lt;script&gt;" in seen["body"]["html"]
    assert "&amp;" in seen["body"]["html"], "the ampersand in the link must be escaped"
