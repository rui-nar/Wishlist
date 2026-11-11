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

- **Admin** (owner, 2026-11-10): the operator of the app, named by account in
  the server configuration. Sees the registered accounts by address, their
  plan, their lists with the number of gifts each, and the space their photos
  take. Can grant Premium by hand and delete an account. Sees counts only,
  never gifts, reservations, pledges or comments. The admin is a user too:
  nothing the admin sees may change with invitee activity, on their own lists
  or anyone else's, so a hidden gift's photo counts for no one.
  For each account the admin sees, apart, its Stripe subscription (status,
  start date, renewal or end date) and a Premium granted by hand with its
  controls; one never hides the other (owner, 2026-11-11).

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
- Decided 2026-11-09 (owner's instruction to proceed silently):
  - An owner can mark **any** gift of their list received, at any time: the
    action is offered the same way on every gift, so it says nothing about
    which gifts were bought.
  - A received gift leaves the list and every occasion: invitees no longer
    see it. The owner finds it under "Received" on the list, where they can
    put it back on the list (a mistake) or delete it. Putting it back brings
    it back as it was, activity included.
  - A received gift cannot be reserved and counts towards no limit.

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
- Decided 2026-11-09 (owner's instruction to proceed silently):
  - The occasion's date is reached when the occasion **has passed**, as for
    reservations: 12:00 UTC on the day after its date, when that day has
    ended in every time zone. Moving the date later hides the gift again
    until the new date has passed.
  - Whoever added a hidden gift can edit or delete it until it is bought;
    the other invitees reserve, pledge and comment on it. Its author's name
    is shown to the occasion's invitees, as for any invitee activity.
  - A hidden gift belongs to its occasion. One nobody bought ends with the
    occasion: it is never revealed, never carried over, and stays visible
    to that occasion's invitees only as part of the passed occasion.
  - Deleting an occasion before it has passed deletes its hidden gifts,
    bought or not: they are never revealed. A bought hidden gift of an
    occasion deleted after it passed stays revealed.
  - The recipient's three choices on a revealed gift: **received** (it
    leaves the list, as any received gift), **dismiss** (it is deleted), or
    **keep** (it becomes an ordinary gift of the list, available again, with
    nothing of its past activity).
  - "For someone else" lists: invitees add hidden gifts as on any list; the
    owners, who are not recipients, see them and add their own like
    invitees. When handover arrives, the new owner must be blind to them
    like to every past activity.
  - Moving an occasion's date earlier never brings a reveal forward: a
    hidden gift is revealed once the latest date the occasion ever had has
    passed. Otherwise a recipient could move the date into the past, read
    the reveals and move it back.
  - A hidden gift whose author leaves or deletes their account stays, with
    their name (no name after an account deletion); nobody can edit it any
    more. When the owner removes its author, their hidden gifts nobody
    bought are deleted: the owner's remedy against an abusive invitee.
  - Moving an occasion's date earlier shows the same warning on every
    occasion: hidden gifts are revealed after the later date anyway.
  - Revealed gifts, with the three choices, also show to the owners of a
    "for someone else" list.

### Invitees among themselves

- Invitees see which invitee reserved, bought or pledged on each gift.
- They coordinate through a **comment thread under each gift**, hidden from the
  owner.
- Decided 2026-11-09 (owner's instruction to proceed silently):
  - A thread belongs to a gift **in one occasion**: invitees of another
    occasion of the same list never see it. Hidden gifts have threads too.
  - The author of a comment can edit it (it then shows "edited") and delete
    it (it disappears). There is no reporting: occasions are small private
    groups, and an owner can remove an invitee.
  - A comment of someone who left or was removed keeps their name; deleting
    their account signs it "Deleted user".
  - A comment is plain text, at most 2000 characters.
  - Comments stay possible after the occasion has passed. A received gift's
    thread is hidden while it is received and comes back with it.

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

Decided 2026-11-09 (owner's instruction to proceed silently):

- **Following:** a giver follows a gift (in its occasion) once they comment
  on it, reserve it or join its group gift, and can follow or unfollow it
  by hand at any time.
- **What is notified:** the owner changed a gift's title, description,
  links, price or image, or deleted it (to its claim's participants,
  bought ones included); a new comment (to the gift's followers, never its
  author); a participant leaving a group gift because they left the
  occasion, were removed or deleted their account (to the other
  participants, as Access and Deleting an account say).
- **Channels now:** email, through Brevo. Push needs the published mobile
  apps; it comes with them, on the same notifications.
- Emails are grouped: at most one email per gift and person every 15
  minutes, listing what happened since the last one.
- Every email has a one-click unsubscribe link, and the account screen has
  an "email notifications" switch (on by default).
- Emails are in the user's app language (English or French).
- A recipient never receives a notification about invitee activity, and the
  owner's own requests do the same work whether or not they cause
  notifications.
- Unfollowing by hand sticks: commenting or pledging later does not follow
  the gift again.
- A first email waits about a minute, so a quick correction or a burst of
  comments arrives as one email.
- When the owner removes an invitee and that deletes a hidden gift they
  added, its other participants are told the gift was removed.
- Not notified for now: a gift marked received, an occasion or list
  deleted, a hidden gift edited or deleted by its author, and anything the
  recipient does with a revealed gift (received, dismiss, keep, or editing
  it first): the hidden gift's story ended with the reveal.

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
- Decided 2026-11-10 (owner's instruction to proceed silently):
  - **Co-owned lists:** a list has no gift limit when at least one of its
    owners is premium, and then counts for none of its free co-owners.
  - **Keep and put back are growth:** refused at the limit, like a new gift.
    The gift stays where it is (revealed or received); the owner can still
    mark it received, dismiss it, delete it, free a place or go premium.
    Limits apply only when something would actually grow.
  - **Premium ends** at the end of the paid period, with a 3-day tolerance; a
    failed renewal keeps premium while Stripe retries the card.
  - **Limits are a switch of their own**, off by default, and never apply
    while no purchase is possible. All numbers are configurable.
  - **Purchases are on the web only** until the mobile apps have store
    purchases; the apps show the plan and the limits, and no price or
    purchase.
  - **Deleting an account** cancels its subscription at once; Stripe keeps the
    customer and invoices for accounting.
  - **Withdrawal:** acknowledged at checkout; for now a refund is made by hand
    in Stripe. An in-app withdrawal is decided before the first real sale.

## Constraints

- **Platforms:** web, Android and iOS.
  iOS, decided 2026-11-11 (owner): built and signed by GitHub Actions on
  macOS and delivered through TestFlight; Premium bought on iPhone through
  Apple's in-app purchase from the first iOS release, and Premium bought on
  the web works on iPhone too. The iOS bundle identifier and the Android
  application id are `com.shushgift.app`, and `com.shushgift.app.val` for VAL
  (owner, 2026-11-11, see Name and domain).
- **Sign-in:** Google, Apple (required on iOS alongside Google), email and
  password.
  Decided 2026-11-10 (owner's instruction to proceed silently):
  - **One account per way of signing in.** Accounts with the same address
    are never joined automatically.
  - **The address is proven before the password exists:** the person types an
    address, gets a link, and chooses the password on the page it opens. The
    same flow resets a forgotten password, and ends every other session.
  - **Passwords:** 10 to 128 characters, no composition rules. Sign-in attempts
    and emails are rate limited.
  - **Apple:** on the web and Android now, on iOS with the iOS release. The
    email link opens the installed app on a phone, and the web otherwise
    (owner, 2026-11-11).
- **Introduction:** three screens explain how the app works, namely the hidden
  actions and the hidden gifts (owner, 2026-11-10). Shown once, after the first
  sign-in on a device, and available again from the account screen. They are
  general: they never say anything about the person's own lists or gifts.
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
- **Name and domain** (owner, 2026-11-11): the app is called **Shush Gift**
  and has its own domain, `shushgift.com`: PROD at `shushgift.com`, VAL at
  `val.shushgift.com`. The rename goes all the way, internal identifiers
  included (code, image, repository, servers, databases). The app ids are
  `com.shushgift.app` and `com.shushgift.app.val`, and can never change once
  in the stores. The repository is private. The move happens as soon as the domain is live, before
  the iOS and Android store releases, so no store build ships with the old
  hosts. Until then PROD and VAL are subdomains of TraxJourney's domain
  (hostnames in the owner's VPS notes, not in this repository). The old hosts
  are removed right after PROD has moved: PROD has no real users yet, so links
  sent before the move may stop working. Emails come from
  `hello@shushgift.com`. On a phone with the app installed, occasion links
  and email links open the app instead of the browser (owner, 2026-11-11).
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
| Offline edits by two co-owners on the same gift: last write wins, or a conflict shown? | Sync design |
| Paywall placeholders the owner supplies before the first real sale: the price, the Stripe account and keys, the legal texts and consent wording, and whether an in-app withdrawal is required (EU Directive 2023/2673, to confirm with legal counsel) | Premium |
| Image storage per account (size and count per gift are decided: 10 MB per image, one image per gift, gift images plan D4, D11) | VPS disk, backups, premium |
