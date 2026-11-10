"""The Brevo mailer (comments plan D15, D19), against a recording transport: no
test reaches Brevo."""

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from app.notifications import mailer as mailer_module
from app.notifications.email_content import EmailMessage
from app.notifications.mailer import BrevoMailer, Outcome

KEY = "test-api-key-not-a-real-one"
SENDER = "sender@example.test"
TO = "giver@example.test"
BODY_SECRET = "the-comment-text-sent-to-brevo"
ACCEPTED = {"messageId": "<id@example.test>"}

MESSAGE = EmailMessage(
    subject="A subject",
    html=f"<p>{BODY_SECRET}</p>",
    text=f"{BODY_SECRET}\n",
    headers={
        "List-Unsubscribe": "<https://app.example.test/api/unsubscribe/tok>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    },
)


def mailer_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[BrevoMailer, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    mailer = BrevoMailer(KEY, SENDER, "Wishlist", transport=httpx.MockTransport(record))
    return mailer, requests


def answer(status: int, **kwargs) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, **kwargs)


def raising(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


def test_the_request_is_the_one_brevo_documents():
    mailer, requests = mailer_with(answer(201, json=ACCEPTED))

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.SENT

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == KEY
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "sender": {"name": "Wishlist", "email": SENDER},
        "to": [{"email": TO, "name": "Ana"}],
        "subject": "A subject",
        "htmlContent": MESSAGE.html,
        "textContent": MESSAGE.text,
        "headers": dict(MESSAGE.headers),
    }


@pytest.mark.parametrize("name", ["", " \n"])
def test_an_empty_sender_name_is_left_out(name):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=ACCEPTED)

    mailer = BrevoMailer(KEY, SENDER, name, transport=httpx.MockTransport(record))

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.SENT
    assert json.loads(requests[0].content)["sender"] == {"email": SENDER}


def test_the_timeouts_are_five_seconds_to_connect_and_ten_to_read():
    mailer, requests = mailer_with(answer(201, json=ACCEPTED))

    mailer.send(TO, "Ana", MESSAGE)

    timeout = requests[0].extensions["timeout"]
    assert timeout["connect"] == 5.0
    assert timeout["read"] == 10.0


@pytest.mark.parametrize(
    "status, expected",
    [
        (429, Outcome.RETRY),
        (500, Outcome.RETRY),
        (503, Outcome.RETRY),
        (400, Outcome.REJECTED),
        (401, Outcome.REJECTED),
        (404, Outcome.REJECTED),
    ],
)
def test_a_refusal_is_retried_or_rejected_by_status(status, expected):
    mailer, _ = mailer_with(answer(status, json={"message": "nope"}))

    assert mailer.send(TO, "Ana", MESSAGE) is expected


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("too slow"),
        httpx.PoolTimeout("no connection"),
    ],
)
def test_a_request_that_never_left_is_retried(exc):
    mailer, _ = mailer_with(raising(exc))

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.RETRY


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("no answer"),
        httpx.WriteTimeout("half sent"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("garbled"),
    ],
)
def test_a_request_that_may_have_been_accepted_is_unknown(exc):
    mailer, _ = mailer_with(raising(exc))

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.UNKNOWN


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {}},
        {"json": {"messageId": ""}},
        {"json": {"messageId": 7}},
        {"json": ["<id@example.test>"]},
        {"content": b"not json"},
        {"content": b""},
        {"content": b"[" * 100_000},
        {"json": {"messageId": "x" * (mailer_module.MAX_RESPONSE_BYTES + 1)}},
    ],
)
@pytest.mark.parametrize("status", [200, 201])
def test_an_unexpected_success_body_is_unknown(status, kwargs):
    mailer, _ = mailer_with(answer(status, **kwargs))

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.UNKNOWN


def test_a_redirect_is_not_followed_and_is_unknown():
    mailer, requests = mailer_with(
        answer(302, headers={"location": "https://elsewhere.example.test/"})
    )

    assert mailer.send(TO, "Ana", MESSAGE) is Outcome.UNKNOWN
    assert len(requests) == 1


def test_no_header_can_be_smuggled_through_a_name():
    mailer, requests = mailer_with(answer(201, json=ACCEPTED))
    message = EmailMessage(
        subject="Hi\r\nBcc: victim@example.test",
        html="",
        text="",
        headers={},
    )

    mailer.send(TO, "Ana\r\nBcc: victim@example.test X-Evil: 1", message)

    payload = json.loads(requests[0].content)
    assert payload["to"][0]["name"] == "Ana Bcc: victim@example.test X-Evil: 1"
    assert payload["subject"] == "Hi Bcc: victim@example.test"


def test_a_recipient_with_no_name_is_sent_without_one():
    mailer, requests = mailer_with(answer(201, json=ACCEPTED))

    mailer.send(TO, " \r\n", MESSAGE)

    assert json.loads(requests[0].content)["to"] == [{"email": TO}]


@pytest.mark.parametrize(
    "handler, expected",
    [
        (answer(400, json={"message": f"{TO} {KEY} {BODY_SECRET}"}), Outcome.REJECTED),
        (answer(503, text=f"{TO} {KEY} {BODY_SECRET}"), Outcome.RETRY),
        (answer(201, text=f"{TO} {KEY} {BODY_SECRET}"), Outcome.UNKNOWN),
        (raising(httpx.ConnectError(f"{TO} {KEY} {BODY_SECRET}")), Outcome.RETRY),
        (raising(httpx.ReadTimeout(f"{TO} {KEY} {BODY_SECRET}")), Outcome.UNKNOWN),
    ],
)
def test_no_key_address_or_body_reaches_a_log_line(handler, expected, caplog):
    mailer, _ = mailer_with(handler)

    with caplog.at_level(logging.DEBUG):
        outcome = mailer.send(TO, "Ana Name", MESSAGE)

    assert outcome is expected
    assert caplog.records  # a failure is logged, by outcome and reason
    logged = caplog.text + repr([record.__dict__ for record in caplog.records])
    for secret in (KEY, TO, SENDER, "Ana Name", BODY_SECRET):
        assert secret not in logged


def test_the_mailer_does_not_show_its_key():
    mailer, _ = mailer_with(answer(201, json=ACCEPTED))

    assert KEY not in repr(mailer)
