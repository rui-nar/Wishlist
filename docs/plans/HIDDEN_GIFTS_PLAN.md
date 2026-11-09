# Occasion lifecycle and hidden gifts

## Problem

Two needs of `docs/NEEDS.md`, both decided on 2026-11-09, have no code yet:

- **After an occasion** (Lists and occasions): the owner cannot say which
  gifts they received. A gift bought for last Christmas stays "taken" for
  every later occasion (RESERVING_PLAN D8, D11) until the owner deletes it,
  which loses it for good. NEEDS wants a **received** marking, offered the
  same way on every gift so it says nothing about which ones were bought,
  that takes the gift off the list and out of every occasion, into a
  "Received" place where it can be put back exactly as it was, or deleted.
- **Hidden gifts** (Hidden gifts): givers cannot suggest a gift that is not
  on the list (a spouse's idea, Grandma's own choice). NEEDS wants givers of
  an occasion to add one, with the properties of any gift (title,
  description, links, price, image), reserve, pledge and buy it like any
  other, see who added it, and the recipient to discover only the bought
  ones once the occasion has passed, as the gift alone, with three choices:
  received, dismiss, keep.

The owner also asked for the welcome page to say that hidden gifts exist
(WEB_LAYOUT_PLAN D8: feature plans keep the welcome copy true).

The surprise (NEEDS, Core rules) is the risk that shapes the plan. A hidden
gift is a row a giver writes about a recipient's list: any recipient-facing
query that picks one up (list detail, gift routes, image routes, counts,
ordering, a 404 that becomes a 403) breaks the product's main invariant
before the occasion. So does any way for the recipient to bring the reveal
forward.

