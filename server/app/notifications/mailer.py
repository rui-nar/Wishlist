"""Hands one email to Brevo, and says what became of it (comments plan D15, D19).

One fixed host and a secret key. An answer can be slow, wrong or hostile, so it
is reduced to an outcome: no key, address, body or httpx message goes into a log
line or leaves here. The app holds one mailer in `app.state.mailer`; tests
replace it with a fake or give this one a recording transport, so none reaches
Brevo.
"""

import enum
import json
import logging

import httpx

from app.notifications.email_content import EmailMessage, single_line

_log = logging.getLogger(__name__)

URL = "https://api.brevo.com/v3/smtp/email"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
# A real acceptance is a few dozen bytes.
MAX_RESPONSE_BYTES = 64 * 1024

# The request cannot have reached Brevo. Any other transport error may have
# come after it was accepted: a duplicate is worse than a missing email (D15).
_NOT_DELIVERED = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class Outcome(enum.StrEnum):
    SENT = "sent"
    # Refused before acceptance: send it again later.
    RETRY = "retry"
    # Maybe accepted, maybe not: never send it again.
    UNKNOWN = "unknown"
    # Refused for good: a bad address or a bad key.
    REJECTED = "rejected"


class BrevoMailer:
    """Constructed once. A client per message: at most 50 per worker run, and
    no connection pool to close at shutdown."""

    def __init__(
        self,
        api_key: str,
        sender_address: str,
        sender_name: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._sender = {"email": single_line(sender_address)}
        name = single_line(sender_name)
        if name:
            self._sender["name"] = name
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=READ_TIMEOUT,
            pool=CONNECT_TIMEOUT,
        )

    def send(self, to_address: str, to_name: str, message: EmailMessage) -> Outcome:
        recipient = {"email": single_line(to_address)}
        name = single_line(to_name)
        if name:
            recipient["name"] = name
        payload = {
            "sender": self._sender,
            "to": [recipient],
            "subject": single_line(message.subject),
            "htmlContent": message.html,
            "textContent": message.text,
            "headers": dict(message.headers),
        }
        outcome, reason = self._post(payload)
        if outcome is not Outcome.SENT:
            _log.warning("brevo: outcome=%s reason=%s", outcome.value, reason)
        return outcome

    def _post(self, payload: dict) -> tuple[Outcome, str]:
        try:
            # trust_env=False: no proxy or CA bundle from the environment.
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST",
                    URL,
                    json=payload,
                    headers={
                        "api-key": self._api_key,
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    return _classified(response)
        except _NOT_DELIVERED as exc:
            return Outcome.RETRY, f"transport:{type(exc).__name__}"
        except httpx.HTTPError as exc:
            return Outcome.UNKNOWN, f"transport:{type(exc).__name__}"


def _classified(response: httpx.Response) -> tuple[Outcome, str]:
    status = response.status_code
    if 200 <= status < 300:
        if _has_message_id(response):
            return Outcome.SENT, "accepted"
        return Outcome.UNKNOWN, "unexpected_body"
    if status == 429 or status >= 500:
        return Outcome.RETRY, f"status:{status}"
    if 400 <= status < 500:
        return Outcome.REJECTED, f"status:{status}"
    return Outcome.UNKNOWN, f"status:{status}"  # a redirect, not followed


def _has_message_id(response: httpx.Response) -> bool:
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            return False
    try:
        data = json.loads(bytes(body))
    except ValueError, RecursionError:
        return False
    return (
        isinstance(data, dict)
        and isinstance(data.get("messageId"), str)
        and bool(data["messageId"])
    )
