# Comments, following and email notifications

## Problem

Givers can reserve, buy and pledge, but they cannot talk to each other
("I'll take the blue one", "who has the receipt?"), and nothing tells them
when something they are giving changes under them. NEEDS calls both out:
invitees "coordinate through a comment thread under each gift, hidden from
the owner" (Invitees among themselves), and invitees who reserved, bought or
pledged are notified when the owner changes or deletes that gift
(Reserving, Notifications). Until now "the change simply shows" (RESERVING
plan, Problem): a giver who reserved a scarf finds out it became a hat only
if they open the occasion again.

This plan delivers the decisions of `docs/NEEDS.md` dated 2026-11-09 under
"Invitees among themselves" and "Notifications", and the notifications that
"Access" and "Deleting an account" promise:

- **Comments:** a thread per gift in one occasion, for that occasion's
  givers only; plain text up to 2000 characters; authors edit ("edited") and
  delete; names kept after leaving or removal; "Deleted user" after account
  deletion.
- **Following:** automatic on commenting, reserving or joining a group gift;
  by hand at any time.
- **Notifications by email (Brevo):** the owner changed or deleted a gift
  (to its claim's participants, bought ones included); a new comment (to the
  gift's followers, never its author); a participant leaving a group gift
  because they left the occasion, were removed or deleted their account (to
  the other participants). Grouped (one email per person and gift every 15
  minutes), one-click unsubscribe, an "email notifications" switch on the
  account screen, in the user's app language.
- **The surprise:** recipients never see a comment and never receive a
  notification about invitee activity; the owner's gift edits and deletions
  do the same work whether or not they cause notifications.

Push is not in this plan: it needs the published mobile apps (NEEDS,
Notifications) and comes with them, as another channel on the same
notifications. Group gift activity notifications and occasion reminders are
out of scope for the first release (NEEDS, Out of scope).

## Current state

- **Claims** (`server/app/reserving/`, RESERVING_PLAN): `gift_claims` keyed
  by `gift_id` (FK `gifts` `ON DELETE CASCADE`), `claim_participants`
  (`gift_id`, `user_id`). `release.py` `release_activity(db, user_id,
  occasion_id | None)` releases a giver who leaves, is removed or deletes
  their account; `lock_occasions`, `delete_unbought_claims`,
  `delete_gift_claims` serve occasion, list and account deletion. Lock order
  (D7): user `FOR KEY SHARE` (auth dependency), occasion `FOR SHARE`, gift
  `FOR KEY SHARE`, then claims.
- **Who gives:** `server/app/lists/access.py` `giving_occasion(db, user,
  occasion_id, lock=True)`: a member of the occasion, or an owner of its list
  when the list is "for someone else"; a recipient gets the random-id 404.
  `server/app/reserving/router.py` `_giving_gift` adds "the gift is on the
  occasion's list" with the gift `FOR KEY SHARE`.
- **Hidden gifts and received** (`docs/plans/HIDDEN_GIFTS_PLAN.md`,
  delivered first on this branch, assumed here, not designed): hidden gifts
  are rows of `gifts` with a nullable hidden-occasion FK and a nullable author
  FK; received gifts carry a received state and leave every occasion. After
  that delivery, `_giving_gift` (or the function that replaced it) answers
  404 for a received gift and for a hidden gift of another occasion. Every
  key in this plan is a `gift_id`, so hidden gifts need nothing special. Its
  migration is the Alembic head this plan's first migration follows.
- **Owner's gift writes:** `server/app/lists/router.py` `update_gift`
  (`PATCH /api/gifts/{id}`, image changes included through `image_id`) and
  `delete_gift` (`DELETE /api/gifts/{id}`; today its claims go by the
  foreign key's cascade; D13 ends that). HIDDEN_GIFTS_PLAN D15: every path
  of that plan that deletes or replaces a gift row (keep, dismiss, an
  author's delete, an occasion's deletion, an author's removal) calls one
  hook, `drop_gift_activity(db, gift_ids)` in
  `server/app/reserving/release.py`, whose contract is "no activity of
  those ids is reachable once the transaction commits"; today it deletes
  their claims, and this plan owns its body from here on. Keep replaces the
  revealed row by a new one with a new id. `visibility.in_occasion(occasion)`
  decides whether an occasion's givers see a gift. Its tests
  `server/tests/lists/test_received.py` and `test_hidden_gifts.py` assert
  unreachability through the API.
  `leave_occasion`, `remove_member`, `delete_occasion`, `delete_list`, and
  `server/app/accounts/router.py` `delete_me` call `release.py`.
- **Accounts:** `users` has `email` (from Google, refreshed at each sign-in)
  and `display_name`; no language, no preferences. `GET /api/me` answers
  `UserOut` (`id`, `email`, `display_name`). The client follows the device
  language (English, or French when the device is French; `client/lib/main.dart`);
  the server never learns it.
- **Background job pattern:** `server/app/media/purge.py` `MediaPurge`, a
  daemon thread started and stopped in `server/app/main.py`'s lifespan,
  one transaction per step, a `_log` line per run, `stop()` joining the
  thread. Tests build apps through `server/tests/conftest.py` `make_client`,
  which runs the lifespan.
- **Outbound HTTP:** `server/app/safe_fetch.py` (user URLs: vetted, capped,
  typed errors with no URL in them, a fake in `app.state.url_fetcher` for
  every test). No email is sent by the app today.
- **Settings and secrets:** `server/app/settings.py` (environment only);
  `deploy/prod/.env.example` and `deploy/val/.env.example` document each
  variable with no value; `docs/DEPLOYMENT.md` step 5 creates the `.env`
  files, step 6 sets `PUBLIC_BASE_URL`, "Release-specific steps" lists
  one-time host steps. `PUBLIC_BASE_URL` is empty on VAL and PROD today. VAL
  is seeded from PROD's dumps (`deploy/val/seed-from-prod.sh`), so VAL's
  `users.email` are real people's addresses.
- **Tests that guard the surprise:** `server/tests/lists/test_roles.py`
  (role matrix; `test_every_route_is_in_the_matrix` over `GUARDED_PREFIXES`)
  and `server/tests/lists/test_surprise.py` (world against control, twin
  gifts; `test_every_route_is_called` over every route of the OpenAPI
  document, so any new route anywhere must be called there).
- **Client:** `client/lib/src/shared/gift_sheet.dart` (`showGiftSheet`:
  title, price, details, participants, actions), `occasion_screen.dart`
  (loads the view and claims, opens the sheet; sends owners elsewhere),
  `shared_repository.dart`, `client/lib/src/auth/account_screen.dart` (name,
  email, about, sign-out, delete), `client/lib/src/app_router.dart`
  (`_publicPaths` = welcome, about), `client/lib/src/welcome/welcome_screen.dart`
  (third card `welcomeSurprise*`, RESERVING D15), fakes in
  `client/test/lists/support/fake_lists_server.dart` and
  `client/test/support/fakes.dart`.

## Decisions

### Comments and following

- **D1 — A comment belongs to a gift in one occasion.** New table
  `comments`: `id` (UUID), `occasion_id` (FK `occasions` `ON DELETE
  CASCADE`), `gift_id` (UUID, **no foreign key**, D13), `author_id` (FK
  `users` `ON DELETE SET NULL`, nullable, indexed), `body`
  (`varchar(2000)`), `created_at`, `edited_at` (null until edited); index
  (`occasion_id`, `gift_id`, `created_at`). The thread is "the comments of
  (occasion, gift)": invitees of another occasion of the same list never
  reach it, hidden gifts have threads like any gift (NEEDS, Decided
  2026-11-09). Rules out one thread per gift across occasions (it would
  leak between occasions) and a thread table (nothing to store on it).
- **D2 — What a comment is.** Plain text, 1 to 2000 characters counted as
  Unicode code points after trimming leading and trailing whitespace;
  whitespace-only is refused (422). NUL and other control characters except
  line feed and tab are refused (422): PostgreSQL rejects NUL in text, which
  would otherwise be a 500. No markup, no links made by the server; the
  client renders text as text. The author edits it (`edited_at` set, shown
  "edited") and deletes it (the row is deleted: it disappears, NEEDS). No
  reporting (NEEDS). Comments are allowed on a passed occasion: settling up
  happens after the date; the thread of a received gift is unreachable while
  it is received (the gift has left every occasion) and is back, unchanged,
  if the owner puts it back ("brings it back as it was, activity included").
- **D3 — Authors and names.** A comment shows its author's current
  `display_name`. Someone who left or was removed keeps their name (their
  user row exists; NEEDS). Account deletion sets `author_id` to null by the
  foreign key; the client shows "Deleted user" ("Utilisateur supprimé"); the
  response carries no trace of who it was. `mine` replaces any user id, as
  for claims (RESERVING D6).
- **D4 — Following.** New table `gift_follows`: `occasion_id` (FK
  `occasions` `ON DELETE CASCADE`), `gift_id` (UUID, no foreign key, D13),
  `user_id` (FK `users` `ON DELETE CASCADE`, indexed), `following` (bool),
  `updated_at`; primary key (`occasion_id`, `gift_id`, `user_id`).
  - Automatic: posting a comment, reserving (including marking a free gift
    bought), and starting or joining a group gift insert `following = true`
    with `ON CONFLICT DO NOTHING`.
  - By hand: follow and unfollow upsert `following = true | false`. An
    explicit unfollow is kept, so a later comment or pledge does not follow
    again: the person said stop. Rules out "commenting follows again"
    (GitHub's way), which re-enrols someone who opted out.
  - Leaving an occasion and being removed delete the person's follows in
    that occasion (`release_activity`, D14); account deletion cascades.
  - Following is read with the thread (D5); there is no list of follows.
- **D5 — Endpoints.** All require `current_user` and resolve through
  `giving_occasion`, then the gift through `giving_gift` (D6). Not a giver,
  a gift not in the occasion (another list, received, hidden in another
  occasion), a comment that is not of this thread, or a comment that is not
  the caller's for an edit or delete: 404 with the random-id body. A
  recipient therefore gets, on every route and for every thread state,
  exactly what a stranger gets for random ids.

  | Method and path | What | Answers |
  |---|---|---|
  | `GET /api/occasions/{occasion_id}/gifts/{gift_id}/comments` | the thread and my follow state | 200 `GiftThread` |
  | `POST /api/occasions/{occasion_id}/gifts/{gift_id}/comments` `{"body": "…"}` | comment; follows (D4) | 201 `CommentOut` |
  | `PATCH /api/occasions/{occasion_id}/gifts/{gift_id}/comments/{comment_id}` `{"body": "…"}` | edit my comment | 200 `CommentOut` |
  | `DELETE /api/occasions/{occasion_id}/gifts/{gift_id}/comments/{comment_id}` | delete my comment | 204 |
  | `PUT /api/occasions/{occasion_id}/gifts/{gift_id}/follow` | follow | 204, idempotent |
  | `DELETE /api/occasions/{occasion_id}/gifts/{gift_id}/follow` | unfollow | 204, idempotent |

  Models, fields listed explicitly:
  - `GiftThread`: `following` (bool: a row with `following = true`),
    `comments`: list of `CommentOut`, oldest first (`created_at`, `id`).
  - `CommentOut`: `id`, `author_name` (string, or null for a deleted
    account), `mine` (bool), `body`, `created_at`, `edited` (bool).
  - `CommentIn`: `body` (`extra="forbid"`).
- **D6 — One gift check for every giver route.** `_giving_gift` moves from
  `reserving/router.py` to `lists/access.py` as `giving_gift(db, user,
  occasion_id, gift_id, lock=True) -> Occasion`, with the hidden-gift and
  received rules the hidden-gifts delivery gave it, and `lock=False` for
  reads (no `FOR SHARE` on the occasion, no `FOR KEY SHARE` on the gift, as
  `occasion_claims` does: an owner's change never waits on a giver's read).
  The claims routes and the comment routes use the same function, so a gift
  is "in the occasion" by one definition.
- **D7 — Comment writes and locks.** Comment and follow writes follow
  RESERVING D7's order (user, occasion `FOR SHARE`, gift `FOR KEY SHARE`),
  then lock the comment row `FOR UPDATE` for an edit or delete. They insert,
  update and delete only `comments`, `gift_follows` and the outbox (D9):
  never `gifts`, `lists` or `occasions`, so nothing an owner reads moves
  (RESERVING D3). A removal or leave racing a comment either committed first
  (404) or waits and then finds a comment by a non-member, which keeps its
  name as any removed person's comment does.
- **D8 — Keeping a revealed hidden gift drops its thread, by
  construction.** NEEDS: a kept revealed gift becomes ordinary "with nothing
  of its past activity". Keep puts a new gift row with a new id on the list
  and deletes the revealed row through `drop_gift_activity`
  (HIDDEN_GIFTS_PLAN D6, D15): the thread and follows are keyed on the old
  id, which answers 404 everywhere, so nothing of them is reachable from the
  kept gift; their rows go with the sweep (D13). No call is added to the
  hidden-gifts handlers.

### Notifications

- **D9 — A durable outbox, written in the triggering transaction.** New
  table `notification_events`: `id` (bigint identity), `kind`
  (`gift_changed` | `gift_deleted` | `comment_added` | `participants_left` |
  `gifts_removed`,
  check constraint), `occasion_id` (UUID, null, no FK), `gift_id` (UUID,
  null, no FK), `actor_id` (FK `users` `ON DELETE SET NULL`, null),
  `payload` (JSONB), `created_at`, `status` (`pending` | `done` |
  `failed`, check constraint), `reason` (a fixed word, null), `processed_at`,
  `attempts`, `next_attempt_at`; partial index on `next_attempt_at` where
  `status = 'pending'`. A fan-out that raises goes back to `pending` with
  backoff (1, 5, 30, 120 minutes); the fifth failure sets `failed` with
  reason `error` and logs the event's id and kind (nothing else). A
  `failed` event is never retried and counts as processed for the sweep
  (D13), so nothing is retried forever and nothing waits on it. The request that causes the event inserts exactly
  one row, in its own transaction, so an event exists if and only if its
  cause committed. The payload holds no personal data: names are read from
  `users` at send time, so a deleted account's name is never sent
  afterwards. Rules out sending from the request (a slow or failing Brevo
  would slow or fail the request, and a rollback after sending would mail
  something that never happened) and an in-memory queue (lost on restart).
- **D10 — What writes an event.**

  | Cause | Event | Payload | Written by |
  |---|---|---|---|
  | An owner's `PATCH /api/gifts/{id}` that changes the title, description, links, price (amount or currency) or image | `gift_changed`, `gift_id`, actor the owner | `{"fields": [...]}`, the changed field names | `update_gift` |
  | An owner's `DELETE /api/gifts/{id}` | `gift_deleted`, `gift_id`, actor the owner | `{"title": "…", "received": bool}`: the title, and whether the gift was received, at deletion (the owner's own data) | `delete_gift` |
  | `POST …/comments` | `comment_added`, `occasion_id`, `gift_id`, actor the author | `{"comment_id": "…"}` | the comment route |
  | `release_activity` (leave, removal, account deletion) | `participants_left`, actor the leaver | `{"gifts": [{"gift_id", "occasion_id"}…]}`: the group gifts they left whose claim is live (`rules.is_live(now)` at release time) and still has participants | `release.py` |
  | An owner's `DELETE …/members/{user_id}` | `gifts_removed`, `occasion_id`, actor the owner | `{"gifts": [{"gift_id", "title"}…]}`: the hidden gifts the removed invitee added that the removal deleted (HIDDEN_GIFTS_PLAN D8, `delete_unbought_by`, which returns their ids and titles); the title is captured because the row is gone by fan-out | `remove_member` |

  The `gift_changed` condition compares the request's values with the gift's
  stored ones, so it depends on the owner's input and the gift alone, never
  on activity. **A revealed gift writes no event** (NEEDS, Notifications:
  anything the recipient does with a revealed gift notifies nobody):
  `update_gift` and `delete_gift` skip the event when the gift has
  `for_list_id` set (`list_id` null). The owner reaches a hidden gift only
  once it is revealed (an unrevealed one answers 404 through `owned_gift`,
  HIDDEN_GIFTS_PLAN), so that column, the owner's own data, says
  "revealed" without reading any activity, and the request does the same
  work for every revealed gift whatever its claim, thread or followers. A
  hidden gift edited or deleted by its author, and keep and received on a
  revealed gift, write no event either (NEEDS). `participants_left` is
  written once per `release_activity` call, also with an empty list, and
  `gifts_removed` once per removal, also with an empty list, so leave,
  removal and deletion write the same event rows whatever was released or
  deleted (D12). A group gift whose claim has expired (its occasion passed)
  is not listed: it already ended, and its participants are not told of a
  departure from it. Marking a gift received and
  deleting an occasion or a list notify nobody (NEEDS lists only the causes
  above; Open decisions).
- **D11 — Fan-out: who is notified, decided by the worker.** The worker
  (D16) turns each event into `notifications` rows: `id` (bigint identity),
  `event_id` (FK `notification_events` `ON DELETE CASCADE`), `user_id` (FK
  `users` `ON DELETE CASCADE`), `occasion_id` (FK `occasions` `ON DELETE
  CASCADE`), `gift_id` (UUID, no FK), `created_at`, `email_digest_id` (FK
  `email_digests`, `ON DELETE SET NULL`, null); unique (`event_id`,
  `user_id`), so fanning out an event twice inserts nothing twice.
  - `gift_changed`, `gift_deleted`: the participants of the gift's claim,
    bought ones included, in the claim's occasion, **if the claim was live
    when the event was written**: `rules.is_live(event.created_at)`, the
    rule every claims read uses, evaluated at the event's time rather than
    the fan-out's. A deleted gift's claim rows cannot change after the
    deletion (every claim route answers 404 on its id), so this is the
    claim as of the deletion, without the owner's request reading it. An
    expired unbought claim (its occasion passed) notifies no one. **The
    actor is never a target**: the owner of a "for someone else" list who
    also gives is not told of their own edit. No claim, no one. A
    `gift_changed` on a gift received at fan-out time, and a `gift_deleted`
    whose payload says `received`, notify no one (received is not
    notified, and its invitees no longer see it).
  - **A claim with no occasion** (bought for an occasion since deleted,
    RESERVING D11) has no giver to notify: the event is set `done` with
    reason `no_occasion` and no notification. Every target must be a giver
    of an occasion (below), and an email names its occasion; the buyer
    already saw that occasion go.
  - `comment_added`: the followers (`following = true`) of (occasion, gift),
    except the comment's author; nobody if the comment was deleted before
    fan-out.
  - `participants_left`: for each listed gift, the claim's participants at
    fan-out time (the leaver is no longer one). A listed gift whose row is
    gone by fan-out (deleted by the same removal, or since) is skipped for
    this event: the removal's `gifts_removed` tells its participants, and a
    gift deleted later by its owner has its own `gift_deleted`.
  - `gifts_removed`: for each listed gift, the participants of its claim,
    read from the claim rows the deletion left (D13: nothing cascades from
    the gift, and the sweep waits for this event), as live at the event's
    time, except the actor; the email says the hidden gift, by its captured
    title, was removed from the occasion, and nothing else about it. No
    claim rows, no one for that gift.
  - **Fan-out is per gift.** For the two list events, each listed gift is
    evaluated on its own: a gift with missing rows is skipped with nothing
    written for it, and never fails the event, so the other gifts of the
    same event are still notified. Only an unexpected error fails the event
    (D9's backoff and cap).
  - **Every target must be a giver of the notification's occasion at fan-out
    time**, by the same rule as `giving_occasion`, evaluated in SQL
    (`access.py` gains `giver_condition(user_id, occasion_id)`, ownership of
    a "for me" list checked first). A recipient is never a giver, so no
    notification row ever names a recipient, including a member who became
    a co-owner of a "for me" list, and including after a handover (computed
    from the list's current kind, RESERVING D4). The check runs again at
    send time (D15).
  - Notifications are channel-agnostic: "this happened, for this person,
    about this gift in this occasion". Email is one delivery of them (D15).
    Push, with the mobile apps, adds its own delivery table keyed on
    `notifications.id` and a device table, without touching events, fan-out
    or the email path. Rules out an email-only outbox, which push would
    have to rewrite.
- **D12 — The owner's requests do the same work whatever the activity
  (NEEDS, Notifications; F1).**
  - `update_gift` writes at most one event row, decided by D10's
    comparison and whether the gift is revealed (both the owner's data). It
    reads nothing about claims, follows or comments.
  - `delete_gift` writes exactly one `gift_deleted` row (none for a
    revealed gift, D10) and deletes the gift row. Nothing cascades from `gifts` into activity any more (D13), so the
    request deletes the same rows whether the gift had a claim, pledges,
    comments and followers, or nothing.
  - `remove_member` writes exactly one `participants_left` row and one
    `gifts_removed` row, whatever the removed person held. Its release of
    their claims and HIDDEN_GIFTS_PLAN D8's deletion of their unbought
    hidden gifts are per-row work RESERVING's and that plan's envelopes
    accept for removal; this plan adds nothing per gift to it. Identical
    statements are not required of it: its floor is those two event rows
    plus that work.
  - Who is notified is decided by the worker (D11), in its own transaction,
    long after the owner's response.
  A test records the SQL statements and row counts of the owner's `PATCH`
  and `DELETE /api/gifts/{id}` on twin gifts, one with each kind of activity
  and one without, and requires them identical (U3, U9); for
  `remove_member` it checks exactly one row of each of its two events with
  and without group gifts and hidden gifts. A schema test fails if any foreign
  key from an activity table (`gift_claims`, `claim_participants`,
  `comments`, `gift_follows`, notification tables) references `gifts`.
- **D13 — Deleting a gift leaves its activity to the worker.** The foreign
  key `gift_claims.gift_id → gifts` is dropped; `comments`, `gift_follows`
  and the notification tables never had one. `drop_gift_activity`
  (HIDDEN_GIFTS_PLAN D15) keeps its name, its callers and its contract, and
  its body stops deleting anything: the contract (nothing reachable once
  the transaction commits) holds by construction, since the gift rows it is
  called for are deleted in the same transaction, and the sweep below
  removes their activity. So keep and dismiss, the recipient's own
  requests, and a hidden gift's deletion do no work that depends on the
  gift's activity, as `delete_gift` (D12). Deleting a gift therefore
  leaves its claim, participants, comments and follows in place, unreachable:
  every read of activity already joins `gifts` (`occasion_claims`, `taken`,
  the thread through `giving_gift`), and a deleted gift's id answers 404
  everywhere. The worker:
  1. fans out the `gift_deleted` event, reading the claim's participants
     from those rows;
  2. then deletes the activity of every gift id that no longer exists in
     `gifts` and is named by no `pending` `gift_deleted` or
     `gifts_removed` event (claims,
     participants by cascade, comments, follows). The same sweep cleans up
     after every other way a gift row goes (keep, dismiss, a hidden gift
     deleted by its author, an occasion's hidden gifts), and deletes unbought
     claims with no occasion (below).

  **Orphaned unbought claims and the occasions' `SET NULL`.** An owner
  deleting a gift with an unbought reservation leaves its claim; deleting
  the list or the account before the sweep cascades the occasions, whose
  `SET NULL` would meet the claims' check constraint
  `ck_gift_claims_occasion_id` (`occasion_id IS NOT NULL OR bought_at IS
  NOT NULL`): a 500 (the RESERVING R1-1 failure), in this release and in
  the previous one after a rollback. **The migration drops that check
  constraint.** An unbought claim with no occasion is then simply expired:
  `is_live` already answers false for it (it holds its gift only when
  bought or of an occasion that has not passed), so the gift is free,
  `purge_expired` deletes it when the gift is claimed again, and the sweep
  deletes it. Both releases run on this schema without a 500, and rollback
  stays image-only (DevOps plan D15, DEPLOYMENT.md Rollback). The explicit
  deletions of RESERVING D11 (`delete_unbought_claims`,
  `delete_gift_claims`) stay as they are. Rules out a downgrade before
  every rollback across this release (an operator step against D15's "safe
  one version back"; forgetting it leaves 500s on list and account
  deletion) and a trigger on `occasions` (logic outside the code, unseen by
  `alembic check`).
  - `claims_invariants.py` tolerates orphaned claims (gift row gone) and
    unbought claims with no occasion, both not live, and checks that no API
    read returns one; its other checks are unchanged.
  Rules out capturing the participants into the event in the owner's
  request (per-claim work in the request, on top of the cascade, which is
  itself per-claim work) and soft-deleting gifts (every gift read in the
  codebase would need a filter, and one missed filter brings a deleted gift
  back).
- **D14 — Givers going away.** `release_activity` (RESERVING D10) also
  returns, and writes as one `participants_left` event, the unbought group
  gifts the user left that still have participants; and deletes the user's
  `gift_follows` in that occasion (in every occasion for account deletion,
  where the cascade would do it anyway). Bought group gifts lose the pledge
  as today and are listed too (their other participants are still giving
  it). The leaver's name is read at send time: after an account deletion the
  `actor_id` is null and the email says "a participant left", nothing that
  identifies them (NEEDS, Deleting an account).
- **D15 — Email digests: at most one email per person and gift every 15
  minutes.** New table `email_digests`: `id` (UUID), `user_id` (FK `users`
  `ON DELETE CASCADE`), `occasion_id` (FK `occasions` `ON DELETE CASCADE`),
  `gift_id` (UUID, no FK), `status` (`pending` | `sending` | `sent` |
  `skipped` | `failed`), `send_after`, `attempts`, `next_attempt_at`,
  `claimed_at` (when a worker took it to send), `sent_at`, `skip_reason`
  (a fixed word), `created_at`; partial unique index (`user_id`,
  `occasion_id`, `gift_id`) where `status = 'pending'`; index (`status`,
  `send_after`).
  - **Grouping.** A new notification attaches to the pending digest of its
    (person, occasion, gift), or creates one with `send_after = max(now + 1
    minute, last + 15 minutes)`, where `last` is the latest `claimed_at` of
    that key. The minute lets an owner who saves twice in a row cause one
    email; the 15 minutes are NEEDS's rule. The email lists every
    notification attached, oldest first: the fields changed (merged), each
    comment with its author and current text (a comment deleted since is
    left out, one edited since shows its current text), who left, or that the
    gift was deleted (then nothing else about it). A digest whose items
    all vanished is `skipped` (`empty`).
  - **At send time** the digest is skipped, with its reason, when: the
    person is no longer a giver of the occasion (`not_giver`, D11); their
    email notifications are off (`opted_out`); email is not configured
    (`not_configured`, D19); outside production, the address is not in
    `EMAIL_ALLOWED_RECIPIENTS` (`not_allowed`, D19). Skipped digests keep
    their notifications, so a later push channel is not affected.
  - **Sending at most once.** A worker claims a due digest with `SELECT …
    FOR UPDATE SKIP LOCKED`, sets `status = sending` and `claimed_at`, and
    commits before calling Brevo. On Brevo's 2xx it sets `sent`. On a
    definite refusal before acceptance (connection refused, DNS failure,
    HTTP 429 or 5xx) it goes back to `pending` with `next_attempt_at` after
    1, 5, 30, 120 and 720 minutes, then `failed` after the sixth attempt. On
    an ambiguous outcome (a timeout after the request was sent, an
    unexpected 2xx body) or a `sending` row found after a crash (older than
    10 minutes), it becomes `failed` with reason `unknown`, never resent:
    a duplicate email is worse than a missing one, and Brevo's transactional
    API offers no idempotency key we rely on (Open decisions). Other 4xx are
    `failed` at once (a bad address, a bad key) and logged.
  - Rules out per-notification emails (NEEDS) and a fixed digest schedule
    (the first notice would wait up to 15 minutes for nothing).
- **D16 — The worker.** `NotificationWorker` in
  `server/app/notifications/worker.py`, shaped like `MediaPurge`: a daemon
  thread started in the lifespan (always, unless `NOTIFICATIONS_WORKER=false`;
  test apps set it false and call `run_once` directly), stopped before the
  engine is disposed. Every 15 seconds `run_once(session_factory, mailer,
  config, now)`:
  1. fan-out: up to 100 `pending` events due, `FOR UPDATE SKIP LOCKED`,
     each in its own transaction (notifications inserted `ON CONFLICT DO
     NOTHING`, digests attached, `status = done` and `processed_at` set); a
     failing event backs off and ends `failed` after five attempts (D9);
  2. send: up to 50 due digests, as D15;
  3. sweep (D13), then retention: events `done` or `failed`, and digests finished
     (`sent`, `skipped`, `failed`), more than 30 days ago are deleted with
     their notifications.
  `SKIP LOCKED` and the unique keys make two app processes running at once
  (a `docker compose up -d` recreating the container, two uvicorn workers)
  safe: each event is fanned out once, each digest sent at most once. One
  `INFO` log line per run that did something, with counts only; no email
  address, name or comment text is ever logged.
- **D17 — Language.** `users.language` (`varchar(2)`, `en` | `fr`, check
  constraint, default `en`). The client reports the language it displays
  (D20) through `PATCH /api/me/preferences {"language": "fr"}` after sign-in
  and whenever it changes. Emails are written in the recipient's
  `language` at send time; strings live in
  `server/app/notifications/email_content.py`, one table per language with
  the same keys (tested). Rules out `Accept-Language` on every request (a
  write of the user row on every call, and mobile HTTP clients do not send
  the app's language reliably) and guessing from the email address.
- **D18 — Preferences and unsubscribing.** `users.email_notifications`
  (bool, default true, so existing accounts are opted in, NEEDS "on by
  default").
  - `GET /api/me/preferences` → `{"email_notifications": bool, "language":
    "en" | "fr"}`; `PATCH /api/me/preferences` with either field
    (`extra="forbid"`, 422 for another language). `GET /api/me` is unchanged.
  - **Unsubscribe token:** `v1.<user id, base64url>.<HMAC-SHA256(secret,
    "unsubscribe:v1:" + user id), base64url>`, secret `NOTIFICATION_SECRET`.
    It never expires (old emails must keep working, RFC 8058); it can do one
    thing: turn email notifications off for that account. Rotating the secret
    invalidates every link sent. Compared in constant time.
  - `POST /api/unsubscribe/{token}`, no session: 204 and
    `email_notifications = false` for a valid token (also when already off,
    and for a deleted account's well-formed token, so the answer says nothing
    about the account); 404 for a malformed or wrongly signed token, or when
    `NOTIFICATION_SECRET` is unset. Any body is accepted, so it serves as the
    RFC 8058 one-click target.
  - Every email carries `List-Unsubscribe: <PUBLIC_BASE_URL/api/unsubscribe/<token>>`
    and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (one click in
    the mail app), and a visible link to `PUBLIC_BASE_URL/unsubscribe#<token>`,
    a public client page with one button that calls the same route. Rules out
    a `GET` that unsubscribes: mail security scanners open links and would
    unsubscribe people who never clicked. The token is in a fragment on the
    page link, as join links are, so it stays out of access logs there.
- **D19 — Brevo, configuration and environments.** `BrevoMailer` in
  `server/app/notifications/mailer.py` calls Brevo's transactional email
  API (`POST https://api.brevo.com/v3/smtp/email`, `api-key` header) with
  httpx: a fixed host, 5 s connect and 10 s read timeouts, no redirects,
  typed outcomes (`sent`, `retry`, `unknown`, `rejected`) and no address,
  key or body in any exception or log. Held in `app.state.mailer`; tests
  replace it with a fake that records messages, so no test reaches Brevo.
  Settings, all from the environment, documented in both `.env.example`
  files without values:
  - `BREVO_API_KEY` (secret), `EMAIL_SENDER_ADDRESS`, `EMAIL_SENDER_NAME`
    (default `Wishlist`), `NOTIFICATION_SECRET` (secret, `openssl rand -hex
    32`), `EMAIL_ALLOWED_RECIPIENTS` (comma-separated addresses; read only
    when `APP_ENV` is not `production`), `NOTIFICATIONS_WORKER` (default
    true).
  - Email is sent only when `BREVO_API_KEY`, `EMAIL_SENDER_ADDRESS`,
    `NOTIFICATION_SECRET` and `PUBLIC_BASE_URL` are all set. Otherwise the
    worker still fans out, marks every due digest `skipped`
    (`not_configured`), and logs once at start which variables are missing,
    by name: DEV, tests and a VAL without a key work and never fail.
  - **VAL holds PROD's real addresses** (seeded from PROD). Outside
    production, only addresses listed in `EMAIL_ALLOWED_RECIPIENTS` are sent
    to; an empty list sends nothing. Rules out trusting VAL to have no key
    (one pasted key would email real users about test activity).
  - Links in emails are built on `PUBLIC_BASE_URL` (stripped of its trailing
    slash, as `/api/config` does): the gift in its occasion,
    `/shared/<occasion_id>?gift=<gift_id>` (D20), the account screen
    `/account`, and the unsubscribe links of D18. Since `PUBLIC_BASE_URL` is
    empty on VAL and PROD today, the owner sets it before email can work
    (U8's release step).
- **D20 — Client.**
  - **Thread in the gift sheet** (both the invitee's occasion screen and the
    "for someone else" owner's giver mode): under the participants and
    actions, "Comments" with the list (author, relative day and time,
    "edited", the text, selectable), "Deleted user" for a null author, a
    field with a 2000-character counter (code points) and "Send", and on my
    own comments "Edit" and "Delete" (delete asks for confirmation). A
    "Follow" / "Following" toggle in the sheet's header row. The thread loads
    when the sheet opens and reloads after each write or error, no
    optimistic state (RESERVING D13). Comments are not rose: rose stays for
    activity chips (`docs/DESIGN.md`). Nothing new on a "for me" owner's
    screens; the client never calls a comment route for them.
  - **Account screen:** an "Email notifications" switch (reads and writes
    `/api/me/preferences`; on failure, a snack bar and the switch goes back).
  - **Language report:** once signed in, the client sends
    `PATCH /api/me/preferences {"language": <displayed language>}` when the
    displayed language differs from the last one it reported for that user
    (kept in memory per app run); failures are ignored and retried at the
    next start.
  - **Unsubscribe page:** public route `/unsubscribe` (with `/welcome` and
    `/about` in `_publicPaths`), reading the token from the fragment, one
    button "Stop email notifications", then a confirmation that points to
    the account screen to turn them back on; an invalid link says so.
  - **Email deep link:** `/shared/<occasion_id>?gift=<gift_id>` opens the
    occasion and that gift's sheet; an owner of a "for someone else" list is
    sent to `/lists/<list_id>/occasions/<occasion_id>?gift=<gift_id>`, which
    does the same; a "for me" owner is sent to the list, without the sheet;
    an unknown gift opens the occasion only.
  - **Welcome copy** (completes the third card of RESERVING D15, which said
    nothing about comments):
    - `welcomeSurpriseBody`
      - EN: "Whoever a list is for never sees what was reserved, bought or
        said. The people you invite see who is giving what, talk it over
        under each gift, and can team up on a bigger gift."
      - FR: "La personne à qui la liste est destinée ne voit jamais ce qui a
        été réservé, acheté ou dit. Les personnes invitées voient qui offre
        quoi, en discutent sous chaque cadeau et peuvent se regrouper pour
        un cadeau plus important."
    If the hidden-gifts delivery changed this key, U4 merges both claims
    into one sentence pair and reports it.

## Review envelope

REVIEW.md defaults apply, with RESERVING_PLAN's envelope (the surprise as a
floor for every response a recipient can get, givers see each other,
concurrency, time), and these additions:

- **Notifications are part of the surprise floor.** A notification row,
  digest or email that names a recipient as its target, or that a recipient
  can tell apart by any channel (response, timing of their own request,
  email), is F1. The owner's `PATCH` and `DELETE /api/gifts/{id}` (dismiss
  of a revealed gift included) must do the same statements with the same
  row counts whatever the activity (D12). For `DELETE
  …/members/{user_id}` the floor is exactly one `participants_left` and
  one `gifts_removed` event row plus the per-claim release work RESERVING
  already accepted and the hidden-gift deletion HIDDEN_GIFTS_PLAN D8
  accepts;
  identical statements are not required of it. Lock waits of a few
  milliseconds stay out of the envelope, as in RESERVING. Other owner
  deletions (occasion, list, account), which cause no notification, keep
  the per-claim work RESERVING accepted; reducing it is not a finding of
  this plan.
- **Comments are givers' content.** Comment text is untrusted (E2): stored
  and returned as plain text, never interpreted by the server, escaped in
  every email.
- **A new external service: Brevo.** Outbound HTTPS to one fixed host with
  a secret API key. Its answers can be slow, wrong, missing or hostile (E2);
  it can accept a message and time out. Brevo receives, per email: the
  recipient's address and name, the gift title, the occasion name, other
  givers' names and comment text. That is the intended processing (NEEDS,
  Constraints: Brevo); sending more than that is a finding.
- **A new unauthenticated route:** `POST /api/unsubscribe/{token}`. Anyone
  can call it with any token. A forged or guessed token turning off someone's
  emails is F1; a valid token (from an email) doing so is the feature.
- **A background job.** One worker thread per app process. Two processes
  running at once (container recreation overlap, or two uvicorn workers)
  is in the envelope: no event fanned out twice, no digest sent twice. A
  process killed at any point is in the envelope: at most one email lost per
  digest it held (D15), nothing sent twice, nothing stuck forever.
- **Time.** Grouping and backoff use the API server's UTC clock; a clock
  moving back a few minutes delays emails, which is accepted.
- **Scale.** A few hundred users: an occasion has tens of givers; a thread
  has tens to hundreds of comments, read whole. The worker handles bursts
  in batches of 100 events and 50 digests per 15-second run. No rate limit on
  comments (Open decisions).
- **Out of the envelope:** email deliverability (spam folders, SPF and DKIM
  of the sender domain, the owner's Brevo set-up), push, and a recipient
  known only by name who joined through a forwarded link (NEEDS, accepted).

## Boundaries crossed

- **Schema (F4):** two migrations, both after the hidden-gifts head, both
  usable by the previous release (DevOps plan D15):
  1. U1: tables `comments` and `gift_follows` (new tables only).
  2. U3: tables `notification_events`, `notifications`, `email_digests`;
     columns `users.language` (default `en`) and `users.email_notifications`
     (default true), added with server defaults so the previous release's
     inserts still work; the foreign key `gift_claims.gift_id → gifts` and
     the check constraint `ck_gift_claims_occasion_id` are dropped (D13).
     **Rollback stays image-only (DevOps D15).** The previous release
     running on this schema deletes gifts without cascading their claims;
     the orphans are invisible to it (its reads join `gifts`), and when it
     then deletes the list or the account, the occasions' `SET NULL` meets
     no check constraint, so no 500; the orphans and the unbought claims
     left with no occasion are not live for it either (its `is_live`) and
     are swept once this release runs again. Tested by running the previous
     release's deletion paths (`delete_list`, `delete_me`) against this
     schema with an orphaned unbought claim (U3). Downgrade deletes orphaned
     claims and unbought claims with no occasion, then restores the foreign
     key and the check constraint, and drops the tables and columns.
- **API contract (F4):** new routes: the six of D5, `GET` and `PATCH
  /api/me/preferences`, `POST /api/unsubscribe/{token}`. No existing
  response changes shape or content. Endpoints whose behaviour grows, with
  the same answers: `PATCH` and `DELETE /api/gifts/{id}` (events),
  `POST …/reservation`, `POST …/bought`, `PUT …/pledge` (auto-follow),
  `DELETE …/membership`, `DELETE …/members/{user_id}`, `DELETE /api/me`
  (events, follows). Through `drop_gift_activity` (D13), keep, dismiss and
  a hidden gift's deletion no longer delete activity rows in the request;
  their answers are unchanged.
- **Emails are a contract with the past:** links in sent emails stay in
  inboxes. These must keep working in every later release:
  `POST /api/unsubscribe/{token}` with `v1` tokens, the client routes
  `/unsubscribe#<token>` and `/shared/<occasion_id>?gift=<gift_id>`.
  A later token format gets a new version prefix; `v1` stays accepted.
- **Stored data:** comments (givers' personal data, kept after the author
  leaves; unsigned after account deletion, as NEEDS decides), follows,
  notification events (gift titles of deleted gifts, comment ids),
  notifications and digests (kept 30 days after completion, D16). Account
  deletion removes follows, notifications and digests of that user and
  unsigns their comments and events. A later data-export plan must include
  comments and preferences.
- **Client:** new route `/unsubscribe` (public); a `gift` query parameter on
  `/shared/:occasionId` and `/lists/:id/occasions/:occasionId`. ARB key
  `welcomeSurpriseBody` changes text.

## Conventions

- Every new route has rows in `server/tests/lists/test_roles.py` (D5's
  routes: the "for me" owner and every non-giver get 404; the "for someone
  else" owner and the occasion's invitee succeed; signed out 401;
  `test_every_route_is_in_the_matrix` passes) and is called by the recipient
  in `server/tests/lists/test_surprise.py` (`test_every_route_is_called`
  passes). `ACTIVITY_KEYS` in both gains `comments`, `following`,
  `author_name`, `edited`.
- Activity tables reference gifts by id only, never by foreign key (D13);
  every read of them joins `gifts` or goes through `giving_gift`. Nothing
  relies on a cascade from `gifts`: a path that deletes a gift row other
  than `delete_gift` calls `drop_gift_activity` (HIDDEN_GIFTS_PLAN D15),
  whose activity rows the worker's sweep removes; tests assert
  unreachability through the API, never that rows were deleted.
- An owner's request that can cause a notification writes a fixed number of
  event rows decided by the owner's input alone (D12); who is notified is
  only ever computed by the worker.
- Every fan-out and every send checks the target is a giver now (D11, D15).
- Comment, follow and notification writes never write `gifts`, `lists` or
  `occasions` (RESERVING D3).
- Response models list their fields explicitly; no user id in a comment or
  thread response.
- No email address, display name, comment text, token or API key in any log
  line or exception message.
- Tests never reach Brevo: `app.state.mailer` is a fake in every test, and
  `make_client` sets `notifications_worker=False`. Worker tests call
  `run_once` with an explicit clock.
- Tests that depend on an occasion not having passed date it relative to
  today (RESERVING Conventions).
- Every user-visible string in both ARB files, sentence case, no emoji;
  goldens light and dark regenerated with `.\goldens.ps1` only (Linux).
- Units with schema, the surprise, an unauthenticated route or the worker
  (U1, U3, U5, U7) get a unit review before integration (DELIVERY §5,
  point 3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Brevo account: a key of TraxJourney's Brevo account or Wishlist's own, the sender address and its verified domain (SPF, DKIM) | Deliverability, U8 runbook | Before email is turned on in VAL |
| Brevo idempotency: if its transactional API accepts an idempotency key, ambiguous outcomes (D15) can be retried instead of failed | Lost emails on timeouts | Revisit if `unknown` failures show in the logs |
| A cap or rate limit on comments per thread or per person | Abuse by a giver; the owner can remove them today | Revisit on abuse |
| A comment count or "new" marker on the gift cards of the occasion screen | Client, one more read route | Revisit on user feedback |
| Notifications when an owner deletes an occasion or a list, or marks a gift received (not notified for now, NEEDS) | NEEDS | Revisit on user feedback |
| Push: device tokens and a push delivery table on `notifications` (D11) | Mobile release | The mobile release plan |
| Retention of 30 days for finished notifications and digests (D16) | Stored data, support questions | Revisit with the data-export plan |

## Execution units

### Wave 1

#### U1 — Server: comment threads and following

- **Goal:** Givers read, post, edit and delete comments under a gift in an
  occasion and follow or unfollow it; recipients and strangers get the
  random-id 404 on every route.
- **Scope:** `server/app/comments/**` (new: `__init__.py`, `models.py`,
  `schemas.py`, `router.py`, `follows.py`), `server/app/lists/access.py`
  (add `giving_gift`), `server/app/reserving/router.py` (use `giving_gift`
  instead of `_giving_gift`, nothing else), `server/app/main.py` (include
  the router), `server/alembic/env.py` (import the models),
  `server/alembic/versions/**` (one new revision), `server/tests/lists/**` (new
  `test_comments.py`, `test_follows.py`, `test_concurrent_comments.py`;
  `test_roles.py` and `test_surprise.py` extended).
- **Context:** this plan D1–D8, Conventions; RESERVING_PLAN D3, D4, D7;
  `server/app/reserving/router.py` and `schemas.py` as the example to
  follow (giver routes, explicit models, `mine` instead of user ids);
  `server/alembic/versions/33d8218ddbae_reserving.py` as the example of a
  new-tables revision; `server/tests/lists/test_reservations.py`,
  `test_concurrent_reservations.py` and `locks.py` for tests.
- **Do:**
  1. `comments/models.py`: `Comment`, `GiftFollow` per D1, D4 (no FK to
     `gifts`); register in `alembic/env.py`; one revision whose
     `down_revision` is the single head the hidden-gifts delivery left.
  2. `access.py`: `giving_gift` per D6, moved from `reserving/router.py`
     with its behaviour after the hidden-gifts delivery, plus `lock=False`;
     the claims routes call it unchanged.
  3. `comments/follows.py`: `auto_follow(db, occasion_id, gift_id,
     user_id)` (insert, `ON CONFLICT DO NOTHING`), `set_following(…, bool)`
     (upsert), `drop_follows(db, user_id, occasion_id | None)`; U3 uses
     them.
  4. `comments/schemas.py`, `comments/router.py`: D5's six routes; D2's
     validation (422 for empty, too long, NUL and control characters); D7's
     locks; posting follows the author.
  5. `test_roles.py`: rows for the six routes; the scenario gains a comment
     by the first occasion's invitee on a gift of each list and a follow;
     `owners_view` records the thread as that invitee sees it, so refused
     calls are shown to change nothing; `ACTIVITY_KEYS` per Conventions.
  6. `test_surprise.py`: `STATES` gains "commented" (a thread with two
     comments, one edited, one by a since-removed invitee, followers);
     the recipient calls D5's routes (404, the random-id body) so
     `test_every_route_is_called` passes; the world against control and twin
     comparisons hold for the new state.
  7. `test_comments.py`: post, read (order, `mine`, `edited`), edit by the
     author, edit or delete of someone else's → 404, delete → gone; 2000
     code points accepted (including emoji counted as one), 2001 → 422,
     whitespace-only → 422, NUL → 422, `extra` field → 422; a comment of
     another thread's id → 404; the invitee of another occasion → 404; the
     "for someone else" owner comments and the invitee sees their name; a
     removed author keeps their name; a deleted account → `author_name`
     null and nothing else changes; a passed occasion accepts comments; a
     received gift → 404, and back with its thread when put back; a hidden
     gift of this occasion has a thread, of another occasion → 404; after
     "keep", the kept gift's thread is empty and the old id answers 404 on
     every route (unreachability through the API, D8); a deleted gift → 404
     on every route.
  8. `test_follows.py`: follow, unfollow, idempotent; posting follows;
     posting after an explicit unfollow stays unfollowed; the follow state
     in `GiftThread`.
  9. `test_concurrent_comments.py`: a comment racing the author's removal
     and the gift's deletion (barrier and held transaction, `locks.py`) →
     201 or 404, never 500.
- **Acceptance:** `uv run --directory server ruff check`;
  `uv run --directory server alembic upgrade head` then `alembic check`;
  `uv run --directory server pytest` passes, including the tests of Do 5–9,
  `test_every_route_is_in_the_matrix`, `test_every_route_is_called`, and the
  hidden-gifts delivery's `test_hidden_gifts.py` and `test_received.py`.
- **Out of scope:** auto-follow from claim routes and follows dropped on
  leave (U3), events and notifications (U3, U7), dropping the claims FK
  (U3), any client change.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the hidden-gifts
  delivery left more than one Alembic head, or no single gift-in-occasion
  check to move; a recipient response would have to change.
- **Depends on:** the hidden-gifts plan delivered on this branch.

#### U2 — Client: the comment thread and follow toggle in the gift sheet

- **Goal:** Givers read, write, edit and delete comments and follow or
  unfollow a gift from its sheet.
- **Scope:** `client/lib/src/shared/shared_repository.dart`,
  `client/lib/src/shared/gift_sheet.dart`,
  `client/lib/src/shared/gift_thread.dart` (new),
  `client/lib/src/shared/occasion_screen.dart`,
  `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/test/shared/**`, `client/test/lists/support/fake_lists_server.dart`,
  `client/test/lists/giver_mode_test.dart`.
- **Context:** this plan D2, D3, D5 (the contract U1 builds in parallel),
  D20 (thread, follow toggle); `docs/DESIGN.md` (Components, Invitee
  colour). Example to follow: the participants block and actions of
  `gift_sheet.dart`, with `client/test/shared/occasion_activity_test.dart`
  and `shared_golden_test.dart`.
- **Do:**
  1. Repository: `GiftThread`, `Comment` models; `thread`, `comment`,
     `editComment`, `deleteComment`, `follow`, `unfollow`.
  2. Fake server: threads per (occasion, gift) and D5's routes with the
     server's rules (author-only edit and delete, 404 otherwise, 2000 code
     points, follow on post, sticky unfollow), and the request log.
  3. `gift_thread.dart`: the thread widget per D20; the sheet shows it and
     the follow toggle; loads when the sheet opens, reloads after each write
     or error; a failure shows a snack bar.
  4. ARB strings EN and FR: section title, empty thread, field hint,
     counter, send, edit, delete and its confirmation, "edited", "Deleted
     user", follow and following, errors.
  5. Tests: repository calls (method, path, body); posting, editing,
     deleting my own; no edit or delete on others' comments; "edited" and
     "Deleted user" shown; the counter at 2000 and refusal past it; follow
     toggle calls the right route; giver mode on a "for someone else" list
     shows the thread; on a "for me" list, no request to any comment route
     (fake server's log). French run of the thread. Goldens light and dark:
     the sheet with a thread (mine, others', edited, deleted user), the
     empty thread, the edit state.
- **Acceptance:** `flutter analyze`; `flutter test` (ARB parity included);
  the tests of Do 5; goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** account screen, unsubscribe page, deep links, welcome
  copy (U4); comment counts on gift cards (Open decisions).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the sheet needs a
  layout change beyond adding the thread and the toggle.
- **Depends on:** the hidden-gifts plan's client units (they touch the same
  sheet).

### Wave 2

#### U3 — Server: the outbox, auto-follow, and gift deletion without cascades

- **Goal:** Every cause of D10 writes its event in its own transaction,
  claim routes follow, givers going away drop their follows, and deleting a
  gift does the same work whatever its activity.
- **Scope:** `server/app/notifications/**` (new: `__init__.py`,
  `models.py`, `events.py`), `server/app/accounts/models.py` (the two
  columns only), `server/app/reserving/models.py` (`GiftClaim` only: drop
  the `gifts` foreign key and the `occasion_id` check constraint with its
  comment), `hidden_gifts/lifecycle.py` (`delete_unbought_by` returns the
  deleted gifts' ids and titles, nothing else),
  `server/app/reserving/release.py` (`release_activity` and the body of
  `drop_gift_activity`), `server/app/reserving/router.py`
  (auto-follow calls only), `server/app/lists/router.py` (`update_gift`,
  `delete_gift`, `remove_member` only), `server/app/comments/router.py` (the event on post
  only), `server/alembic/env.py`, `server/alembic/versions/**` (one new
  revision), `server/tests/lists/claims_invariants.py`,
  `server/tests/lists/**` (new `test_notification_events.py`,
  `test_owner_work.py`, `test_previous_release_on_schema.py`; existing
  release and deletion tests extended; `test_hidden_gifts.py` and
  `test_received.py` only where a test reads activity rows directly instead
  of through the API), `server/tests/test_migrations.py` (the downgrade
  case).
- **Context:** this plan D8–D14, Conventions; RESERVING D7, D10, D11 and its
  review R1-1 (the `SET NULL` failure); HIDDEN_GIFTS_PLAN D6, D15 (the
  hook's contract); DEPLOYMENT.md Rollback (image-only rollback); `server/app/reserving/release.py` as
  the example for writes inside an existing transaction; the revision of
  U1 as the example revision.
- **Do:**
  1. `notifications/models.py`: `NotificationEvent`, `Notification`,
     `EmailDigest` (D9, D11, D15); `User.language`,
     `User.email_notifications` (D17, D18). One revision: the tables, the
     columns with server defaults, the FK and check-constraint drops (D13);
     downgrade per Boundaries crossed.
  2. `notifications/events.py`: one function per kind, each inserting one
     row.
  3. `update_gift`: compare D10's fields before and after; write
     `gift_changed` with the changed names when any changed and the gift is
     not revealed (`for_list_id` null). `delete_gift`: unless revealed,
     write `gift_deleted` with the title and `received`; then delete the gift
     row (D10).
  4. `release.py`: `release_activity` collects the group gifts left that
     still have participants (bought ones too), only those whose claim is
     live (`rules.is_live(now)`), writes one `participants_left` per call
     (empty list included) and calls
     `drop_follows`. `drop_gift_activity`: its body deletes nothing (D13);
     docstring states its contract and that the sweep removes the rows.
     `remove_member`: after the release and HIDDEN_GIFTS_PLAN D8's
     `delete_unbought_by`, write one `gifts_removed` with the ids and titles
     it returned (empty list included).
  5. Claims routes: `auto_follow` on reserve, mark bought from free, start
     or join a group gift. Comment post: `comment_added`.
  6. `claims_invariants.py`: orphaned claims and unbought claims with no
     occasion allowed per D13; every other check unchanged.
  7. `test_notification_events.py`: each cause writes exactly its row and
     payload; an edit changing no notified field (or only an unnotified
     one) writes none; leave, removal and account deletion each write one
     `participants_left`, with and without group gifts; a group gift of a
     passed occasion (claim expired) is not listed, a live one is; a removal
     writes one `gifts_removed` with the titles of the removed author's
     unbought hidden gifts, and an empty one when there are none; follows
     dropped on
     leave and removal; auto-follow per route, sticky unfollow respected;
     a deleted gift's claim, comments and follows remain, unreachable, and
     every claims and comment read ignores them; a gift deleted, then its
     list deleted (and its owner's account deleted) before any worker run
     → 204, `assert_claims_consistent`; a revealed gift edited or dismissed
     writes no event, with and without a thread and followers; deleting a
     received gift writes `received: true`; keep, dismiss and a hidden
     gift's deletion leave the rows and nothing is reachable through the
     API.
  8. `test_owner_work.py`: a SQLAlchemy `after_cursor_execute` listener
     records statements (parameters stripped of ids, through the twin
     renaming of `test_surprise.py`) and row counts; the owner's `PATCH` and
     `DELETE /api/gifts/{id}` on G1 with each activity (reserved, bought,
     group with pledges, commented and followed, taken elsewhere) and on its
     twin G2 with none record identical sequences; the same for a revealed
     gift's edit and dismissal (twin revealed gifts, one with a thread and
     followers, one without). `DELETE …/members/{user_id}` on an invitee
     with and without group gifts and hidden gifts writes exactly one
     `participants_left` and one `gifts_removed` row each time (statements
     not compared: its release and hidden-gift deletion are accepted
     per-row work, D12). A schema test: no foreign key
     from `gift_claims`, `claim_participants`, `comments`, `gift_follows`,
     `notification_events`, `notifications`, `email_digests` to `gifts`.
  9. `test_migrations.py`: upgrade then downgrade with an orphaned claim
     and an unbought claim with no occasion present succeeds.
  10. `test_previous_release_on_schema.py`: on this schema, an orphaned
      unbought claim (gift deleted with no worker run), then the list
      deleted and an account deleted through the code paths as the previous
      release has them (`delete_gift_claims` and the cascades, with the
      hook's old body) → no error, and claims reads stay correct (R1-1).
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`;
  `pytest` passes, including the tests of Do 7–10, every existing
  reserving, deletion, `test_roles.py` and `test_surprise.py` test, and the
  hidden-gifts delivery's `test_hidden_gifts.py`, `test_received.py` and
  `assert_claims_consistent` wherever it is called.
- **Out of scope:** fan-out, digests, sending, the sweep (U7); preferences
  and unsubscribe routes (U5); events for hidden-gift author edits (not
  notified, NEEDS).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a read of
  `gift_claims`, `comments` or `gift_follows` exists that does not join
  `gifts` or go through `giving_gift`; a caller of `drop_gift_activity`
  keeps the gift row it names; an owner's gift edit or deletion cannot be
  made to record identical statements; an existing answer would have to
  change.
- **Depends on:** U1.

#### U4 — Client: email switch, language report, unsubscribe page, deep links, welcome copy

- **Goal:** The account screen turns email notifications on and off, the
  server learns the app's language, email links open the right gift, the
  unsubscribe link works signed out, and the welcome page mentions comments.
- **Scope:** `client/lib/src/auth/account_screen.dart`,
  `client/lib/src/auth/preferences_repository.dart` (new),
  `client/lib/src/auth/language_report.dart` (new), `client/lib/main.dart`
  (hook the language report only), `client/lib/src/app_router.dart`,
  `client/lib/src/unsubscribe/unsubscribe_screen.dart` (new),
  `client/lib/src/shared/occasion_screen.dart` (the `gift` parameter only),
  `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/test/auth/**`, `client/test/unsubscribe/**` (new),
  `client/test/app_router_test.dart`, `client/test/shared/**`,
  `client/test/support/fakes.dart`, `client/test/welcome/**`,
  `client/test/goldens/**`.
- **Context:** this plan D17, D18, D20; WEB_LAYOUT_PLAN D6 (public paths)
  and D8; RESERVING D15. Examples to follow: `JoinScreen` and
  `join_browser_web.dart` for a page reading a token from the fragment,
  `account_screen.dart` and `client/test/auth/account_screen_test.dart`,
  `authRedirect` and its tests in `app_router_test.dart`.
- **Do:**
  1. `preferences_repository.dart`: `GET` and `PATCH /api/me/preferences`;
     `unsubscribe(token)` → `POST /api/unsubscribe/<token>` without a
     session.
  2. Account screen: the "Email notifications" switch per D20.
  3. `language_report.dart`: per D20, hooked under `MaterialApp` so it
     reads the displayed locale; nothing sent while signed out.
  4. `/unsubscribe` public route and screen per D18, D20.
  5. `gift` query parameter: `/shared/:id?gift=` opens that gift's sheet
     once the claims are loaded; the redirect of a "for someone else" owner
     keeps it on `/lists/:id/occasions/:occasionId`; a "for me" owner goes
     to the list without it.
  6. Welcome: `welcomeSurpriseBody` per D20, EN and FR.
  7. Tests: switch reads, writes, reverts on failure; the language is
     reported once after sign-in, again after a locale change, never signed
     out; `/unsubscribe` reachable signed out, the button calls the route,
     success, invalid link; `authRedirect` lets `/unsubscribe` through; the
     deep link opens the sheet for an invitee and a "for someone else"
     owner, the list for a "for me" owner; welcome texts in both languages.
     Goldens light and dark: account screen with the switch, unsubscribe
     page before and after, welcome (regenerated).
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 7;
  goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** the thread (U2); push; a language picker in the app.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the router cannot
  keep the token in the fragment through the sign-in guard; the
  hidden-gifts delivery changed `welcomeSurpriseBody` in a way the new
  sentence cannot include.
- **Depends on:** U2 (ARB files, occasion screen).

### Wave 3

#### U5 — Server: preferences and the unsubscribe route

- **Goal:** Users read and change their email switch and language; a signed
  unsubscribe token turns email off without a session; forged tokens get
  404.
- **Scope:** `server/app/notifications/router.py` (new),
  `server/app/notifications/unsubscribe.py` (new), `server/app/settings.py`
  (`notification_secret` only), `server/app/main.py` (include the router),
  `server/tests/notifications/conftest.py`,
  `server/tests/notifications/test_preferences.py`,
  `server/tests/notifications/test_unsubscribe.py` (all new),
  `server/tests/lists/test_surprise.py` (the recipient calls the three
  routes).
- **Context:** this plan D17, D18, Review envelope (unauthenticated route);
  `server/app/accounts/router.py` and `schemas.py` as the example for
  `/api/me` routes; `server/tests/accounts/test_sessions.py` for token
  tests.
- **Do:**
  1. `unsubscribe.py`: `make_token(secret, user_id)`,
     `read_token(secret, token) -> UUID | None` (format check, constant-time
     compare, `v1` only).
  2. `router.py`: `GET` and `PATCH /api/me/preferences`
     (`extra="forbid"`, `language` in `en`, `fr`); `POST
     /api/unsubscribe/{token}` per D18 (any body; 404 when the secret is
     unset). The user row is updated, never locked beyond the auth
     dependency's lock.
  3. Tests: defaults for an existing account (`true`, `en`); patch each
     field; 422 for `de` and extra fields; 401 signed out; a valid token →
     204 and off, twice → 204, a deleted account's token → 204; a token
     with a changed user id, signature, version or length → 404; secret
     unset → 404; the RFC 8058 form body accepted; the response does not
     differ between an existing and a deleted account.
  4. `test_surprise.py`: the recipient calls the three routes, so
     `test_every_route_is_called` passes.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including the tests of Do 3 and
  `test_every_route_is_called`.
- **Out of scope:** sending email, the worker (U7), client (U4).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the token needs a
  database column.
- **Depends on:** U3 (the user columns).

#### U6 — Server: the Brevo mailer and email content

- **Goal:** A digest's content renders as a subject, HTML and text email in
  English or French, and a mailer sends one message to Brevo with typed
  outcomes and no secret or address in logs.
- **Scope:** `server/app/notifications/mailer.py` (new),
  `server/app/notifications/email_content.py` (new),
  `server/tests/notifications/test_mailer.py` (new),
  `server/tests/notifications/test_email_content.py` (new).
- **Context:** this plan D15 (what an email lists), D17, D18 (headers and
  links), D19; `server/app/safe_fetch.py` and `server/tests/test_safe_fetch.py`
  as the example for outbound HTTP with typed errors and a recording
  transport (no network in tests).
- **Do:**
  1. `email_content.py`: input dataclasses (recipient name, language,
     occasion name, gift title, links, items: fields changed, comments with
     author name or null, participants left with name or null, gift
     deleted, hidden gift removed with its title); `render(...) -> EmailMessage` (subject, HTML, text, headers);
     strings in an EN and an FR table with the same keys; every value HTML-
     escaped; no external images, no tracking.
  2. `mailer.py`: `BrevoMailer(api_key, sender_address, sender_name,
     transport=None)`, `send(to_address, to_name, message) -> Outcome`
     (`sent`, `retry`, `unknown`, `rejected`) per D15, D19; 5 s connect,
     10 s read, no redirects.
  3. Tests: each item kind in both languages (golden text files under
     `server/tests/notifications/emails/`); key parity of the two tables;
     escaping of `<script>` in a comment and a gift title; the headers of
     D18; "Deleted user" and "a participant" wording; mailer against an
     `httpx.MockTransport`: the request's URL, headers, JSON; 201 → `sent`,
     429 and 503 → `retry`, connect error → `retry`, read timeout →
     `unknown`, 400 and 401 → `rejected`; no key, address or body in any
     exception text or captured log.
- **Acceptance:** `ruff check`; `pytest` passes, including the tests of
  Do 3.
- **Out of scope:** choosing what goes in a digest, when to send, settings
  and wiring (U7).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); Brevo's API needs
  something D19 does not describe.
- **Depends on:** —

#### U8 — Infrastructure: environment variables and the owner's steps

- **Goal:** The VPS runbook and the `.env` examples say how to turn email on
  in VAL and PROD, with no value committed.
- **Scope:** `deploy/prod/.env.example`, `deploy/val/.env.example`,
  `docs/DEPLOYMENT.md`, `docs/DEVELOPMENT.md`.
- **Context:** this plan D18, D19; the `GOOGLE_CLIENT_IDS` and
  `PUBLIC_BASE_URL` blocks of the `.env.example` files and DEPLOYMENT.md
  steps 5, 6 and "Release-specific steps" as the examples to follow.
- **Do:**
  1. Both `.env.example`: `BREVO_API_KEY=`, `EMAIL_SENDER_ADDRESS=`,
     `EMAIL_SENDER_NAME=Wishlist`, `NOTIFICATION_SECRET=` with how to
     generate it, and in VAL's only `EMAIL_ALLOWED_RECIPIENTS=` with why
     (VAL holds PROD's addresses); each says what happens when empty.
  2. DEPLOYMENT.md: placeholders `<brevo-api-key>`,
     `<sender-address>`; a "Release-specific steps" entry for the release
     with notifications: check `PUBLIC_BASE_URL` is set in both `.env`
     (the commands of step 6; email stays off without it), generate
     `NOTIFICATION_SECRET` per environment (never shared, never rotated
     without reason: it invalidates every unsubscribe link), the Brevo key
     and verified sender, VAL's allow-list with the owner's own address,
     `docker compose up -d`, and how to check: a comment on VAL reaches the
     allowed address; the log line naming missing variables is gone.
  3. DEVELOPMENT.md: DEV sends no email unless the variables are set; how
     to try one against an allow-listed address.
- **Acceptance:** the `deploy-smoke` workflow passes; `grep` finds no host,
  address or key in the changed files; every variable of D19 appears in
  both examples (the allow-list in VAL's only) and in DEPLOYMENT.md.
- **Out of scope:** server code; Brevo account set-up itself (the owner's,
  Open decisions); DNS for the sender domain.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed (X3); the compose files
  need a change.
- **Depends on:** —

### Wave 4

#### U7 — Server: the notification worker

- **Goal:** Events become notifications for current givers, grouped into at
  most one email per person and gift every 15 minutes, sent at most once
  through the mailer, with retries, a sweep of deleted gifts' activity and
  retention, safe with two processes.
- **Scope:** `server/app/notifications/worker.py` (new),
  `server/app/notifications/fanout.py` (new),
  `server/app/notifications/digests.py` (new), `server/app/lists/access.py`
  (`giver_condition` only), `server/app/settings.py` (D19's settings but
  `notification_secret`), `server/app/main.py` (lifespan and
  `app.state.mailer`), `server/tests/conftest.py` (`make_client`:
  `notifications_worker=False`, a fake mailer), `server/tests/notifications/**`
  (new: `test_fanout.py`, `test_digests.py`, `test_worker.py`,
  `test_concurrent_worker.py`).
- **Context:** this plan D11, D13, D15, D16, D19, Review envelope;
  `server/app/media/purge.py` (`MediaPurge`, one transaction per step, the
  log line) and `server/tests/media/test_purge.py` as the examples to
  follow; `server/tests/lists/locks.py` for concurrency helpers.
- **Do:**
  1. `access.py`: `giver_condition(user_id, occasion_id)` as a SQL
     expression equal to `giving_occasion`'s rule; a test compares the two
     on every role of the `test_roles.py` scenario.
  2. `fanout.py`: D11 per kind, `SKIP LOCKED`, `ON CONFLICT DO NOTHING`,
     digest attach per D15, backoff on failure.
  3. `digests.py`: claim, check at send time, render through U6's
     `email_content`, unsubscribe links through U5's `make_token`, send
     through `app.state.mailer`, outcomes and backoff per D15.
  4. `worker.py`: `run_once` (fan-out, send, sweep, retention) and
     `NotificationWorker` per D16; the start-up log naming missing
     variables.
  5. `settings.py`, `main.py`: D19's settings; the mailer built when
     configured, else none; the worker started unless
     `notifications_worker` is false.
  6. Tests, with an explicit clock and the fake mailer:
     - fan-out per kind: participants (bought included), followers minus
       the author, other participants after a leave; nobody for a received
       gift, a `gift_deleted` whose payload says received, a deleted
       comment, a gift without claim, an expired unbought claim (its
       occasion passed before the event, for `gift_changed` and
       `gift_deleted`; a claim that expires between the event and the
       fan-out is still notified); the actor never, including the owner of
       a "for someone else" list who also reserved; a claim with no
       occasion → event `done`, reason `no_occasion`, no row; an event
       whose fan-out raises five times → `failed`, logged, not retried, and
       the sweep proceeds for its gift; a removal deleting the removed
       author's unbought hidden group gift that others pledged on → its
       other participants get one "removed" notification with the captured
       title, the same removal's `participants_left` skips that gift and
       still notifies the leaver's other group gifts, the claim rows are
       swept only after; a `gifts_removed` gift with no claim rows → nobody,
       the event `done`; a removed invitee, a
       recipient, a co-owner of a "for me" list who was a member, and a
       "for someone else" list's owner (a giver: notified) — no row ever for
       a non-giver; fanning out the same event twice inserts nothing twice;
     - grouping: first email after the settle minute, later notifications
       wait for 15 minutes after the last claim, one email lists all of
       them; separate gifts and separate occasions get separate emails;
     - send-time checks: opted out, no longer a giver, not configured, not
       in the allow-list outside production, allow-list ignored in
       production; language EN and FR; `List-Unsubscribe` headers and links
       on `PUBLIC_BASE_URL`;
     - outcomes: `retry` backs off 1, 5, 30, 120, 720 minutes then
       `failed`; `unknown` and a stale `sending` → `failed`, never resent;
       `rejected` → `failed`;
     - sweep: a deleted gift's claim, participants, comments and follows go
       after its `gift_deleted` fan-out, not before; retention after 30 days;
       account deletion removes the user's notifications and digests;
     - `test_concurrent_worker.py`: two `run_once` in parallel threads over
       100 events and their digests, 20 rounds → every event fanned out
       once, every digest sent once (the fake mailer counts);
     - lifespan: the worker starts and stops with the app when enabled, not
       when disabled.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including the tests of Do 6 and every
  existing test.
- **Out of scope:** push; preferences routes (U5); email wording (U6).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a schema change is
  needed; a target cannot be decided without per-request work in an owner's
  request.
- **Depends on:** U3, U5, U6.

### Wave 5

#### U9 — Server: no notification reaches the recipient, end to end

- **Goal:** A suite proves that, for every activity state, the recipient's
  account never gets a notification, digest or email, the owner's requests
  record the same work, and the recipient's answers are unchanged by
  comments and notifications.
- **Scope:** `server/tests/lists/test_surprise.py`,
  `server/tests/lists/test_owner_work.py`. Server code only if a test
  fails, through X3.
- **Context:** this plan D11, D12, D15, Review envelope; the existing
  `test_surprise.py` (`build`, `Recorder`, world against control) and U3's
  `test_owner_work.py` as the examples to follow.
- **Do:**
  1. After each world and control is built and the recipient's calls run,
     `run_once` the worker (fake mailer, configured, clock moved past the
     grouping window): no `notifications` or `email_digests` row and no
     email for the recipient (the owner, and the co-owner who was a member)
     in any state; the "for someone else" owner, a giver, does get them in
     the states that notify, so the check is not vacuous.
  2. The recipient's own answers after the worker ran equal the control's
     (world against control), so nothing the worker writes leaks into an
     owner response.
  3. `test_owner_work.py`: the statement comparison runs for every state of
     `STATES`, including "commented".
- **Acceptance:** `ruff check`; `pytest` passes with the extended suites;
  no server file changed, or each change escalated and approved (X3).
- **Out of scope:** push.
- **Latitude:** local design.
- **Escalate if:** any comparison fails (an F1 finding: report it, do not
  fix it inside this unit); a file outside Scope is needed (X3).
- **Depends on:** U7.

## Definition of done

- On VAL, two invitees of one occasion open the same gift; one comments, the
  other sees the comment with its author, replies, edits it ("edited") and
  deletes it (gone). The owner of the "for me" list sees nothing and gets
  404 from every comment route.
- Invitees of a second occasion of the same list never see that thread; a
  hidden gift has its own thread in its occasion.
- A removed invitee's comments keep their name; after an account deletion
  they read "Deleted user".
- An invitee who reserved a gift receives, at an allow-listed address on
  VAL, one email in their app language when the owner changes its price,
  and one listing both changes when the owner changes the title twice within
  15 minutes; one when the owner deletes it.
- A follower receives an email for a new comment; its author does not; an
  invitee who unfollowed does not, even after commenting again.
- The other participants of a group gift receive an email when a
  participant leaves the occasion, is removed or deletes their account.
- Each email has a working unsubscribe link and `List-Unsubscribe` headers;
  after unsubscribing, the account screen shows the switch off and no
  further email arrives; turning it on again resumes emails.
- No recipient is ever the target of a notification, digest or email
  (`test_surprise.py`, `test_fanout.py`); the owner's gift edit, gift
  deletion and member removal record the same statements and row counts
  whatever the activity (`test_owner_work.py`).
- With `BREVO_API_KEY` unset (DEV, CI, a VAL without key), everything works
  and digests are marked skipped; on VAL, no address outside the
  allow-list is ever sent to.
- Two app processes running together send each email at most once
  (`test_concurrent_worker.py`).
- The welcome page mentions comments in English and French.
- All DELIVERY.md §2 checks pass on server, client and infrastructure,
  goldens included.
