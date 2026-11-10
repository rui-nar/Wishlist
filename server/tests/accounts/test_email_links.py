"""Addresses and the tokens of email links (sign-in plan D4, D7)."""

import base64
import hashlib
import hmac
import uuid

import pytest

from app.accounts import email_links
from app.notifications import unsubscribe

SECRET = "a-test-secret"


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("ada@example.com", "ada@example.com"),
        ("  Ada@Example.COM\n", "ada@example.com"),
        # Nothing provider-specific.
        ("a.d.a+tag@gmail.com", "a.d.a+tag@gmail.com"),
        ("a" * 242 + "@example.com", "a" * 242 + "@example.com"),
    ],
)
def test_a_valid_address_is_normalised(typed, stored):
    assert email_links.normalise(typed) == stored


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "no-at-sign",
        "@example.com",
        "ada@",
        "a@b@example.com",
        "ada lovelace@example.com",
        "ada@exam\tple.com",
        "ada\x00@example.com",
        "ada\x7f@example.com",
        "ada\x85@example.com",
        "ada\n@example.com",
        "a" * 243 + "@example.com",
    ],
)
def test_an_invalid_address_is_refused(typed):
    assert email_links.normalise(typed) is None


def test_a_token_reads_back_as_its_link():
    link = uuid.uuid4()

    assert email_links.read_token(SECRET, email_links.make_token(SECRET, link)) == link


def test_a_token_is_url_safe_and_carries_no_padding():
    token = email_links.make_token(SECRET, uuid.uuid4())

    assert set(token) <= set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    )


def _signed(prefix: str, link: uuid.UUID) -> str:
    def encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signature = hmac.new(
        SECRET.encode(), f"{prefix}{link}".encode(), hashlib.sha256
    ).digest()
    return f"{encode(link.bytes)}.{encode(signature)}"


def test_the_signature_is_the_plans():
    # The worker and the route build and read it apart: its form is a contract
    # with every link in an inbox (D7).
    link = uuid.uuid4()

    assert email_links.make_token(SECRET, link) == _signed("email-link:", link)


def test_a_token_for_another_row_is_refused():
    first, second = uuid.uuid4(), uuid.uuid4()
    first_token = email_links.make_token(SECRET, first)
    second_token = email_links.make_token(SECRET, second)

    swapped = f"{first_token.split('.')[0]}.{second_token.split('.')[1]}"

    assert email_links.read_token(SECRET, swapped) is None


def test_a_token_signed_for_unsubscribing_is_refused():
    link = uuid.uuid4()

    assert email_links.read_token(SECRET, _signed("unsubscribe:v1:", link)) is None


def test_an_unsubscribe_token_is_refused():
    token = unsubscribe.make_token(SECRET, uuid.uuid4())

    assert email_links.read_token(SECRET, token) is None


def test_an_email_link_token_does_not_unsubscribe():
    token = email_links.make_token(SECRET, uuid.uuid4())

    assert unsubscribe.read_token(SECRET, token) is None


def test_a_token_made_with_another_secret_is_refused():
    token = email_links.make_token("another-secret", uuid.uuid4())

    assert email_links.read_token(SECRET, token) is None


def test_no_token_is_accepted_without_a_secret():
    token = email_links.make_token("", uuid.uuid4())

    assert email_links.read_token("", token) is None


def test_the_unused_bits_of_a_token_cannot_be_changed():
    # 16 bytes leave 4 unused bits in the id's last character.
    link = uuid.UUID(bytes=bytes(16))
    identifier, signature = email_links.make_token(SECRET, link).split(".")
    assert identifier[-1] == "A"

    assert email_links.read_token(SECRET, f"{identifier[:-1]}B.{signature}") is None


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-token",
        "a.b",
        "é" * 22 + "." + "é" * 43,
    ],
)
def test_a_malformed_token_is_refused(token):
    assert email_links.read_token(SECRET, token) is None
