"""What an email says (comments plan D15, D17, D18), in the recipient's language.

Titles, names and comments are untrusted. A message is first composed as plain
text in blocks; the text part prints those blocks and the HTML part escapes
them, in one place each, so no value can reach the HTML unescaped. Names and
titles are reduced to one line before anything else, so none can break out of
a header.
"""

import html
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

# C0, DEL, C1 (NEL is one of them), and the Unicode line and paragraph
# separators. Non-breaking spaces and joiners are text, and stay.
_LINE_BREAKERS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")

_EN = {
    "subject_update": "News about “{gift}” ({occasion})",
    "subject_deleted": "The gift “{gift}” was deleted ({occasion})",
    "subject_hidden_removed": "The hidden gift “{gift}” was removed ({occasion})",
    "greeting": "Hello {name},",
    "greeting_anonymous": "Hello,",
    "intro": "There is news about the gift “{gift}”, for {occasion}.",
    "gift_deleted": "The gift “{gift}”, for {occasion}, was deleted.",
    "hidden_removed": (
        "The hidden gift “{gift}” was removed from the occasion {occasion}."
    ),
    "fields_changed": "What changed: {fields}.",
    "field_title": "title",
    "field_description": "description",
    "field_links": "links",
    "field_price": "price",
    "field_image": "image",
    "comments_heading": "Comments:",
    "comment_by": "{author}:",
    "deleted_user": "Deleted user",
    "participant_left": "{name} left this group gift.",
    "a_participant_left": "A participant left this group gift.",
    "open_gift": "Open the gift",
    "open_occasion": "Open the occasion",
    "why": (
        "You are receiving this email because you are giving or following a "
        "gift in this occasion."
    ),
    "unsubscribe": "Stop email notifications",
    "account": "Email settings",
    "link_line": "{label}: {url}",
}

_FR = {
    "subject_update": "Du nouveau sur « {gift} » ({occasion})",
    "subject_deleted": "Le cadeau « {gift} » a été supprimé ({occasion})",
    "subject_hidden_removed": ("Le cadeau caché « {gift} » a été retiré ({occasion})"),
    "greeting": "Bonjour {name},",
    "greeting_anonymous": "Bonjour,",
    "intro": "Il y a du nouveau sur le cadeau « {gift} », pour {occasion}.",
    "gift_deleted": "Le cadeau « {gift} », pour {occasion}, a été supprimé.",
    "hidden_removed": (
        "Le cadeau caché « {gift} » a été retiré de l'occasion {occasion}."
    ),
    "fields_changed": "Ce qui a changé : {fields}.",
    "field_title": "titre",
    "field_description": "description",
    "field_links": "liens",
    "field_price": "prix",
    "field_image": "image",
    "comments_heading": "Commentaires :",
    "comment_by": "{author} :",
    "deleted_user": "Utilisateur supprimé",
    "participant_left": "{name} a quitté ce cadeau commun.",
    "a_participant_left": "Un participant a quitté ce cadeau commun.",
    "open_gift": "Voir le cadeau",
    "open_occasion": "Voir l'occasion",
    "why": (
        "Vous recevez cet e-mail parce que vous offrez ou suivez un cadeau de "
        "cette occasion."
    ),
    "unsubscribe": "Arrêter les notifications par e-mail",
    "account": "Réglages des e-mails",
    "link_line": "{label} : {url}",
}

_STRINGS = {"en": _EN, "fr": _FR}

# A notification's field names are the gift's columns (D10); amount and
# currency are one thing to a reader. In the order an email lists them.
_FIELD_LABELS = {
    "title": "field_title",
    "description": "field_description",
    "links": "field_links",
    "price_amount": "field_price",
    "price_currency": "field_price",
    "image_id": "field_image",
}


@dataclass(frozen=True)
class Links:
    gift: str
    occasion: str
    account: str
    unsubscribe_page: str
    unsubscribe_one_click: str


def build_links(
    public_base_url: str, occasion_id: uuid.UUID, gift_id: uuid.UUID, token: str
) -> Links:
    """The URLs of one email (D18, D19). They stay in inboxes: the routes they
    name must keep working in every later release. `token` is the signed
    unsubscribe token, whose alphabet is safe in a URL."""
    base = public_base_url.rstrip("/")
    return Links(
        gift=f"{base}/shared/{occasion_id}?gift={gift_id}",
        occasion=f"{base}/shared/{occasion_id}",
        account=f"{base}/account",
        unsubscribe_page=f"{base}/unsubscribe#{token}",
        unsubscribe_one_click=f"{base}/api/unsubscribe/{token}",
    )


@dataclass(frozen=True)
class Comment:
    # Null once the author deleted their account (D3).
    author_name: str | None
    body: str