Out of this plan: comments and notifications (COMMENTS_NOTIFICATIONS_PLAN,
written in parallel, builds on this plan's data model, D15), handover of a
"for someone else" list, co-owners, free-plan limits (the premium plan; this
plan only says how the model keeps hidden and received gifts out of them,
D12).

## Current state

- `server/app/lists/models.py`: `gifts` (`list_id` not null, indexed,
  `ON DELETE CASCADE`; `image_id` unique; `created_at`, `updated_at`) and
  `occasions` (`date`, a calendar date; `join_token`). Alembic head:
  `33d8218ddbae` (reserving).
- `server/app/lists/access.py`: `owned_list`, `owned_gift` (`db.get(Gift)`
  then `owned_list(gift.list_id)`), `visible_occasion` → owner | invitee,
  `giving_occasion` (an invitee, or an owner of a "for someone else" list;
  404 for the recipient), `owned_occasion`. Hidden is 404
  `{"detail": "Not found"}`, the body of a random id.
- `server/app/lists/router.py`: every owner read selects gifts by
  `Gift.list_id == …` (`_gifts`, `my_lists`' `gift_count`); `get_occasion`
  answers an owner `OwnerOccasionView` and an invitee `InviteeOccasionView`,
  both with all the list's gifts; `update_occasion` sets fields as sent;
  `delete_occasion` locks the occasion, deletes its unbought claims, then the
  occasion (RESERVING D11); `delete_list` locks the list's occasions and
  deletes its gifts' claims (`delete_gift_claims(Gift.list_id == …)`) before
  the cascades.
- `server/app/reserving/`: claims keyed by `gift_id` (`gift_claims`,
  `claim_participants`); `rules.py` has `has_passed` / `last_passed_date`
  (an occasion dated D has passed from 12:00 UTC on D + 1) and `is_live`;
  `router.py`'s `_giving_gift` checks `Gift.list_id == occasion.list_id`
  under `FOR KEY SHARE`, and `occasion_claims` reads every claim on the
  list's gifts; `release.py` has `release_activity`, `lock_occasions`,
  `delete_unbought_claims`, `delete_gift_claims`.
- `server/app/media/`: `gift_images.set_gift_image` attaches a pending image
  of the caller; `router.py`'s `get_image` lets an owner of the gift's list
  read it (`_readable_by_owner`), `get_occasion_image` lets an owner or
  member of the occasion read any image of a gift with
  `Gift.list_id == occasion.list_id`; `purge.py` releases image rows no gift
  points at.
- `server/app/accounts/router.py` `delete_me`: user `FOR UPDATE`, occasions,
  `release_activity`, `delete_gift_claims` on the lists owned alone, then
  `delete_lists_owned_only_by` and the user.
- Tests: `server/tests/lists/test_roles.py` (9 actors × 2 lists × every
  route, content scans, random-id probes, `test_every_route_is_in_the_matrix`
  over `/api/lists`, `/api/gifts`, `/api/occasions`, `/api/join`,
  `/api/shared`, `/api/images`); `test_surprise.py` (a world with activity on
  G1 against a control without, every route the recipient can call compared
  byte for byte, `test_every_route_is_called` over the whole OpenAPI
  document); `claims_invariants.py`. Tests move the clock with
  `client.app.state.clock = lambda: …` (`test_reservations.py`); sessions
  live 90 days (`app/accounts/sessions.py`).
- Client: `client/lib/src/lists/list_detail_screen.dart` (gifts, each
  opening `gift_form_screen.dart`, which adds, edits and deletes a list gift,
  with `GiftImageSection`: choose, image URL, paste); `lists_repository.dart`;
  `client/lib/src/shared/occasion_screen.dart` (view + claims, giver mode
  under `/lists/:id/occasions/:occasionId`), `gift_sheet.dart`
  (`giftActions`, `claimChip`, `showGiftSheet`), `shared_repository.dart`;
  fake server `client/test/lists/support/fake_lists_server.dart`; welcome
  copy in `welcomeSurprise*` ARB keys (RESERVING D15).

## Decisions

- **D1 — A hidden gift is a row of `gifts` that belongs to no list.** Hidden
  gifts live in the existing `gifts` table, so claims, images and the
  comments plan's threads key on `gift_id` unchanged. What makes them safe is
  that they have **no `list_id`**: `gifts.list_id` becomes nullable and a
  hidden gift names its list in a new column instead. Every query that reads
  "the gifts of list L" with `Gift.list_id == L`, today's and any written
  later without thinking of hidden gifts, cannot pick one up; nor can the
  previous release if PROD is rolled back (Boundaries). Rules out a
  discriminator column on gifts that keep their `list_id` (every owner query,
  present and future, would have to remember a filter, and one forgotten
  filter is an F1 leak) and a separate `hidden_gifts` table (claims, images
  and comment threads would need a second foreign key or a polymorphic one).
  New columns on `gifts`:
  - `for_list_id` (uuid, null, FK `lists` `ON DELETE CASCADE`, indexed): the
    list a hidden or revealed gift is for. Set exactly when `list_id` is
    null.
  - `hidden_occasion_id` (uuid, null, FK `occasions` `ON DELETE CASCADE`,
    indexed): the occasion a hidden gift belongs to. The cascade deletes a
    hidden gift with its occasion; an occasion deleted after it passed first
    turns its bought hidden gifts into revealed ones (D9), so the cascade
    only ever meets the ones NEEDS says go.
  - `hidden_by` (uuid, null, FK `users` `ON DELETE SET NULL`, indexed): its
    author; null once their account is deleted.
  - `received_at` (timestamptz, null): when an owner marked it received
    (D5), on any gift.
  Check constraints: `(list_id IS NULL) <> (for_list_id IS NULL)` (exactly
  one list reference); `hidden_occasion_id IS NULL OR for_list_id IS NOT
  NULL`; `hidden_by IS NULL OR for_list_id IS NOT NULL`. The code keeps one
  more invariant, checked by `claims_invariants.py` (U1): a hidden gift's
  occasion is of its `for_list_id`.
- **D2 — A gift's states.** Written states are three; "revealed" is
  evaluated, never written, while its occasion exists (D3):

  | State | Columns | Who sees it |
  |---|---|---|
  | **On the list** | `list_id` set | its owners; every occasion's givers (unless received) |
  | **Hidden** | `for_list_id`, `hidden_occasion_id` set | that occasion's givers only, until revealed (D3) |
  | **Revealed** | hidden, its occasion's reveal date passed and its claim bought; or `for_list_id` set and `hidden_occasion_id` null (its occasion deleted after it passed, D9) | its list's owners, as the gift alone; that occasion's givers while the occasion exists |
  | **Received** | any of the above with `received_at` set | its owners only, under "Received"; no giver |

  A hidden gift nobody bought is never revealed: it stays hidden, inert in
  its passed occasion (RESERVING D8 refuses writes there), until its
  occasion or list is deleted.
- **D3 — The reveal moment, evaluated, and a date that only moves the reveal
  later.** A hidden gift is revealed when its claim is bought and its
  occasion's **reveal date** has passed, with RESERVING D8's rule
  (`has_passed`: 12:00 UTC the day after). Nothing is written at that
  moment, as for expiry (RESERVING D8): no job, and moving the date later
  hides the gift again (NEEDS). The reveal date is not simply the occasion's
  date: the recipient owns the occasion and can edit its date, so with the
  date alone they could move it into the past, read which hidden gifts were
  bought, and move it back, breaking the surprise with two requests. New
  column `occasions.latest_date` (date, null): `update_occasion` sets it to
  `greatest(latest_date, the date before the change)` whenever the date
  changes, and the reveal date is `greatest(date, latest_date)`. Moving the
  date later moves the reveal later; moving it earlier never brings the
  reveal forward. Everything else that reads "passed" (expiry, refusing
  givers' writes) keeps reading `date` (RESERVING D8, unchanged). The same
  reveal date decides an occasion's deletion (D9), or deleting it after a
  move into the past would keep bought hidden gifts revealed. Cost: an owner
  who corrects a date typo from later to earlier delays reveals to the later
  date (Open decisions, to record in NEEDS). Rules out the date alone (the
  hole above) and refusing earlier dates (an answer that differs with
  nothing the owner can see would itself have to be justified, and blocks
  honest corrections).
- **D4 — One module decides which gifts each person sees.** New
  `server/app/lists/visibility.py`, the only place that names
  `Gift.for_list_id`, `Gift.hidden_occasion_id` or `Gift.received_at`,
  besides the models and the hidden-gift package (`server/app/hidden_gifts/`).
  A test scans `server/app/` and fails on any other module that names them
  (U1): a router that needs one of them asks this module. Its SQL
  conditions:
  - `on_list(list_id)`: `Gift.list_id == list_id AND received_at IS NULL`.
    What an owner's list shows and what every occasion view shows, owners'
    and invitees' (`get_list`, `get_occasion`).
  - `counted(list_id)`: the same; `ListSummary.gift_count` and, later, the
    free-plan limit (D12).
  - `revealed(list_id, now)`: `for_list_id == list_id` and either
    `hidden_occasion_id IS NULL`, or its occasion's reveal date has passed
    and a bought claim exists on it. The only owner-side condition that reads
    a claim, and it reads only hidden gifts' claims.
  - `owner_visible(list_id, now)`: `Gift.list_id == list_id OR
    revealed(list_id, now)`, received or not. `owned_gift(db, user, gift_id,
    now)` resolves through it: an unrevealed hidden gift answers the random
    id's 404 to every owner, the owners of a "for someone else" list
    included (they reach it as givers, D7).
  - `in_occasion(occasion)`: `received_at IS NULL AND (Gift.list_id ==
    occasion.list_id OR Gift.hidden_occasion_id == occasion.id)`. What a
    giver of the occasion sees: the claims read, every claim write, the
    occasion's image route for givers, the hidden-gift routes.
  - `of_lists(list_condition)`: every gift of the matching lists, hidden and
    revealed included, for deletions (D9).
  Rules out filters spread over each router (RESERVING's review history:
  each new route is one more place to forget one).
- **D5 — Received.** Any owner marks any gift they can see received, on the
  list or revealed, at any time: `POST /api/gifts/{gift_id}/received` sets
  `received_at` (204, idempotent). The answer is the same for every gift
  whatever its activity, so the action says nothing about what was bought
  (NEEDS). A received gift leaves the list (`on_list`), every occasion
  (`in_occasion`: givers no longer see it, its claim included, and every
  claim write on it answers the random id's 404) and counts towards nothing
  (D12). The owner sees it under `ListDetail.received`, newest first, and
  either puts it back (`DELETE /api/gifts/{gift_id}/received`, 204,
  idempotent: `received_at` cleared and nothing else touched, so it comes
  back in its place, `created_at` order, with its claim as it was, NEEDS) or
  deletes it (`DELETE /api/gifts/{gift_id}`, as today). Its claim is kept
  while it is received: putting it back must restore the activity, and a
  bought claim keeps the gift "taken" for the other occasions. Rules out
  deleting its claim on receipt (putting back could not restore it).
- **D6 — The recipient's three choices on a revealed gift.** Revealed gifts
  are in `ListDetail.revealed`, as `GiftOut` with the owner's image paths:
  the gift alone, with no author, buyer, occasion, date or timestamp, ordered
  by title then id (never `created_at`, which is when a giver added it).
  - **Received:** D5's route.
  - **Dismiss:** `DELETE /api/gifts/{gift_id}`; its claim cascades.
  - **Keep:** `POST /api/gifts/{gift_id}/keep` → 200 `GiftOut` of the gift
    now on the list, under a **new id**. Keep inserts a new `gifts` row with
    the revealed gift's title, description, links, price and image
    (`list_id` = its `for_list_id`, `created_at` now, so it goes to the end
    of the list and carries no giver's timestamp), then deletes the revealed
    row, all in one transaction (the image is moved: the old row's
    `image_id` is cleared before the new row takes it, so the unique
    constraint holds). Everything keyed on the old id goes with it through
    the foreign keys: its claim now, its comment thread with the comments
    plan, anything later, so "nothing of its past activity" (NEEDS) holds by
    construction. 409 `{"code": "not_revealed"}` on a gift that is on the
    list; a received revealed gift kept is on the list, not received. Rules
    out clearing the hidden columns in place (every activity table, present
    and future, would need its own cleanup, one forgotten table being an F1
    leak once the gift is an ordinary gift again).
  Revealed gifts appear the same way to the owners of a "for someone else"
  list (they saw them as givers; this is where they record what was handed
  over). An owner may also edit a revealed gift (`PATCH /api/gifts/{id}`,
  any gift `owner_visible` sees), so it can be tidied before it is kept.
- **D7 — Hidden-gift routes, for givers.** A new package
  `server/app/hidden_gifts/` (`router.py`, `schemas.py`, `lifecycle.py`).
  Every route requires `current_user` and resolves through
  `giving_occasion` (RESERVING D4): the recipient gets the random id's 404
  on every route and for every state; a hidden gift of another occasion is
  404 (`in_occasion`).

  | Method and path | What | Answers |
  |---|---|---|
  | `GET /api/occasions/{occasion_id}/hidden-gifts` | the occasion's hidden gifts | 200 `list[HiddenGiftOut]`, oldest first |
  | `POST /api/occasions/{occasion_id}/hidden-gifts` | add one; body `GiftCreate` (an `image_id` attaches the caller's pending image, as for owners) | 201 `HiddenGiftOut`; 409 `passed` |
  | `PATCH /api/occasions/{occasion_id}/hidden-gifts/{gift_id}` | edit it; body `GiftUpdate` | 200 `HiddenGiftOut`; 403 `not_author`; 409 `bought`, `passed` |
  | `DELETE /api/occasions/{occasion_id}/hidden-gifts/{gift_id}` | delete it; its claim cascades | 204; 403 `not_author`; 409 `bought`, `passed` |

  `HiddenGiftOut`: `id`, `title`, `description`, `links`, `price_amount`,
  `price_currency`, `image` (the occasion's image paths, gift images D7),
  `author` (display name; null once the account is deleted), `mine` (the
  caller is the author). No user id, no timestamp. Errors use RESERVING's
  `{"detail", "code"}` body; the codes grow by `not_author` (403) and
  `not_revealed` (409, D6). A 403 goes only to a giver who can see the gift,
  so it reveals nothing a 404 would hide. Reserving, pledging and marking
  bought a hidden gift go through RESERVING's six routes unchanged, which
  now accept any gift `in_occasion` (D4). A hidden gift is never "taken"
  elsewhere: no other occasion sees it. Rules out hidden gifts inside
  `InviteeOccasionView` or `OwnerOccasionView` (the owner model is the
  recipient's too; RESERVING D5's reason holds), and inside `/claims`
  (activity and gifts stay apart, as for list gifts).
- **D8 — The author.** Only the author edits or deletes a hidden gift, while
  it is not bought and its occasion has not passed (by `date`, RESERVING
  D8); the other givers reserve, pledge and buy it. The author must still be
  a giver of the occasion (`giving_occasion`). An author who leaves the
  occasion or is removed leaves the gift in place with their name, like a
  bought reservation (RESERVING D10), and can no longer change it; an author
  who deletes their account leaves it with no name (`hidden_by` set null).
  Both are recommendations to record in NEEDS (Open decisions); the model
  needs no change if the owner decides the gift should go with its author
  instead (one more delete in `release_activity`).
- **D9 — Deleting and moving things.**
  - **Deleting an occasion** (`delete_occasion`): the occasion locked
    `FOR UPDATE` as today, its unbought claims deleted (today's step, which
    now includes its hidden gifts' unbought claims), then
    `hidden_gifts.lifecycle.settle_occasion_deletion(db, occasion, now)`: if
    its reveal date (D3) has passed, its bought hidden gifts become revealed
    (`hidden_occasion_id` and `hidden_by` set null; `for_list_id` stays) and
    its other hidden gifts are deleted; if not, all its hidden gifts are
    deleted, bought or not (NEEDS). Then the occasion. Hidden gifts are
    deleted explicitly, with their claims first, rather than left to the
    cascade, so no `SET NULL` on `gift_claims.occasion_id` meets an unbought
    claim whatever order Postgres fires cascades in (RESERVING R1-1). The
    answer stays 204.
  - **Deleting a list, or an account:** `delete_gift_claims` takes
    `of_lists(…)`, so hidden and revealed gifts' claims go before the
    cascades, as for list gifts (RESERVING D11). `for_list_id` and
    `hidden_occasion_id` cascade the rows.
  - **Deleting a gift** (owner, `owner_visible`) and **deleting a hidden
    gift** (author): the row; its claim cascades.
  - **Changing an occasion's date:** D3. Moving it later hides revealed
    gifts again until the new date has passed, received ones included (they
    leave "Received" meanwhile; nothing is lost).
  - Leaving, removal, account deletion of a giver: `release_activity`
    unchanged; hidden gifts' claims are claims like any other (D8 for
    authorship).
- **D10 — Concurrency.** RESERVING D7's order holds for every new write:
  user (`FOR KEY SHARE`, by `current_session`), occasion, gift, claims.
  - **Adding a hidden gift:** occasion `FOR SHARE` (`giving_occasion`), then
    the insert. An occasion deletion, a removal or a leave at the same moment
    either committed first (404) or waits for the add; a deletion then
    settles the new gift like any other.
  - **Editing or deleting a hidden gift:** occasion `FOR SHARE`, the gift
    `FOR UPDATE`, then its claim read for `bought`. Every claim write takes
    the gift `FOR KEY SHARE` first (RESERVING D7 step 2), which `FOR UPDATE`
    excludes, so an edit and a "mark bought" on the same hidden gift take
    turns: an edit never lands on a gift bought before it committed.
  - **Received and put back:** an update of `received_at` only, a non-key
    update: it never waits on a giver's `FOR KEY SHARE`, and no giver write
    waits on it (RESERVING D3 kept for list gifts). Claim writes read
    `received_at` in their locked `SELECT … FOR KEY SHARE` of the gift
    (`_giving_gift`), so a claim either committed before the receipt (kept,
    restored by put back) or sees the gift received (404).
  - **Keep:** the occasion of a hidden-state gift `FOR SHARE` (so a date
    change, which updates the occasion row, takes turns with it), then the
    gift `FOR UPDATE`, then the reveal checked. A keep racing a date moved
    later either kept the gift first or finds it hidden again (404, the
    random id's answer). Two keeps at once: the second finds the row gone
    (404).
  - **Occasion deletion:** unchanged lock (`FOR UPDATE` on the occasion), so
    no hidden gift is added, edited, claimed or bought in it while it
    settles.
- **D11 — What a recipient can never observe, extended.** RESERVING D12
  holds with hidden gifts in every state short of revealed: hidden, reserved,
  in a group gift with pledges, bought before the occasion passed, bought in
  an occasion whose date was moved into the past (D3), bought in an occasion
  deleted before it passed, with an image, by an author who left. For an
  owner of a "for me" list every route answers the same status, body and
  headers (apart from `Date`) as without them, the hidden gift's id and its
  image id answering what random ids answer on every owner and occasion
  route. Once revealed, the only difference is the gift in
  `ListDetail.revealed` and the routes that act on it (D6), and no answer
  names its author or buyer. Proven by `test_surprise.py` (U7) and the role
  matrix (U3, U5).
- **D12 — Limits.** `counted(list_id)` is the one count of "gifts on the
  list": only rows with that `list_id`, not received. Hidden and revealed
  gifts have no `list_id`, so they count towards nothing by construction;
  received gifts are excluded by the condition (NEEDS, Free and premium).
  `ListSummary.gift_count` uses it from this plan on, and the premium plan
  reads the same condition. A kept gift is on the list and counts from then
  (whether keep is refused over the free limit is the premium plan's
  decision, Open decisions).
- **D13 — Client: the owner's list.** `ListDetail` gains `received` and
  `revealed`. The gift form of a list gift gains **Mark as received**
  (outlined, above Delete), on every gift alike. The list screen shows,
  below the gifts and only when not empty, a **revealed** section ("Gifts
  from your occasions": each card the gift alone, with **Received**, **Keep
  on my list**, **Dismiss** (confirmed)), then a collapsed **Received**
  section with its count, each card with **Put back** and **Delete**
  (confirmed). Teal and neutral only: nothing rose on an owner's list
  screen (RESERVING Conventions).
- **D14 — Client: givers.** The occasion screen (invitee, and giver mode of
  a "for someone else" owner) loads view, claims and hidden gifts, and shows
  a **Hidden gifts** section below the list's gifts: an explanation line
  ("Only the people giving for this occasion see these. {recipient} will see
  the ones bought, once the occasion has passed."), each hidden gift as a
  `GiftCard` with a rose `inviteeActivity` chip "Added by Ana" / "Added by
  you" next to its claim chip, and **Add a hidden gift** unless `passed`.
  The gift sheet gains **Edit** and **Delete** (confirmed) for the author
  while the gift is not bought and the occasion has not passed. The gift
  form gets a hidden mode (add, edit, delete through D7's routes; image
  choose, URL and paste as for owners; no Mark as received). Routes:
  `/shared/:occasionId/hidden/new`, `/shared/:occasionId/hidden/:giftId/edit`
  and the same under `/lists/:id/occasions/:occasionId/`. An owner of a "for
  me" list never calls `/hidden-gifts` (tested on the fake server's request
  log; the server's 404 is the guarantee).
- **D15 — What the comments plan builds on.** COMMENTS_NOTIFICATIONS_PLAN
  depends on: hidden gifts are `gifts` rows and keep their id while hidden;
  `visibility.in_occasion(occasion)` is how to decide whether a giver of an
  occasion sees a gift (threads of hidden gifts included); keep replaces the
  row (D6) and dismiss deletes it, so a thread's foreign key to `gifts` must
  cascade; received gifts keep their rows (a thread survives receipt and put
  back). Changing any of these is a change to both plans.
- **D16 — Welcome copy.** `welcomeSurpriseBody` gains hidden gifts; nothing
  else on the page changes. It claims only what the app does after this
  plan:
  - EN: "Whoever a list is for never sees what was reserved or bought. The
    people you invite see who is giving what, team up on a bigger gift, and
    can add hidden gifts of their own: the ones bought are revealed once
    the occasion has passed."
  - FR: "La personne à qui la liste est destinée ne voit jamais ce qui a été
    réservé ou acheté. Les personnes invitées voient qui offre quoi, se
    regroupent pour un cadeau plus important et peuvent ajouter leurs propres
    cadeaux cachés : ceux qui ont été achetés sont dévoilés une fois
    l'occasion passée."

## Review envelope

REVIEW.md defaults apply, with RESERVING_PLAN's envelope (the surprise as a
floor for every recipient response, givers seeing each other, concurrency,
the server's UTC clock, no background job), and these additions:

- **Hidden gifts are activity.** Their existence, number, content, images,
  authors, claims and timestamps are invitee activity for the surprise
  floor until revealed (D3). Any difference a recipient can observe, on any
  route, between a list with hidden gifts and the same list without, before
  reveal, is F1, even if it needs several requests or a request the client
  never makes (E2: the recipient may call the API by hand). That includes
  bringing the reveal forward with requests the recipient is allowed to make
  (their occasion's date, deleting it).
- **The reveal is the decided exception.** After reveal, the recipient sees
  that a hidden gift was bought, and its fields; nothing about who added,
  bought or pledged, nor when. A finding that the recipient learns a hidden
  gift existed after reveal is D1 (outside the envelope), not F1.
- **Received is the owner's own data.** Its routes, counts and ordering may
  depend on what the owner marked received; never on activity.
- **Out of the envelope:** lock waits of a few milliseconds (as RESERVING),
  and the sub-millisecond extra work an owner's deletion does for rows
  activity created (deleting unbought claims and hidden gifts with an
  occasion or a list), which no single request can tell from network jitter;
  a rollback of PROD below this plan's migration (an admin action, E3, with
  its effects stated in Boundaries); the recipient known only by name who
  joins through a forwarded link (NEEDS, accepted).
- **Scale.** An occasion has tens of hidden gifts at most; the `revealed`
  read is one query over one list's hidden gifts (indexed `for_list_id`).

## Boundaries crossed

- **Schema (F4):** one migration (`down_revision` `33d8218ddbae`):
  - `gifts.list_id` becomes nullable; new nullable columns `for_list_id`,
    `hidden_occasion_id`, `hidden_by` (with their foreign keys and indexes)
    and `received_at`; the three check constraints of D1;
  - `occasions.latest_date` (date, null).
  Every existing row is valid as is (an ordinary gift: `list_id` set, the
  rest null; `latest_date` null means the reveal date is the date). No data
  migration. Downgrade deletes gifts with a null `list_id` (hidden and
  revealed gifts, with their claims) before restoring `NOT NULL` and dropping
  the columns: data loss on downgrade, stated in the revision.
- **Rollback (DevOps D15):** the previous release keeps working against the
  new schema, and never shows a hidden gift (it reads gifts by `list_id`,
  which hidden gifts do not have). What degrades during a rollback, to go in
  the runbook's rollback notes: received gifts show on the list again (owner
  data, no leak); hidden and revealed gifts are invisible to everyone;
  deleting an occasion deletes its bought hidden gifts instead of revealing
  them; deleting a list whose hidden gifts have unbought claims may answer
  500 (its cascade can meet the claims' check constraint). No surprise leak.
- **API contract (F4):** new routes: `POST` and `DELETE
  /api/gifts/{gift_id}/received`, `POST /api/gifts/{gift_id}/keep`, and the
  four of D7. `ListDetail` gains `received` and `revealed` (lists of
  `GiftOut`). Content changes with the same shape: a received gift is no
  longer in `ListDetail.gifts`, `OwnerOccasionView.gifts`,
  `InviteeOccasionView.gifts` nor counted in `ListSummary.gift_count`; the
  claims read and claim writes accept hidden gifts of the occasion and refuse
  received gifts (404). Error codes grow by `not_author` (403) and
  `not_revealed` (409). Behaviour that grows with the same answers:
  `PATCH /api/occasions/{id}` (D3), `DELETE /api/occasions/{id}`,
  `DELETE /api/lists/{id}`, `DELETE /api/me` (D9).
- **Old clients (E5):** an old owner client does not show received or
  revealed gifts (unknown keys are ignored), and a gift marked received from
  a new client disappears from its list; an old invitee client never shows
  hidden gifts, and ignores their entries in the claims read (it looks claims
  up by the ids of the gifts it shows). Nothing breaks; nothing leaks.
- **Stored data:** hidden gifts name their author (`hidden_by`); account
  deletion sets it null. A hidden gift nobody bought stays in the database,
  inert, until its occasion or list is deleted (Open decisions).
- **Client:** new routes (D14); ARB text of `welcomeSurpriseBody` changes,
  new keys for D13 and D14.

## Conventions

- Every query that selects gifts for an owner or a giver uses a condition of
  `server/app/lists/visibility.py` (D4); the scan test of U1 fails on any
  other module of `server/app/` naming `for_list_id`, `hidden_occasion_id`
  or `received_at`, apart from `server/app/lists/models.py` and
  `server/app/hidden_gifts/`.
- Every new route has rows in `server/tests/lists/test_roles.py` (and
  `test_every_route_is_in_the_matrix` passes) and is called by the recipient
  in `test_surprise.py` (`test_every_route_is_called` passes), in the unit
  that adds it. The owner of the "for me" list gets the random id's 404 on
  every hidden-gift route and on every owner route given a hidden gift's id.
- Response models list their fields explicitly; no user id and no timestamp
  in a hidden-gift or revealed-gift response.
- Hidden-gift writes follow D10's lock order; received writes update
  `received_at` only (a non-key update).
- Tests that need an occasion not to have passed date it relative to today;
  reveal tests date occasions a few days ahead and move
  `client.app.state.clock` a few days past them (sessions live 90 days).
  Concurrency and lifecycle tests end with `assert_claims_consistent(engine)`.
- Rose (`inviteeActivity`) for giver-side chips only (claims, "Added by");
  nothing rose on an owner's list screen, revealed and received sections
  included. Every user-visible string in both ARB files, sentence case, no
  emoji; goldens light and dark, regenerated with `.\goldens.ps1` only
  (Linux), never on Windows.
- U1 and U5 change stored data, the surprise and locking: each gets a unit
  review before integration (DELIVERY §5, point 3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Record in `docs/NEEDS.md` (Hidden gifts) that moving an occasion's date earlier never brings a reveal forward (D3), and that correcting a date from later to earlier therefore delays reveals to the later date | The reveal rule, U1 | Before delivery starts |
| Record in NEEDS what happens to a hidden gift whose author leaves, is removed or deletes their account (D8's recommendation: it stays, with their name, then with none; nobody can edit it) | U5 | Before delivery starts |
| Record in NEEDS that revealed gifts appear, with the three choices, to the owners of a "for someone else" list too (D6) | U3, U4 | Before delivery starts |
| `welcomeSurpriseBody` is also likely changed by COMMENTS_NOTIFICATIONS_PLAN: the plan delivered second merges both sentences into one card | Welcome copy | When the second of the two plans is delivered |
| Whether keep is refused when the list is at the free-plan limit | Premium plan | That plan |
| A purge of expired unbought claims and of hidden gifts nobody bought in long-passed occasions (data minimisation); deferred again from RESERVING's open decisions, since neither affects what anyone sees | Stored data, GDPR export | The data-export plan |
| Notifying givers when an author deletes a hidden gift they reserved or pledged on, or when the recipient dismisses or keeps it | Notifications | COMMENTS_NOTIFICATIONS_PLAN |
| Showing which occasion a revealed gift came from (today: the gift alone) | Client, `GiftOut` | Revisit on user feedback |

## Execution units

### Wave 1

#### U1 — Server: the hidden-gift model and the visibility guard

- **Goal:** Gifts can be hidden, revealed or received in the database, and
  every existing route sees exactly the gifts D4 allows, with deletions and
  date changes behaving as D3 and D9 say; no new route yet.
- **Scope:** `server/app/lists/models.py`, `server/app/lists/visibility.py`
  (new), `server/app/lists/access.py` (`owned_gift` only),
  `server/app/lists/router.py` (`my_lists`, `get_list`, `update_gift`,
  `delete_gift`, `get_occasion`, `update_occasion`, `delete_occasion`,
  `delete_list`, `_gifts`, `_gift_out`), `server/app/hidden_gifts/__init__.py`
  and `server/app/hidden_gifts/lifecycle.py` (new),
  `server/app/reserving/router.py` (`_giving_gift`, `occasion_claims` only),
  `server/app/media/router.py` (`get_occasion_image`, `_readable_by_owner`
  only), `server/app/accounts/router.py` (`delete_me` only),
  `server/alembic/versions/**` (one new revision),
  `server/tests/lists/test_hidden_model.py` (new),
  `server/tests/lists/claims_invariants.py`.
- **Context:** this plan D1–D4, D9, D10, D12, Conventions, Boundaries
  (schema, rollback); RESERVING_PLAN D3, D7, D8, D11; `docs/NEEDS.md`
  (Lists and occasions, Hidden gifts). Examples to follow: the migration
  `server/alembic/versions/33d8218ddbae_reserving.py` (its constraint
  naming), `server/app/reserving/rules.py` (`is_live` as an SQL condition
  built in one place), `server/app/reserving/release.py`
  (`delete_unbought_claims`, `delete_gift_claims`) for
  `settle_occasion_deletion`; `server/tests/lists/test_reservations.py` for
  tests, including `test_the_server_clock_decides` for moving the clock.
- **Do:**
  1. Models per D1 (`Gift.list_id` optional, the four columns, constraints,
     indexes) and `Occasion.latest_date` per D3.
  2. One revision (autogenerate, then read it): nullable `list_id`, new
     columns, constraints, indexes; downgrade deletes gifts with a null
     `list_id` (their claims first) before the reverse steps; its docstring
     states the downgrade's data loss and that the previous release keeps
     working (Boundaries).
  3. `visibility.py`: D4's conditions, and `reveal_date_passed(now)` (the
     SQL of `greatest(date, latest_date) <= last_passed_date(now)`, reusing
     `reserving.rules.last_passed_date`) and its Python twin for one
     occasion.
  4. `owned_gift(db, user, gift_id, now)` through `owner_visible`; its two
     callers pass the request's clock. `_gift_out` answers `list_id` with
     `visibility.list_of(gift)` (the gift's `list_id` or `for_list_id`), so
     the router never names the new columns.
  5. `lists/router.py`: `_gifts` and `get_occasion` (both roles) through
     `on_list`; `my_lists`' `gift_count` through `counted`;
     `update_occasion` keeps `latest_date` per D3 when the date changes;
     `delete_occasion` per D9 (lock, unbought claims, `settle_occasion_
     deletion`, occasion); `delete_list` deletes the claims of
     `of_lists(List.id == …)`.
  6. `hidden_gifts/lifecycle.py`: `settle_occasion_deletion(db, occasion,
     now)` per D9.
  7. `reserving/router.py`: `_giving_gift` locks the gift through a new
     `visibility.lock_gift_in_occasion(db, gift_id, occasion)` (its
     `SELECT … FOR KEY SHARE` filtered by `in_occasion`, so the locked read
     sees `received_at` as committed, D10), 404 when it finds nothing;
     `occasion_claims` reads only claims of gifts `in_occasion`.
  8. `media/router.py`: `get_occasion_image` serves an image of a gift
     `in_occasion` for a giver of the occasion, and of a gift `on_list` for
     an owner of a "for me" list; `_readable_by_owner` requires the image's
     gift to be `owner_visible`.
  9. `accounts/router.py` `delete_me`: `delete_gift_claims` over
     `of_lists(…)` for the lists owned alone.
  10. `claims_invariants.py`: the "claim's occasion is of its gift's list"
      check uses `coalesce(list_id, for_list_id)`; new checks: a hidden
      gift's occasion is of its `for_list_id`; no claim on a hidden gift
      belongs to another occasion than the gift's.
  11. `test_hidden_model.py` (hidden gifts, claims and `received_at` written
      directly in the database through the `engine` fixture; no route adds
      them yet):
      - recipient: a hidden gift (free, reserved, bought, group with
        pledges, with an image) in a future occasion changes nothing in
        `GET /api/lists`, `GET /api/lists/{id}`, `GET /api/occasions/{id}`;
        its id on `PATCH` and `DELETE /api/gifts/{id}` and its image id on
        both image routes answer exactly what random ids answer;
      - givers: the occasion's invitee and the "for someone else" owner see
        its claim in `/claims` and can reserve, pledge and buy it through
        RESERVING's routes; an invitee of another occasion gets 404 on each
        and no `taken` entry for it; the occasion image route serves its
        image to the occasion's givers only;
      - received (column set directly): the gift leaves `ListDetail.gifts`,
        both occasion views, `gift_count`, the claims read (its claim
        stays in the database), and claim writes on it answer 404; clearing
        the column brings it back in its place with its claim;
      - reveal (clock moved): a bought hidden gift is `owner_visible`
        (`PATCH /api/gifts/{id}` 200) once the reveal date has passed, and
        not at 11:59:59 UTC on D + 1; an unbought one never; moving the date
        into the past after the purchase does not reveal it (D3); moving it
        later hides a revealed one again;
      - deletions: deleting an occasion before its reveal date deletes its
        hidden gifts, bought or not; after it, bought ones become revealed
        (`for_list_id` kept, occasion and author null) and the others go;
        moving the date into the past and then deleting it deletes them all;
        deleting the list and deleting the owner's account with hidden gifts
        holding unbought claims answer 204, never 500; deleting the author's
        account leaves the gift with `hidden_by` null;
      - the scan test of Conventions (no module of `server/app/` but
        `lists/models.py`, `lists/visibility.py` and `hidden_gifts/` names
        `for_list_id`, `hidden_occasion_id` or `received_at`);
      - each test ends with `assert_claims_consistent`.
- **Acceptance:** `uv run --directory server ruff check`;
  `uv run --directory server alembic upgrade head` then `alembic check`;
  `uv run --directory server pytest` passes, including `test_hidden_model.py`
  and the existing `test_roles.py`, `test_surprise.py`,
  `test_account_deletion.py` and `test_reservations.py` unchanged.
- **Out of scope:** new routes (received, keep, hidden gifts), response
  shape changes (`received`, `revealed`), the client, notifications, a
  purge.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); an existing test
  must change for a reason other than a received gift leaving a view; a
  recipient-facing answer would have to change; the cascades cannot be made
  safe without a trigger or a deferred constraint.
- **Depends on:** —.

#### U2 — Welcome page copy

- **Goal:** The welcome page's third card says that invitees can add hidden
  gifts, revealed once bought and the occasion passed.
- **Scope:** `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/lib/src/welcome/welcome_screen.dart`, `client/test/welcome/**`,
  `client/test/goldens/welcome_screen_*.png`.
- **Context:** this plan D16 (the exact copy); WEB_LAYOUT_PLAN D8;
  RESERVING_PLAN D15 and its U2, the example to follow;
  `client/test/welcome/welcome_screen_test.dart`.
- **Do:**
  1. Set `welcomeSurpriseBody` in both ARB files to D16's text (the EN `@`
     description unchanged).
  2. Update the welcome tests' expected body text (EN and FR runs).
  3. Regenerate the welcome goldens with `.\goldens.ps1`.
- **Acceptance:** `flutter analyze` and `flutter test` in `client/` pass
  (ARB parity included); the welcome tests find D16's sentence in English
  and French; goldens passing `.\goldens.ps1 -Check`.
- **Out of scope:** the headline, purpose, other cards, layout; anything
  about comments or notifications.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed (X3); the longer text does
  not fit the compact or expanded layout without a layout change.
- **Depends on:** — (ships with the plan on this branch).

### Wave 2

#### U3 — Server: received, put back and keep

- **Goal:** Owners mark any gift received, put it back or delete it, and
  decide on revealed gifts (received, dismiss, keep), with `ListDetail`
  carrying `received` and `revealed`; the recipient learns nothing from any
  of it before reveal.
- **Scope:** `server/app/lists/router.py`, `server/app/lists/schemas.py`,
  `server/app/lists/visibility.py`, `server/app/hidden_gifts/lifecycle.py`
  (add `keep_revealed`, `set_received`),
  `server/tests/lists/test_received.py` (new),
  `server/tests/lists/test_concurrent_received.py` (new),
  `server/tests/lists/test_roles.py`, `server/tests/lists/test_surprise.py`.
- **Context:** this plan D2, D5, D6, D10, D11, Conventions; U1's
  `visibility.py` and `test_hidden_model.py` (how hidden gifts are written
  in tests). Examples to follow: `delete_gift` and `update_gift` in
  `lists/router.py`; `server/tests/lists/test_gifts.py` for route tests;
  `server/tests/lists/test_concurrent_reservations.py` for races.
- **Do:**
  1. `schemas.py`: `ListDetail.received` and `ListDetail.revealed`
     (`list[GiftOut]`), and the 409 body with code `not_revealed`.
  2. `get_list`: `received` (owner-visible gifts with `received_at`, newest
     first, then id), `revealed` (`revealed(...)` and not received, by title
     then id), both with owner image paths. The two queries and their order
     are conditions added to `visibility.py`, so the router still names no
     hidden-gift column (U1's scan test).
  3. Routes `POST` and `DELETE /api/gifts/{gift_id}/received` (D5; 204,
     idempotent, through `owned_gift`, updating `received_at` only, through
     a `set_received(gift, now | None)` in `hidden_gifts/lifecycle.py`) and
     `POST /api/gifts/{gift_id}/keep` (D6, D10; `keep_revealed` in
     `lifecycle.py`: lock order, copy, image moved, old row deleted; 200
     `GiftOut` of the new row; 409 `not_revealed` on a gift on the list).
  4. `test_roles.py`: rows for the three routes (owner 204/204/409 on the
     scenario's gift, everyone else per `expected`); the content scan
     unchanged.
  5. `test_surprise.py`: the recipient marks G1 and G2 received and puts
     them back (twins, in `edits`, before the second `reads`), and calls
     keep on G1 and G2 (twins: 409 both); `reads` checks `received` and
     `revealed` are empty in both worlds; `test_every_route_is_called`
     passes.
  6. `test_received.py`: received then put back restores order and claim
     (a reservation and a bought claim, checked through the invitee's
     `/claims`); a received gift is absent from both occasion views, the
     claims read and `gift_count`, and reserving it answers 404; marking
     received is 204 for a free, a reserved, a bought and a group gift with
     identical headers and body; put back and received twice are
     idempotent; deleting a received gift; revealed (clock moved past a
     near date): in `revealed` with exactly `GiftOut`'s fields, by title,
     no author or buyer name anywhere in the owner's answers; received
     moves it to `received`; dismiss deletes it and its claim; keep returns
     a gift with a new id at the end of `gifts`, the same fields and image
     (readable by the owner, its bytes unchanged), no claim (a giver of any
     occasion sees it free), the old id 404; keep on a list gift 409
     `not_revealed`; keep on an unrevealed hidden gift's id 404 with the
     random id's body; a "for someone else" owner sees and decides the same
     way.
  7. `test_concurrent_received.py`: received racing a reservation of the
     gift (barrier, 20 rounds) → the reservation is 200 and kept, or 404,
     never a 500; keep racing a date moved later (held transaction) → kept
     or 404; two keeps at once → one 200, one 404. Each ends with
     `assert_claims_consistent`.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including the tests of Do 4–7,
  `test_every_route_is_in_the_matrix` and `test_every_route_is_called`.
- **Out of scope:** hidden-gift routes (U5), the client, notifications,
  limits.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); keep cannot move the
  image under the unique constraint in one transaction; a recipient answer
  would differ with activity.
- **Depends on:** U1.

#### U4 — Client: received and revealed gifts on the owner's list

- **Goal:** An owner marks any gift received from its form, finds received
  gifts under "Received" (put back, delete), and decides on revealed gifts
  (received, keep, dismiss).
- **Scope:** `client/lib/src/lists/lists_repository.dart`,
  `client/lib/src/lists/list_detail_screen.dart`,
  `client/lib/src/lists/gift_form_screen.dart`, `client/lib/l10n/app_en.arb`,
  `client/lib/l10n/app_fr.arb`, `client/test/lists/**` (including
  `support/fake_lists_server.dart` and `lists_golden_test.dart` with its
  goldens).
- **Context:** this plan D5, D6 (the contract), D13, Conventions;
  `docs/DESIGN.md` (Components, Invitee colour). Examples to follow: the
  gift form's Delete button and `confirmDelete` in
  `client/lib/src/lists/gift_form_screen.dart`; the occasions section of
  `list_detail_screen.dart` for a section under the gifts;
  `client/test/lists/list_detail_screen_test.dart` and
  `lists_golden_test.dart`.
- **Do:**
  1. Repository: `ListDetail.received` and `ListDetail.revealed` (empty
     when absent, so an older server still parses); `markReceived`,
     `putBack`, `keep` (returns the new `Gift`); dismiss is `deleteGift`.
  2. Fake server: `received_at` per gift, a revealed list per list, the
     three routes with the server's rules (idempotent, 409
     `not_revealed`, keep's new id), and the request log.
  3. Gift form (list gifts, edit mode): **Mark as received**, then back to
     the list; a failure in a snack bar.
  4. List screen per D13: the revealed section (three actions, Dismiss
     confirmed), the collapsed Received section with its count (Put back,
     Delete confirmed); reload after each action; nothing rose.
  5. ARB strings EN and FR.
  6. Tests: each repository call's method, path and body; Mark as received
     on a gift with and without links and image (same button, same call);
     the sections hidden when empty; each action calls its route and
     reloads; keep shows the gift at the end of the list; French run.
     Goldens light and dark: list detail with a revealed and a received
     gift, the Received section expanded.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 6;
  goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** hidden gifts on the giver side (U6), the gift form's
  hidden mode, offline queueing, notifications.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); `GiftCard` needs a
  change to carry three actions.
- **Depends on:** U2 (ARB files integrated); the contract of D5, D6.

### Wave 3

#### U5 — Server: hidden-gift routes

- **Goal:** Givers of an occasion add, read, edit and delete hidden gifts
  with images, and reserve, pledge and buy them through the claim routes;
  the recipient gets the random id's 404 on all of it.
- **Scope:** `server/app/hidden_gifts/router.py` and
  `server/app/hidden_gifts/schemas.py` (new), `server/app/main.py` (include
  the router), `server/tests/lists/test_hidden_gifts.py` (new),
  `server/tests/lists/test_concurrent_hidden_gifts.py` (new),
  `server/tests/lists/test_roles.py`, `server/tests/lists/test_surprise.py`.
- **Context:** this plan D7, D8, D10, D11, Conventions; U1's
  `visibility.py` and `lifecycle.py`. Examples to follow:
  `server/app/reserving/router.py` (`giving_occasion`, `_conflict`, explicit
  response models, the module docstring's lock order) and `add_gift` /
  `update_gift` in `server/app/lists/router.py` (body handling,
  `set_gift_image`, the price check); `test_group_gifts.py` and
  `test_concurrent_group_gifts.py` for tests.
- **Do:**
  1. `schemas.py`: `HiddenGiftOut` (D7), the conflict codes.
  2. `router.py`: the four routes of D7 with D8's author rule, D10's locks
     (occasion `FOR SHARE`; gift `FOR UPDATE` for edit and delete; claim
     read for `bought`), `passed` by `date` (RESERVING D8); images through
     `set_gift_image` with the caller; occasion image paths in responses;
     the author's name joined from `users`.
  3. `test_roles.py`: the scenario gains, in each list's first occasion, a
     hidden gift with an image, added by that occasion's invitee and
     reserved on the "for someone else" list by its owner; `hidden_from`
     hides its id and its image id from everyone but that occasion's givers
     (the "for me" owner included); `owners_view` records the hidden gifts
     as the first invitee sees them; rows for the four routes (author the
     invitee: invitee 200/201/200/204, the "for someone else" owner 200/201
     and 403 `not_author` on edit and delete, recipient 404 on all), for
     both image routes on the hidden image (owners 404 on the owner path,
     givers 200 on the occasion path, recipient 404), and for
     `PATCH`/`DELETE /api/gifts/{id}`, received and keep on the hidden id
     (404 for every owner). `ACTIVITY_KEYS` gains `author` and `mine`. The
     random-id probe applies to 404s; a 403 is asserted to go only to a
     giver of the occasion.
  4. `test_surprise.py`: `activity` calls the four routes on every occasion
     and on ids that exist nowhere (all the random id's 404); `ACTIVITY` and
     `ACTIVITY_KEYS` updated; `test_every_route_is_called` passes.
  5. `test_hidden_gifts.py`: add with every property and each image way
     (upload, image URL through the `url_fetcher` fixture), read by the
     occasion's givers with author and `mine`; invitees of another occasion
     404 on every route and see no claim of it; reserve, pledge, buy it
     through RESERVING's routes; author edits until bought (reserved
     included), 409 `bought` after, 409 `passed` after the date, 403 for
     another giver; delete cascades its claim; the author removed or gone
     leaves the gift with their name, and can no longer edit it; the
     author's account deleted → `author` null; the "for someone else" owner
     adds and sees hidden gifts like an invitee; no user id and no
     timestamp in any response; the recipient gets 404 with the random-id
     body on every route, for every state.
  6. `test_concurrent_hidden_gifts.py`: an author's edit racing a "mark
     bought" (barrier, 20 rounds) → the edit landed before the purchase or
     was refused 409 `bought`; a delete racing a reservation → 204 then 404,
     or reserved then deleted, never a 500 nor a claim on a missing gift;
     an add racing the occasion's deletion (held transaction) → 201 and
     then settled per D9, or 404, never a 500; an add racing the author's
     removal → the gift stays or is refused, never a 500. Each ends with
     `assert_claims_consistent`.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including the tests of Do 3–6,
  `test_every_route_is_in_the_matrix` and `test_every_route_is_called`.
- **Out of scope:** comment threads, notifications, the client, received
  and keep (U3).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a hidden gift needs
  a field a list gift does not have; an author rule needs a schema change.
- **Depends on:** U1, U3 (shared test files).

#### U6 — Client: hidden gifts for givers

- **Goal:** Givers see an occasion's hidden gifts with who added them, add
  one with every property and an image (choose, URL, paste), and edit or
  delete their own until bought; the owner of a "for me" list never calls
  the hidden-gift routes.
- **Scope:** `client/lib/src/shared/shared_repository.dart`,
  `client/lib/src/shared/occasion_screen.dart`,
  `client/lib/src/shared/gift_sheet.dart`,
  `client/lib/src/lists/gift_form_screen.dart`,
  `client/lib/src/app_router.dart`, `client/lib/l10n/app_en.arb`,
  `client/lib/l10n/app_fr.arb`, `client/test/shared/**`,
  `client/test/lists/support/fake_lists_server.dart`,
  `client/test/lists/gift_form_screen_test.dart`,
  `client/test/lists/giver_mode_test.dart`, `client/test/app_router_test.dart`.
- **Context:** this plan D7, D8 (the contract), D14, Conventions;
  RESERVING_PLAN D13, D14. Examples to follow: the occasion screen's claims
  loading and `_act` in `occasion_screen.dart`; `giftActions` and
  `showGiftSheet` in `gift_sheet.dart`; the gift form and its
  `GiftImageSection` for the hidden mode; the members route in
  `app_router.dart` for new routes; `client/test/shared/occasion_activity_test.dart`
  and `shared_golden_test.dart`.
- **Do:**
  1. Repository: `HiddenGift` (the gift's fields, `author`, `mine`);
     `hiddenGifts(occasionId)`, `addHiddenGift`, `updateHiddenGift`,
     `deleteHiddenGift`; 403 and 409 surface their `code`.
  2. Fake server: hidden gifts per occasion with the server's rules
     (author, bought, passed; claims on them in `/claims`).
  3. Occasion screen: loads hidden gifts with view and claims (not for an
     owner sent to the list, RESERVING D14); the Hidden gifts section of
     D14 with its explanation line, "Added by" chips (rose), claim chips,
     Add a hidden gift unless `passed`.
  4. Gift sheet: Edit and Delete for the author while not bought and not
     passed; Delete confirmed; after either, or a 409, reload.
  5. Gift form hidden mode (`GiftFormScreen` given an occasion instead of a
     list): load, add, save and delete through the hidden routes, the image
     section unchanged, no Mark as received; 409 `bought` says it can no
     longer be changed.
  6. Routes of D14 under `/shared/:occasionId` and
     `/lists/:id/occasions/:occasionId`.
  7. ARB strings EN and FR.
  8. Tests: repository calls; the section with author chips ("Added by
     you" for `mine`, none for a deleted author); Add hidden in both modes
     and not when passed; edit and delete only for the author and not once
     bought; the form adds with an uploaded, a URL and a pasted image; a
     "for me" owner opening the list, its occasion cards and `/shared/:id`
     makes no request to `/hidden-gifts` (request log); French run. Goldens
     light and dark: the occasion with a hidden gifts section, the author's
     sheet, the hidden gift form.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 8;
  goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** comments, notifications, the owner's received and
  revealed sections (U4), offline queueing.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the gift form's
  hidden mode needs a second form screen rather than a mode.
- **Depends on:** U4 (shared files integrated); the contract of D7.

### Wave 4

#### U7 — Server: the recipient sees nothing of hidden gifts

- **Goal:** `test_surprise.py` proves D11: every hidden-gift state short of
  revealed leaves every answer to the recipient unchanged, and a revealed
  gift shows as the gift alone.
- **Scope:** `server/tests/lists/test_surprise.py`. Server code only if a
  test fails, through X3.
- **Context:** this plan D3, D6, D9, D11, the Review envelope;
  `test_surprise.py` itself (`build`, `STATES`, `Recorder`, `differences`,
  `test_a_giving_owner_sees_the_activity`) as the example to follow.
- **Do:**
  1. `HIDDEN_STATES`, each built in the world only, on top of the `none`
     G1 state, by the occasions' invitees: a hidden gift with an image
     added in A; reserved; a group gift with pledges; bought in A; added
     and bought in P before `build` moves P's date into the past (D3: not
     revealed); added and bought in D before `build` deletes it (deleted,
     D9); added in A by Ben, who is then removed. The hidden gift's id and
     image id are names of the world (random ids in the control), so the
     recipient's calls name them in both.
  2. The recipient's calls gain, on the hidden gift's id and image id:
     `PATCH`, `DELETE`, received and keep on `/api/gifts/{id}`, both image
     routes on every occasion, and the hidden-gift routes on every occasion.
     World and control answers identical, after renaming, for every state,
     for the owner and the co-owner, with the endings in turn as `RUNS`
     does.
  3. A reveal test: occasions dated a few days ahead, hidden gifts bought
     and not, the clock moved past them; the world's answers differ from
     the control's only in `ListDetail.revealed` and in the routes called on
     the revealed gift's id and image; `revealed` holds exactly the bought
     ones with `GiftOut`'s fields; no answer names an invitee; moving the
     date later empties `revealed` again; deleting the occasion keeps it.
  4. `test_a_giving_owner_sees_the_activity` gains the hidden states: the
     "for someone else" owner sees them through `/hidden-gifts` and
     `/claims` only.
- **Acceptance:** `ruff check`; `pytest` passes with `test_surprise.py`; no
  server file changed, or each change escalated and approved (X3).
- **Out of scope:** comments and notifications (their plan extends this
  suite).
- **Latitude:** local design.
- **Escalate if:** any comparison fails (an F1 finding: report it, do not
  fix it inside this unit); the suite's run time more than doubles (propose
  which runs to pair, as `RUNS` does); a file outside Scope is needed (X3).
- **Depends on:** U1, U3, U5.

## Definition of done

- On VAL, an invitee adds a hidden gift with an image (uploaded, from a URL
  and pasted) to an occasion; another invitee of that occasion sees it with
  "Added by <name>", reserves and buys it; an invitee of another occasion of
  the list does not see it; the author can edit it until it is bought and
  not after.
- The owner of a "for me" list gets the same answers from every endpoint,
  status, body and headers, with or without hidden gifts in any state short
  of revealed, including after moving the occasion's date into the past and
  after deleting the occasion before its date (`test_surprise.py`,
  `test_roles.py`, `test_hidden_model.py`).
- Once the occasion has passed (12:00 UTC the next day, by its latest date),
  the recipient finds each bought hidden gift under the revealed section, as
  the gift alone, and marks it received, dismisses it or keeps it; a kept
  gift is an ordinary gift at the end of the list, free in every occasion,
  with nothing of its past; unbought hidden gifts are never shown to them.
- Moving the occasion's date later hides a revealed gift again; moving it
  earlier never reveals one sooner.
- Deleting an occasion before its reveal date deletes its hidden gifts;
  after it, bought ones stay revealed.
- An owner marks any gift received from its form (the same action on every
  gift), finds it under "Received", puts it back exactly as it was, its
  reservation included, or deletes it; a received gift is in no occasion,
  cannot be reserved and is not counted in `gift_count`.
- Hidden and revealed gifts are never counted: `counted()` reads only gifts
  with a `list_id`, not received.
- No module but `server/app/lists/visibility.py` and
  `server/app/hidden_gifts/` names the hidden-gift columns (scan test).
- Every new route is in `test_roles.py`'s matrix and called in
  `test_surprise.py`; both completeness tests pass.
- The welcome page shows D16's copy in English and French.
- All DELIVERY.md §2 checks pass on server and client, goldens included.
