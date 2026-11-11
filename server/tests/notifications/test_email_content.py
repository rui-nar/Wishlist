"""What an email says (comments plan D15, D17, D18).

The golden files under emails/ hold each kind of item in each language. After
an intended change, regenerate them by running this file with
UPDATE_EMAIL_GOLDENS=1, and read the diff.
"""

import os
import re
import string
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from app.lists.router import _NOTIFIED_FIELDS
from app.notifications.email_content import (
    _EN,
    _FIELD_LABELS,
    _FR,
    Comment,
    Digest,
    EmailMessage,
    build_links,
    render,
    render_sign_in_link,
)

GOLDEN_DIR = Path(__file__).parent / "emails"
BASE = "https://app.example.test"
OCCASION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
GIFT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
TOKEN = "v1.dXNlcg.c2lnbmF0dXJl"
LINKS = build_links(BASE, OCCASION_ID, GIFT_ID, TOKEN)
XSS = '<script>alert("x")</script>'
ESCAPED_XSS = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"

BASE_DIGEST = Digest(
    recipient_name="Ana",
    language="en",
    occasion_name="Birthday 2026",
    gift_title="Blue scarf",
    links=LINKS,
)

ITEMS = {
    "fields_changed": {
        "fields_changed": ("title", "price_amount", "price_currency", "image_id"),
    },
    "comments": {
        "comments": (
            Comment("Bob", "I'll take the blue one.\nOK?"),
            Comment(None, "Who has the receipt?"),
        ),
    },
    "participants_left": {"participants_left": ("Carol", None)},
    "gift_deleted": {"gift_deleted": True},
    "hidden_gift_removed": {"hidden_gift_removed": True},
    "all_of_it": {
        "fields_changed": ("description", "links"),
        "comments": (Comment("Bob", "Noted."),),
        "participants_left": ("Carol",),
    },
}


def golden(message: EmailMessage) -> str:
    headers = "".join(f"{name}: {value}\n" for name, value in message.headers.items())
    return (
        f"Subject: {message.subject}\n{headers}\n"
        f"=== text ===\n{message.text}\n=== html ===\n{message.html}"
    )


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("kind", ITEMS)
def test_each_item_kind_in_each_language_matches_its_golden(kind, language):
    digest = replace(BASE_DIGEST, language=language, **ITEMS[kind])
    rendered = golden(render(digest))
    path = GOLDEN_DIR / f"{kind}.{language}.txt"

    if os.environ.get("UPDATE_EMAIL_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")

    assert rendered == path.read_text(encoding="utf-8")