@dataclass(frozen=True)
class Digest:
    """One email's content, decided by the worker. `gift_title` is the gift's
    title, or the captured one when the gift has gone. An email saying the gift
    was deleted or removed says nothing else about it (D11, D15), whatever else
    is set here.
    """

    recipient_name: str
    language: str
    occasion_name: str
    gift_title: str
    links: Links
    # The changed columns, as in the event's payload (D10).
    fields_changed: tuple[str, ...] = ()
    comments: tuple[Comment, ...] = ()
    # One entry per departure; null once their account is deleted (D14).
    participants_left: tuple[str | None, ...] = ()
    gift_deleted: bool = False
    hidden_gift_removed: bool = False


@dataclass(frozen=True)
class EmailMessage:
    subject: str
    html: str
    text: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class _Paragraph:
    text: str


@dataclass(frozen=True)
class _Quote:
    author: str
    body: str


def single_line(value: str) -> str:
    """`value` with nothing that could end a header line."""
    return _LINE_BREAKERS.sub(" ", value).strip()


def render(digest: Digest) -> EmailMessage:
    strings = _STRINGS[digest.language]
    links = digest.links
    gift = single_line(digest.gift_title)
    occasion = single_line(digest.occasion_name)
    name = single_line(digest.recipient_name)

    def say(key: str, **values: str) -> str:
        return strings[key].format(**values)

    named = {"gift": gift, "occasion": occasion}
    greeting = say("greeting", name=name) if name else say("greeting_anonymous")
    blocks: list[_Paragraph | _Quote] = [_Paragraph(greeting)]
    if digest.gift_deleted:
        subject = say("subject_deleted", **named)
        blocks.append(_Paragraph(say("gift_deleted", **named)))
        action, target = say("open_occasion"), links.occasion
    elif digest.hidden_gift_removed:
        subject = say("subject_hidden_removed", **named)
        blocks.append(_Paragraph(say("hidden_removed", **named)))
        action, target = say("open_occasion"), links.occasion
    else:
        subject = say("subject_update", **named)
        blocks.append(_Paragraph(say("intro", **named)))
        blocks += _activity(digest, say)
        action, target = say("open_gift"), links.gift

    footer = [
        (say("unsubscribe"), links.unsubscribe_page),
        (say("account"), links.account),
    ]
    why = say("why")
    return EmailMessage(
        subject=subject,
        html=_html(digest.language, subject, blocks, action, target, why, footer),
        text=_text(blocks, action, target, why, footer, say),
        headers={
            "List-Unsubscribe": f"<{links.unsubscribe_one_click}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _activity(digest: Digest, say) -> list[_Paragraph | _Quote]:
    blocks: list[_Paragraph | _Quote] = []
    if digest.fields_changed:
        labels = dict.fromkeys(
            say(key)
            for field, key in _FIELD_LABELS.items()
            if field in digest.fields_changed
        )
        blocks.append(_Paragraph(say("fields_changed", fields=", ".join(labels))))
    if digest.comments:
        blocks.append(_Paragraph(say("comments_heading")))
    for comment in digest.comments:
        author = (
            say("deleted_user")
            if comment.author_name is None
            else single_line(comment.author_name)
        )
        blocks.append(_Quote(say("comment_by", author=author), comment.body))
    for name in digest.participants_left:
        blocks.append(
            _Paragraph(
                say("a_participant_left")
                if name is None
                else say("participant_left", name=single_line(name))
            )
        )
    return blocks


def _text(blocks, action, target, why, footer, say) -> str:
    parts = []
    for block in blocks:
        if isinstance(block, _Paragraph):
            parts.append(block.text)
        else:
            indented = "\n".join(f"  {line}" for line in block.body.split("\n"))
            parts.append(f"{block.author}\n{indented}")
    parts.append(say("link_line", label=action, url=target))
    links = "\n".join(say("link_line", label=label, url=url) for label, url in footer)
    parts.append(f"--\n{why}\n{links}")
    return "\n\n".join(parts) + "\n"


def _html(language, subject, blocks, action, target, why, footer) -> str:
    escape = html.escape
    body = []
    for block in blocks:
        if isinstance(block, _Paragraph):
            body.append(f"<p>{escape(block.text)}</p>")
        else:
            lines = "<br>\n".join(escape(line) for line in block.body.split("\n"))
            body.append(
                '<blockquote style="margin:0 0 16px;padding-left:12px;'
                'border-left:3px solid #CBD5E1">'
                f"<strong>{escape(block.author)}</strong><br>\n{lines}</blockquote>"
            )
    body.append(
        f'<p><a href="{escape(target)}" style="color:#0F766E">{escape(action)}</a></p>'
    )
    links = " · ".join(
        f'<a href="{escape(url)}" style="color:#64748B">{escape(label)}</a>'
        for label, url in footer
    )
    content = "\n".join(body)
    return (
        "<!doctype html>\n"
        f'<html lang="{escape(language)}">\n'
        f'<head><meta charset="utf-8"><title>{escape(subject)}</title></head>\n'
        '<body style="font-family:sans-serif;color:#1E293B;line-height:1.5">\n'
        f"{content}\n"
        '<hr style="border:0;border-top:1px solid #E2E8F0">\n'
        f'<p style="font-size:12px;color:#64748B">{escape(why)}<br>\n{links}</p>\n'
        "</body>\n</html>\n"
    )
