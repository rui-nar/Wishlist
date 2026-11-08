# Wishlist — Need description

Status: converged on the first release's needs (2026-11-07), pending the
owner's read-through. Remaining questions are under
[Open questions](#open-questions).

## Problem

People who give each other gifts (family, friends) want to know what the
recipient would like, without spoiling the surprise and without two people
buying the same gift.

## Users and roles

Two roles, plus who the list is for:

- **Owner** — creates and edits the list and its gifts, and shares it. A list
  can have several **co-owners**.
- **Invitee** — someone an occasion is shared with. Reserves gifts, joins group
  gifts, adds hidden gifts and coordinates with the other invitees.
- **Recipient** — every list says who it is for:
  - **"for me"**: the owner and co-owners are the recipients, and are blind
    (e.g. my own list, or a couple's list "for us").
  - **"for someone else"**, given by name, without an account (e.g. a young
    child, or a spouse who does not use the app): the owners are not
    recipients, so they see invitee activity and can reserve, pledge, comment
    and add hidden gifts like an invitee.
- **Handing over:** an owner can transfer a "for someone else" list to the
  recipient once they have an account. It becomes "for me": the new owner is
  blind, including to everything from past occasions, and the previous owners
  become invitees.
- A "for me" list can never become "for someone else": that would let an
  owner unblind themselves.

A person can own lists and be an invitee on other people's.

## Core rules

- **The surprise.** Recipients never see any invitee activity on their list: no
  reservation, purchase, pledge, comment or notification about them, and
  nothing indirect (counts, timestamps, ordering, limits, error differences)
  that would let them infer it. This holds after the occasion too. This is the
  product's main invariant.
- **No double gift.** When two invitees reserve the same gift at the same
  moment, exactly one succeeds.
- **A recipient cannot join their own occasion as an invitee.** The server
  enforces it for recipients with an account. It cannot for a recipient known
  only by name: an occasion link forwarded to them lets them sign up and see
  everything. Accepted limitation.

## Use cases

### Lists and occasions

- An owner keeps **permanent lists** ("things I'd like").
- A list is shared for successive **occasions** (e.g. Christmas 2026,
  birthday 2027), each with a date.
- **Invitees belong to an occasion**, not to the list: the same list can be
  shared with family for Christmas and with friends for a birthday.
- Reservations belong to an occasion and expire after its date, so a gift
  reserved last Christmas is available again for the next occasion.
- **After an occasion**, the owner marks the gifts they actually received, and
  those leave the list. Invitee activity stays hidden.

### Gifts

First-release properties:

- title and description (size, colour, model…);
- one or more links to shop websites;
- an indicative price, with its currency;
- an image: fetched from a shop link when possible, otherwise uploaded by the
  owner. The owner adds it in one of three ways (owner, 2026-11-08): **select
  an image** from the device, give an **image URL**, or **paste an image** from
  the clipboard. One image per gift; it can be replaced or removed. An image
  from a URL is downloaded once by the server and kept as a copy, so the
  shop's site never learns who looks at the list and the image survives the
  shop changing it. Reading the image from a shop page link is later.

Later: priority, quantity (with partial reservations).

### Reserving

- An invitee **reserves** a gift (an intention, which they can release), then
  marks it **bought** (final).
- A **group gift**: several invitees join one gift together. The app records
  **pledges only**: who joined and, optionally, how much. Who buys and how
  they settle up happens outside the app; no money moves through it.
- **The owner edits or deletes a reserved gift:** the change goes through
  exactly as for any other gift; the invitees who reserved, bought or pledged
  on it are notified and decide what to do. (Notifications come with the
  notifications feature; until then the change simply shows.)
- Decided 2026-11-08 (owner's instruction to proceed with recommendations):
  - A gift is either reserved by one invitee or a group gift, never both.
    Whoever reserved it, or any participant of the group gift, can mark it
    bought. Bought is final in the app.
  - A participant can leave a group gift (their pledge goes); when the last
    one leaves, the gift is available again.
  - **Several occasions of one list at once** (e.g. family for Christmas,
    friends for a birthday): a gift reserved, in a group gift or bought in
    another occasion that has not passed shows to this occasion's invitees as
    "taken" (not by whom, nor in which occasion) and cannot be reserved, so it
    is not bought twice.
  - **After an occasion's date** its reservations and group gifts that were
    not bought end, and the gift is available again for the next occasion. A
    gift bought in a past occasion stays "taken" until the owner marks it
    received or deletes it.
  - An invitee who leaves an occasion is treated like a removed one: their
    reservations not bought are released, what they bought stays bought,
    their pledges are removed.
  - An occasion has passed from 12:00 UTC on the day after its date: that
    day has then ended in every time zone, so a reservation never ends early
    (the side that protects against a double gift).
    Whoever reserved a gift, or joined its group gift, can still mark it
    bought after the date, as long as nobody has claimed it since.
  - A bought reservation of someone who left or was removed keeps their name
    for the other invitees; deleting their account removes the name.
  - Deleting an occasion keeps the gifts bought in it "taken" (anonymously)
    until the owner marks them received or deletes them.

### Hidden gifts

- An invitee can add a **hidden gift** to an occasion: a gift that is not on
  the recipient's list (e.g. a spouse's idea, Grandma's own choice).
- The occasion's invitees see it like any other gift: they can reserve it,
  pledge on it and comment on it. Invitees of other occasions do not see it.
- The recipient does not see it until the **occasion's date**. Then only the
  hidden gifts marked **bought** are revealed, as the gift alone: who added,
  bought or pledged on it stays hidden, as for all invitee activity.
- Hidden gifts nobody bought are never revealed.
- A revealed gift leaves the list once the recipient marks it received. If
  not received, the recipient can dismiss it or keep it on their list as an
  ordinary gift.
- Hidden gifts never count towards the recipient's limits.

### Invitees among themselves

- Invitees see which invitee reserved, bought or pledged on each gift.
- They coordinate through a **comment thread under each gift**, hidden from the
  owner.

### Access

- An owner shares an **occasion link**. Whoever opens it signs
  in (or signs up) and joins the occasion as an invitee. A forwarded link lets
  others join.
- **Revoking the link** stops new people from joining; invitees who already
  joined keep access.
- **Removing an invitee:** they lose access at once and cannot rejoin the
  occasion through any link, current or old, until the owner allows them
  again; allowing them again does not rejoin them, they need a link. Their
  reserved-but-not-bought gifts become available again; gifts they bought
  stay bought; their pledges are removed and the other participants of those
  group gifts are notified. An invitee who leaves on their own can rejoin with
  a current link, unless the owner removes them afterwards: an owner's removal
  is recorded even if the person had already left.

### Deleting an account

An account can be deleted (GDPR). Then:

- the lists they own alone are deleted, with their gifts;
- as an invitee: gifts they reserved but did not buy become available again;
  gifts they bought stay bought; their pledges are removed and the other
  participants of those group gifts are notified;
- their comments stay, signed "Deleted user": the thread keeps its sense and
  nothing identifies them.

### Notifications

Push on mobile, email otherwise:

- to invitees who reserved, bought or pledged: the owner changed or deleted
  that gift;
- to invitees following a gift: a new comment.

Later candidates: group gift activity, occasion reminders.

### Free and premium (from the first release)

- **Free:** 1 list, at most 20 gifts per list.
- **Premium:** unlimited lists and gifts, as a **yearly subscription**.
- **Payment channels:** Stripe on the web, Apple and Google in-app purchase in
  the mobile apps (store rules), all feeding one premium status on the server.
- **Only owners pay.** Being an invitee is always free, whatever the invitee's
  own plan.
- **Nothing is deleted when premium ends.** Lists over the limit stay
  readable, shareable and editable but cannot grow (no new list, no new gift
  past 20), as in TraxJourney.
- **Only gifts still on the list count** towards the 20; gifts marked received
  do not.
- The limits never reveal invitee activity to the owner: reservations, group
  gifts, pledges and comments count towards nothing the owner sees.
- EU obligations from the first sale: VAT (OSS, Stripe Tax, tax-inclusive
  prices), the 14-day withdrawal right, terms of service. TraxJourney's
  `docs/BILLING.md` is the reference.

## Constraints

- **Platforms:** web, Android and iOS.
- **Sign-in:** Google, Apple (required on iOS alongside Google), email and
  password.
- **Languages:** English and French from the first release.
- **Offline (mobile):** owners can add and edit gifts offline, synced later;
  invitees can read what they already viewed, and every invitee action needs a
  connection.
- **Look:** direction "Lagoon", built on TraxJourney's design foundations
  (Inter, 8-point grid, 6/8/12/16 px radii, flat bordered cards, slate greys,
  sentence case, no emoji): deep teal primary `#0F766E`, rose `#E11D48` for
  invitee activity, Space Grotesk for titles. Light and dark themes. Mock-ups:
  https://claude.ai/artifact/PSc8n5pwZLeVxvLCPHNVmi (private to the owner).
- **Email:** Brevo, as TraxJourney (password reset and notifications).
- **Hosting:** the server side runs on the owner's existing VPS (OVH, France),
  next to TraxJourney.
- **Domain:** for now, PROD and VAL are subdomains of TraxJourney's domain
  (hostnames in the owner's VPS notes, not in this public repository); Wishlist
  gets its own domain later.
- **Stack (agreed ahead of the needs, see
  [`plans/DEVOPS_FOUNDATION_PLAN.md`](plans/DEVOPS_FOUNDATION_PLAN.md)):**
  Flutter; FastAPI, Alembic, PostgreSQL.

## Out of scope (first release)

- Moving money between invitees (group gift settlement).
- Gift priority and quantities.
- Group gift activity notifications and occasion reminders.
- Languages other than English and French.

## Open questions

| Question | Affects |
|---|---|
| Who can add co-owners, and can they remove each other? What happens to a co-owned list when one co-owner deletes their account? | Roles, access control, account deletion |
| Hidden gifts: at what moment exactly is the occasion's date reached (whose time zone; start or end of the day)? | Reveal timing |
| Hidden gifts nobody bought: does the author keep them for a later occasion, or do they expire with the occasion? | Hidden gifts lifecycle |
| Can invitees also add hidden gifts to a "for someone else" list, where nobody is blind until a handover? | Hidden gifts, handover |
| Offline edits by two co-owners on the same gift: last write wins, or a conflict shown? | Sync design |
| Comment moderation: can invitees edit or delete comments; can anyone report one? | Comments design |
| Image limits: size, count per gift, storage per account | VPS disk, backups, premium |