def test_the_two_languages_have_the_same_keys_and_placeholders():
    def placeholders(text: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    assert _EN.keys() == _FR.keys()
    for key in _EN:
        assert placeholders(_EN[key]) == placeholders(_FR[key]), key


def test_every_field_that_notifies_has_a_label():
    assert set(_FIELD_LABELS) == set(_NOTIFIED_FIELDS)


def test_links_are_built_on_the_public_url_and_match_the_client_routes():
    links = build_links(BASE + "/", OCCASION_ID, GIFT_ID, TOKEN)

    assert links.gift == f"{BASE}/shared/{OCCASION_ID}?gift={GIFT_ID}"
    assert links.occasion == f"{BASE}/shared/{OCCASION_ID}"
    assert links.account == f"{BASE}/account"
    assert links.unsubscribe_page == f"{BASE}/unsubscribe#{TOKEN}"
    assert links.unsubscribe_one_click == f"{BASE}/api/unsubscribe/{TOKEN}"


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_unsubscribe_headers_and_link_are_on_every_kind(language):
    for kind in ITEMS:
        message = render(replace(BASE_DIGEST, language=language, **ITEMS[kind]))

        assert message.headers == {
            "List-Unsubscribe": f"<{BASE}/api/unsubscribe/{TOKEN}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        assert f"{BASE}/unsubscribe#{TOKEN}" in message.html
        assert f"{BASE}/unsubscribe#{TOKEN}" in message.text
        assert f"{BASE}/account" in message.text


def every_value_hostile(language: str = "en") -> Digest:
    return replace(
        BASE_DIGEST,
        language=language,
        recipient_name=XSS,
        occasion_name=XSS,
        gift_title=XSS,
        comments=(Comment(XSS, XSS),),
        participants_left=(XSS,),
    )


def test_every_user_value_is_escaped_in_the_html():
    message = render(every_value_hostile())

    assert "<script" not in message.html
    # recipient, title tag, intro, comment author and body, who left
    assert message.html.count(ESCAPED_XSS) >= 6


def test_a_script_in_a_comment_is_escaped():
    message = render(replace(BASE_DIGEST, comments=(Comment("Bob", XSS),)))

    assert "<script" not in message.html
    assert ESCAPED_XSS in message.html
    assert XSS in message.text


@pytest.mark.parametrize("flag", ["gift_deleted", "hidden_gift_removed", None])
def test_a_script_in_a_gift_title_is_escaped(flag):
    items = {flag: True} if flag else {}
    message = render(replace(BASE_DIGEST, gift_title=XSS, **items))

    assert "<script" not in message.html
    assert ESCAPED_XSS in message.html


def test_a_quote_cannot_leave_an_attribute():
    links = build_links(
        'https://x.example.test/"onmouseover="y', OCCASION_ID, GIFT_ID, TOKEN
    )
    message = render(replace(BASE_DIGEST, links=links))

    assert '"onmouseover' not in message.html
    assert "&quot;onmouseover" in message.html


def test_braces_in_a_value_are_not_a_template():
    message = render(
        replace(BASE_DIGEST, gift_title="{occasion}", recipient_name="{0}")
    )

    assert "“{occasion}”" in message.text
    assert "Hello {0}," in message.text


@pytest.mark.parametrize("flag", ["gift_deleted", "hidden_gift_removed", None])
@pytest.mark.parametrize("breaker", ["\r\n", "\n", "\r", "\x85", " ", " "])
def test_a_title_cannot_add_a_header_line(flag, breaker):
    items = {flag: True} if flag else {}
    title = f"Gift{breaker}Bcc: victim@example.test"
    message = render(replace(BASE_DIGEST, gift_title=title, **items))

    assert not re.search(r"[\r\n\x85  ]", message.subject)
    assert "Gift Bcc: victim@example.test" in message.subject


def test_an_occasion_cannot_add_a_header_line():
    message = render(replace(BASE_DIGEST, occasion_name="Party\r\nBcc: a@example.test"))

    assert "\r" not in message.subject and "\n" not in message.subject


def test_a_name_stays_on_its_line_in_the_text_part():
    message = render(
        replace(
            BASE_DIGEST,
            recipient_name="Ana\nFake paragraph",
            participants_left=("Carol\nMore",),
        )
    )

    assert "Hello Ana Fake paragraph," in message.text
    assert "Carol More left" in message.text


@pytest.mark.parametrize(
    "language, wording",
    [("en", "Deleted user"), ("fr", "Utilisateur supprimé")],
)
def test_a_deleted_author_is_a_deleted_user(language, wording):
    message = render(
        replace(BASE_DIGEST, language=language, comments=(Comment(None, "Hi"),))
    )

    assert wording in message.text
    assert wording in message.html


@pytest.mark.parametrize(
    "language, wording",
    [
        ("en", "A participant left this group gift."),
        ("fr", "Un participant a quitté ce cadeau commun."),
    ],
)
def test_a_deleted_account_leaves_as_a_participant(language, wording):
    message = render(replace(BASE_DIGEST, language=language, participants_left=(None,)))

    assert wording in message.text
    assert wording in message.html


@pytest.mark.parametrize("flag", ["gift_deleted", "hidden_gift_removed"])
def test_a_gift_that_went_says_nothing_else_about_it(flag):
    digest = replace(
        BASE_DIGEST,
        fields_changed=("description",),
        comments=(Comment("Bob", "a secret plan"),),
        participants_left=("Carol",),
        **{flag: True},
    )

    message = render(digest)

    for rendered in (message.text, message.html):
        assert "secret plan" not in rendered
        assert "Bob" not in rendered
        assert "Carol" not in rendered
        assert "description" not in rendered
        assert f"gift={GIFT_ID}" not in rendered
        assert LINKS.occasion in rendered


def test_a_price_change_is_listed_once():
    digest = replace(BASE_DIGEST, fields_changed=("price_currency", "price_amount"))

    assert render(digest).text.count("price") == 1


def test_a_multi_line_comment_keeps_its_lines():
    message = render(replace(BASE_DIGEST, comments=(Comment("Bob", "one\ntwo"),)))

    assert "one<br>\ntwo" in message.html
    assert "  one\n  two" in message.text


def test_no_external_image_and_only_our_own_links():
    message = render(
        replace(BASE_DIGEST, comments=(Comment("Bob", "https://evil.test"),))
    )

    assert "<img" not in message.html
    assert "src=" not in message.html
    assert "url(" not in message.html
    assert set(re.findall(r'href="([^"]*)"', message.html)) == {
        LINKS.gift,
        LINKS.unsubscribe_page,
        LINKS.account,
    }


def test_a_recipient_with_no_name_is_greeted_without_one():
    assert render(replace(BASE_DIGEST, recipient_name=" ")).text.startswith("Hello,\n")


@pytest.mark.parametrize(
    ("language", "creating", "subject"),
    [
        ("en", True, "Create your Shush Gift account"),
        ("en", False, "Reset your Shush Gift password"),
        ("fr", True, "Créez votre compte Shush Gift"),
        ("fr", False, "Réinitialisez votre mot de passe Shush Gift"),
    ],
)
def test_a_sign_in_email_names_the_app(language, creating, subject):
    # The product name (Shush Gift plan D2), in both languages.
    message = render_sign_in_link(language, creating, f"{BASE}/create-account#t")

    assert message.subject == subject
    assert "Shush Gift" in message.text
