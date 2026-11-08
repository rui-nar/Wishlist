# Reserving, group gifts and the surprise

## Problem

Invitees can open an occasion and read its gifts, but they cannot do the
thing the product exists for (`docs/NEEDS.md`, Problem): say "I'm giving
this" so nobody else buys it, or team up on a bigger gift. Two invitees can
buy the same gift today and nothing stops them. The owner asked on 2026-11-08
to "implement the reserving roadmap". This plan delivers that slice of
`docs/NEEDS.md`:

- **Reserving:** reserve and release a gift, mark it bought (final).
- **Group gifts:** join or leave, with an optional pledge in the gift's
  currency.
- **Invitees among themselves:** each invitee sees who reserved, bought or
  pledged on each gift of their occasion. The comment thread is a later plan.
- **Several occasions at once:** a gift taken in another occasion that has
  not passed, or bought in any occasion, shows as "taken" (not by whom, nor
  where) and cannot be taken again.
- **Expiry:** after an occasion's date, its reservations and group gifts that
  were not bought end.
- **Who sees it:** owners of a "for someone else" list see the activity and
  act like invitees; recipients ("for me" owners) see nothing, directly or
  indirectly.
- **Effects** of removing an invitee, an invitee leaving, an account being
  deleted, and an owner editing or deleting a gift, as NEEDS describes them.
- **The welcome page** says what the app now does (WEB_LAYOUT_PLAN D8).

Notifications ("the owner changed or deleted that gift", group activity) are
the notifications plan; until then a change simply shows (NEEDS, Reserving).
Hidden gifts, comments, "received" marking and handover are later plans. The
data model chosen here must not need rewriting when they arrive.

## Current state

- `server/app/lists/models.py`: `lists`, `list_owners`, `gifts`,
  `occasions` (`date` is a calendar date, no time), `occasion_members`,
  `occasion_removals`. Keys are UUIDs. Alembic head: the gift images
  plan's revision (`docs/plans/GIFT_IMAGES_PLAN.md`), delivered on this
  branch before this plan; gifts then carry an optional image.
- `server/app/lists/access.py`: `owned_list`, `owned_gift`,
  `visible_occasion` → `(occasion, "owner" | "invitee")`, `owned_occasion`.
  Hidden means 404 with the body `{"detail": "Not found"}`, the same as a
  random id.
- `server/app/lists/router.py`: owners' and invitees' endpoints
  (LISTS_GIFTS_SHARING_PLAN D8). `GET /api/occasions/{id}` answers an owner
  with `OwnerOccasionView` (role `owner`) and a member with
  `InviteeOccasionView` (role `invitee`). Responses list their fields
  explicitly. Locking patterns already in use: `join` takes the occasion
  `FOR SHARE`, `remove_member` takes it `FOR UPDATE` and the removed user
  `FOR KEY SHARE`. `leave_occasion` takes no lock.
- `server/app/accounts/router.py` `delete_me` →
  `server/app/lists/deletion.py` `delete_lists_owned_only_by`, then deletes
  the user. Foreign keys cascade memberships and removals.
- `server/app/db.py`: one session and one transaction per request
  (READ COMMITTED, Postgres default), committed before the response.
- No API response carries `updated_at`, an `ETag` or `Last-Modified`
  (only static files get an ETag, `server/app/main.py`).
- Tests (`server/tests/lists/`): a scratch Postgres database per run;
  `test_roles.py` is the role matrix (8 actors × 2 lists × every endpoint),
  with content scans (`assert_reveals_nothing`), random-id probes, "nothing
  changed" checks (`owners_view`) and `test_every_route_is_in_the_matrix`,
  which fails for any route under `/api/lists`, `/api/gifts`,
  `/api/occasions`, `/api/join`, `/api/shared` without a row (ledger R4-2).
  Its scenario dates its occasions `2026-12-25`, a fixed date.
  `test_concurrent_join.py` has the two concurrency patterns: a barrier
  releasing two requests together many times, and a transaction held open
  with `wait_until_blocked_on_a_lock`.
- Client: `client/lib/src/shared/occasion_screen.dart` shows an invitee's
  occasion read-only (privacy banner, `GiftCard`s with a details sheet) and
  sends an owner to the list. `shared_repository.dart` parses
  `OccasionView` as `OwnedOccasion(listId)` or `InviteeOccasion`.
  `client/lib/src/lists/occasions_section.dart` is the owner's occasion card
  (link, members, edit, delete). `StatusChip(variant: inviteeActivity)` is
  rose and reserved for invitee activity (`docs/DESIGN.md`, Invitee colour);
  `GiftCard` takes chips as display values. Client tests run against
  `client/test/lists/support/fake_lists_server.dart`.
- Welcome page: `client/lib/src/welcome/welcome_screen.dart`, copy in
  `welcome*` ARB keys; WEB_LAYOUT_PLAN D8 says this plan updates the purpose
  sentence and the third card ("You stay in control").

## Decisions

- **D1 — One claim per gift, enforced by the primary key.** A new table
  `gift_claims` holds at most one row per gift: `gift_id` (primary key, FK
  `gifts` `ON DELETE CASCADE`), `occasion_id` (FK `occasions`
  `ON DELETE SET NULL`, indexed), `kind` (`reservation` | `group`),
  `bought_at` (timestamptz, null until bought), `created_at`. Check
  constraints: `kind` in the two values; `occasion_id IS NOT NULL OR
  bought_at IS NOT NULL` (only a bought claim can outlive its occasion,
  D11). Because the key is the gift, "exactly one of two simultaneous
  reservations succeeds" (NEEDS, Core rules) is the database's guarantee,
  across every occasion of the list at once, whatever the code does: the
  second `INSERT … ON CONFLICT DO NOTHING` inserts nothing and the request
  answers 409. Rules out a claim per (occasion, gift) with an application
  check across occasions (two occasions could each pass the check at the
  same moment) and a partial unique index on live claims (liveness depends
  on the clock, which an index cannot read). Quantities with partial
  reservations (NEEDS, Later) would change this key; that later plan pays a
  migration, accepted.
- **D2 — Who is in a claim.** `claim_participants`: `gift_id` (FK
  `gift_claims` `ON DELETE CASCADE`), `user_id` (FK `users`
  `ON DELETE CASCADE`, indexed), `pledge_amount` (`numeric(12,2)`, null, `> 0`),
  `pledge_currency` (3 letters, null; both or neither, check constraint),
  `joined_at`; primary key (`gift_id`, `user_id`). A reservation has one
  participant, the reserver, with no pledge; a group gift has one or more,
  each with an optional pledge. A gift is either reserved by one person or a
  group gift, never both (NEEDS, Decided 2026-11-08), which `kind` makes a
  single state. Invariants the code keeps and a test helper checks after
  every concurrency and release test (`claims_invariants.py`, U1): an
  unbought claim has at least one participant and an occasion; a
  reservation has at most one participant; pledges exist only on group
  claims.
- **D3 — Activity never touches the owner's rows.** Claim writes insert,
  update and delete only `gift_claims` and `claim_participants`. They never
  update `gifts`, `lists` or `occasions` (no `updated_at` moves, no order
  changes), and they lock those rows only in shared modes (`FOR KEY SHARE`,
  `FOR SHARE`) that never block an owner's read. Rules out a status column
  on `gifts`, which would put invitee activity in the row the recipient
  edits and reads.
- **D4 — Who may see and do: the giver.** A *giver* of an occasion is a
  member of it (an invitee), or an owner of its list when the list is "for
  someone else" (NEEDS, Users and roles). `access.py` gains
  `giving_occasion(db, user, occasion_id) -> Occasion`: `visible_occasion`,
  then 404 (`not_found()`, the same body) for an owner of a "for me" list.
  Every endpoint of D6 goes through it, so a recipient gets, for every
  activity route and every gift state, exactly what a stranger gets for a
  random id. Whether a person sees activity is computed from the list's
  current `recipient_kind` on every request and never stored with the
  activity, so the later handover ("for someone else" → "for me") blinds
  the new owner to every past occasion at once without touching claims.
  Ownership is checked first: a member who becomes an owner of a "for me"
  list (co-owners, later) is blind from that moment.
- **D5 — Activity is in its own route; existing responses do not change.**
  Givers read an occasion's activity from `GET /api/occasions/{id}/claims`.
  `ListSummary`, `ListDetail`, `OwnerOccasionView`, `InviteeOccasionView`,
  `SharedOccasion`, `MemberOut` and `JoinPreview` keep their exact shape and
  content. This makes the floor provable: activity appears only in the
  routes of D6, and every owner response is byte-identical whatever the
  activity (U7). It also leaves shipped clients (E5) untouched. Rules out
  adding claim fields to the gifts of the invitee and owner views, which
  would need a per-kind owner model and a role-discriminator change on an
  existing endpoint. Cost: the giver's screen makes two requests (the view
  and its claims); the client merges them by gift id.
- **D6 — Endpoints.** All require `current_user` and resolve through
  `giving_occasion`; the gift must belong to the occasion's list, otherwise
  404. Writes on a passed occasion (D8) answer 409 `passed`. A 409 body is
  `{"detail": "<English sentence>", "code": "taken" | "bought" | "passed"}`.

  | Method and path | What | Answers |
  |---|---|---|
  | `GET /api/occasions/{occasion_id}/claims` | the occasion's activity | 200 `OccasionClaims` |
  | `POST /api/occasions/{occasion_id}/gifts/{gift_id}/reservation` | reserve | 200 `GiftClaimOut`; 200 again if it is already mine (a double tap); 409 `taken` if anyone else holds the gift, here or in another occasion, reserved or as a group gift |
  | `DELETE /api/occasions/{occasion_id}/gifts/{gift_id}/reservation` | release my reservation | 204, also when I hold none (idempotent); 409 `bought` if mine is bought |
  | `POST /api/occasions/{occasion_id}/gifts/{gift_id}/bought` | mark bought: my reservation, a group gift I am in, or a free gift (reserved and bought at once) | 200 `GiftClaimOut`, idempotent; 409 `taken` otherwise |
  | `PUT /api/occasions/{occasion_id}/gifts/{gift_id}/pledge` `{"amount": "50.00" \| null}` | join the group gift, starting it if the gift is free, or change my amount | 200 `GiftClaimOut`; 409 `taken` if reserved (by anyone, me included: release first) or held in another occasion; 409 `bought` once the group gift is bought; 422 for an amount on a gift with no currency |
  | `DELETE /api/occasions/{occasion_id}/gifts/{gift_id}/pledge` | leave the group gift; the last one out frees the gift | 204, also when I am not in it; 409 `bought` once bought |

  Response models, fields listed explicitly:
  - `OccasionClaims`: `passed` (bool, D8), `gifts`: list of `GiftClaimOut`,
    one per gift of the list that has a live claim (D8), oldest gift first,
    plus, once the occasion has passed, the caller's own unbought claims of
    this occasion (review R3-1), so they can still mark them bought; a gift
    absent from it is free.
  - `GiftClaimOut`: `gift_id`; `state`: `reserved` | `group` | `taken`;
    `bought` (bool, always false for `taken`); `participants`: list of
    `{display_name, mine, pledge_amount, pledge_currency}`, by `joined_at`
    then name, always empty for `taken`; `expired` (bool): true only for
    the caller's own unbought claim of a passed occasion, in the read above
    (review R3-1).
  - `taken` means "held by a claim of another occasion that has not passed,
    or bought in any other occasion, or bought in a deleted occasion": no
    name, no occasion id, no date, no bought flag.
  - No user id appears in any of them (`mine` replaces it), so the role
    matrix's rule "nobody sees another user's id unless they own a list that
    user joined" holds unchanged. A participant whose account was deleted is
    simply absent (D10).
- **D7 — Concurrency design.** Every write runs in the request's one
  transaction (READ COMMITTED), in this order:
  1. the occasion `FOR SHARE`, then the giver check (`giving_occasion`):
     a removal or a leave (which take the occasion `FOR UPDATE`, D10) either
     finished before, and the write answers 404, or waits for the write and
     then releases what it made;
  2. the gift `FOR KEY SHARE`, checked to be on the occasion's list: an
     owner deleting it at the same moment either finished (404) or waits;
     an owner editing its fields is not blocked at all (D3); changing its
     image is a key update of `gifts.image_id` (unique), which can wait a few
     milliseconds while a giver's write on that gift commits: accepted as
     noise, like an owner deleting the gift (review round 2);
  3. creating a claim: purge this gift's expired unbought claim (D8), then
     `INSERT … ON CONFLICT (gift_id) DO NOTHING RETURNING`; no row returned
     means someone holds it: read that claim and answer per D6;
  4. changing a claim (join, change pledge, leave, release, mark bought):
     the claim row `FOR UPDATE` first, so participants of one group gift
     are serialised; a claim gone by then (its last participant left) is
     created afresh by step 3, once.

  Two `PUT …/pledge` on a free gift at the same moment therefore end in one
  group gift with two participants; a reservation and a pledge at the same
  moment end with exactly one of them. Account deletion (D10) locks the
  user row `FOR UPDATE` first, so a write by the same account at the same
  moment either commits before the release runs or fails its foreign key
  and answers 404; no unbought claim is left without a participant. Tests
  use real concurrent requests against Postgres (U1, U3, U5), with both
  patterns of `test_concurrent_join.py`.
- **D8 — When an occasion has passed.** An occasion dated D has passed from
  **12:00 UTC on D + 1**: the moment D has ended in every time zone (the
  last to end is UTC−12). In code, with the server's clock,
  `passed ⇔ D ≤ (now_utc − 36 h).date()`, in one function
  (`server/app/reserving/rules.py`) used by every read and write. NEEDS
  leaves the time zone open for hidden gifts; for expiry, ending late is the
  safe direction: a reservation kept a few hours longer can only delay a
  gift becoming available again, while one ended early can let a second
  occasion's invitee take a gift that is being handed over, and nothing in
  the rule reaches the recipient (D4, D5). Rules out the owner's or the
  invitee's time zone (neither is stored) and "the end of D in UTC" (it
  would end Christmas reservations at 19:00 on the 25th in New York, while
  the gifts are still being handed over). Effects:
  - a claim of a passed occasion that is not bought is no longer live: no
    longer shown (not even to that occasion's invitees), no longer
    "taken" elsewhere; the gift is free;
  - a bought claim stays "taken" for every other occasion until the owner
    deletes the gift ("received" is a later plan, NEEDS);
  - writes on a passed occasion answer 409 `passed`, with one exception
    (envelope answer, review round 1): a giver may still mark **bought** their
    own claim of a passed occasion while that claim still exists (it is only
    purged when someone claims the gift again, below), so a gift handed over
    on the day can be recorded afterwards and is not freed for the next
    occasion; reads still work, and `OccasionClaims.passed` tells the client
    to hide every other action;
  - expiry is evaluated, never written: expired rows are purged only when
    someone claims that gift again (D7 step 3). If an owner moves an
    occasion's date later before that happens, its unbought claims are live
    again. Rules out a background job (one more moving part on the VPS, and
    a sensitive one, DELIVERY S5) and purging on a date change (an owner's
    typo would destroy invitees' reservations for good).
- **D9 — Pledges are in the gift's currency.** `amount` is optional, a
  decimal `> 0` within `numeric(12,2)` (same bounds as prices, 422 beyond).
  The server stores it with the gift's currency at that moment
  (`pledge_currency`); a gift with no price has no currency, so its pledges
  carry no amount (422 if one is sent). An owner changing the gift's
  currency later does not reinterpret stored pledges: each is shown in its
  own currency. Rules out reading the currency from the gift at display
  time (an owner's edit would silently change what someone pledged) and a
  currency chosen by the participant (not asked for; noted in Open
  decisions).
- **D10 — When a giver goes away.** One function,
  `release_activity(db, user_id, occasion_id | None)` in
  `server/app/reserving/release.py`:
  - **Leaving an occasion, or being removed from it** (NEEDS, Access and
    Reserving): in that occasion, the user's unbought reservations are
    deleted (the gifts are free again); their participations in group
    gifts are deleted, bought or not ("their pledges are removed"); an
    unbought group gift left with nobody is deleted; their bought
    reservations stay, with their name ("what they bought stays bought").
    `leave_occasion` and `remove_member` take the occasion `FOR UPDATE` and
    release in the same transaction; their answers do not change (204,
    whether or not there was anything to release).
  - **Deleting an account** (NEEDS, Deleting an account): the same in every
    occasion, and their participant rows on bought reservations go too
    (through the foreign key), so a bought gift stays "bought" with no name
    and nothing identifies them. `delete_me` locks the user row, releases,
    deletes the lists they own alone (which cascades their claims), then
    deletes the user.
  - Owners of a "for someone else" list are not members: nothing to leave
    or be removed from. Their claims go with the list or their account.
- **D11 — When the owner changes the list.** As for any other gift (NEEDS,
  Reserving), with no indication either way:
  - **editing a gift** with a claim: allowed, unchanged answer, the claim
    stays;
  - **deleting a gift**: its claim and participants cascade; 204 as always;
  - **deleting an occasion**: its unbought claims are deleted with it; its
    bought claims stay, their `occasion_id` set to null by the foreign key,
    so a gift bought for a deleted occasion stays "taken" and cannot be
    bought twice (NEEDS: it stays taken "until the owner marks it received
    or deletes it"). `delete_occasion` first locks the occasion
    `FOR UPDATE` (as removal and leave do, D7), so no reservation can commit
    in it meanwhile, then deletes the unbought claims, then the occasion.
    Without the lock, a reservation committing while the delete waits would
    make the foreign key's `SET NULL` violate the claims' check constraint and
    answer the owner a 500 that only invitee activity can cause (review
    R1-1). Deleting a list or an account reaches the same `SET NULL` through
    the occasions cascade; there the gifts cascade must delete the claims
    first: U5 states and tests it rather than relying on trigger order;
  - **deleting the list**, or the owner's account: everything cascades;
  - **changing an occasion's date**: D8.
- **D12 — What a recipient can never observe.** For an owner of a "for me"
  list (the recipient), every endpoint they can call answers the same
  status, the same body and the same headers (apart from `Date`) whatever
  the activity on their gifts: none, reserved, bought, a group gift with
  pledges, taken elsewhere, expired. That covers counts (`gift_count`,
  `occasion_count`, `member_count`), ordering (gifts by `created_at`),
  timestamps (D3), error differences (D4, D10, D11) and limits: claims and
  pledges count towards nothing an owner sees, now and when free-plan limits
  arrive (NEEDS, Free and premium). U7 proves it by comparing every owner
  endpoint on two identical gifts, one in each activity state and one free.
- **D13 — Client: what invitees see and do.** The occasion screen loads the
  view and its claims and shows, on each `GiftCard`, rose
  `StatusChip(variant: inviteeActivity)` chips: "Reserved by Ana" / "Reserved
  by you", "Bought by Ana" / "Bought" (no name left), "Group gift · 3",
  "Group gift · bought", "Taken". Tapping a gift opens its sheet (today's
  details sheet, extended): the participants with their pledges and, when
  every pledge is in the gift's currency, their total against the price;
  then the actions the state allows (Reserve, Start a group gift, Mark as
  bought, Release, Join the group gift, Change my amount, Leave the group
  gift), none once `passed`. Releasing and leaving ask for confirmation;
  marking bought says it is final. After any action, or a 409, the claims
  are loaded again (no optimistic state). Every action needs a connection
  (NEEDS, Constraints, Offline); a failure says so in a snack bar.
- **D14 — Client: owners of a "for someone else" list act as givers.** On
  such a list, each occasion card gains "Gifts and reservations", opening
  `/lists/:id/occasions/:occasionId`: the same occasion screen, built from
  `OwnerOccasionView` plus the claims, with the same chips, sheet and
  actions, and no "leave" menu. For a "for me" list nothing changes: no
  entry point, the occasion screen still sends its owner to the list, and
  the client never calls `/claims` (tested; the server's 404 is the actual
  guarantee).
- **D15 — Welcome copy (completes WEB_LAYOUT_PLAN D8).** The purpose sentence
  and the third card change; the first two cards stay. The third card's
  keys are renamed from `welcomeControl*` to `welcomeSurprise*`, its icon
  becomes `Icons.visibility_off_outlined` (teal, as the others; never rose).
  It claims only what the app does after this plan (no comments, no
  notifications):
  - `welcomePurpose`
    - EN: "Keep the things you'd love to receive in one place, share them
      with family and friends for each occasion, and let them choose
      without spoiling the surprise."
    - FR: "Rassemblez les choses que vous aimeriez recevoir, partagez-les
      avec votre famille et vos amis pour chaque occasion, et laissez-les
      choisir sans gâcher la surprise."
  - `welcomeSurpriseTitle`
    - EN: "The surprise stays a surprise"
    - FR: "La surprise reste entière"
  - `welcomeSurpriseBody`
    - EN: "Whoever a list is for never sees what was reserved or bought.
      The people you invite see who is giving what, and can team up on a
      bigger gift."
    - FR: "La personne à qui la liste est destinée ne voit jamais ce qui a
      été réservé ou acheté. Les personnes invitées voient qui offre quoi,
      et peuvent se regrouper pour un cadeau plus important."

## Review envelope

REVIEW.md defaults apply, with these additions:

- **The surprise is a floor for every response a recipient can get.** A
  recipient is any owner of a "for me" list. Any difference, in status,
  body, header, ordering, count or timestamp, between what they get for a
  gift with activity and for the same gift without, on any endpoint they
  can call, is an F1 finding, even if it needs several requests to notice.
  Out of the envelope: lock waits of a few milliseconds (an owner deleting a
  gift while a reservation of it commits), which cannot be told from network
  jitter on one request; and the recipient known only by name who joins
  through a forwarded link (NEEDS, Core rules, accepted).
- **Givers see each other.** Invitees of an occasion and the owners of a
  "for someone else" list see each other's display names and pledges on
  that occasion's claims (NEEDS, Invitees among themselves). Invitees of
  another occasion of the same list see only "taken".
- **Concurrency.** Several givers acting on the same gift at the same
  moment, from one occasion or from several of the same list, and any of
  them racing an owner's edit or deletion, a removal, a leave or an account
  deletion, are the normal case (E1). The outcome must be one of the serial
  orders, never a 500 and never a claim breaking D2's invariants. One API
  process and one database (E1): the claim key and row locks are enough,
  no distributed locking.
- **Time.** Expiry reads the API server's UTC clock (one host). Occasions
  dated far in the past or future are valid input (the API accepts any
  date).
- **No background job.** Nothing runs outside a request (D8).
- **Scale.** A claims read is one query over one list's gifts; a group gift
  has at most as many participants as the occasion has members.

## Boundaries crossed

- **Schema (F4):** two new tables, `gift_claims` and `claim_participants`,
  in one migration that adds tables only, so the previous release keeps
  working against it (DevOps plan D15). Its `down_revision` is the head the
  images delivery leaves; downgrade drops both tables.
- **API contract (F4):** six new routes (D6). No existing response changes
  shape or content. Existing endpoints whose behaviour grows, with the same
  answers: `DELETE /api/occasions/{id}/membership`,
  `DELETE /api/occasions/{id}/members/{user_id}`,
  `DELETE /api/occasions/{id}`, `DELETE /api/gifts/{id}`,
  `DELETE /api/lists/{id}`, `DELETE /api/me` (D10, D11). Old clients ignore
  the new routes; the `code` values of D6 and the field names of
  `OccasionClaims` become part of the contract.
- **Stored data:** claims and pledges, with user ids and amounts. Account
  deletion removes every participant row of the user; bought claims survive
  it, and their occasion's deletion, without anyone's identity (D10, D11).
  Expired unbought claims stay in the database until the gift is claimed
  again (D8; Open decisions).
- **Client:** ARB keys `welcomeControlTitle` and `welcomeControlBody` are
  renamed (client-internal). One new client route,
  `/lists/:id/occasions/:occasionId`.

## Conventions

- Every route of D6 resolves through `giving_occasion` (D4) and has rows in
  `server/tests/lists/test_roles.py`; `test_every_route_is_in_the_matrix`
  fails otherwise. The owner of the "for me" list gets 404 on each, the
  owner of the "for someone else" list and the invitee of the occasion get
  success, everyone else 404, signed out 401.
- Claim writes touch only `gift_claims` and `claim_participants` (D3) and
  follow D7's lock order. No endpoint answers a recipient differently
  because of activity (D12); a new owner-facing count, sort or timestamp
  must say why it is independent of claims.
- No `ETag`, `Last-Modified` or caching header on an API response derived
  from anything activity can change.
- Response models list their fields explicitly; no user id in an activity
  response (D6).
- Tests that depend on an occasion not having passed date it relative to
  today (`date.today() + timedelta(days=60)`), never a fixed date: a fixed
  date turns into a passed occasion and a failing test (D8).
- Every server test module that touches claims ends its concurrency and
  release tests with `assert_claims_consistent(engine)` (U1).
- Rose (`inviteeActivity`) for activity chips only; nothing rose on a "for
  me" owner's screen. Every user-visible string in both ARB files, sentence
  case, no emoji; goldens light and dark, regenerated with `.\goldens.ps1`
  only (Linux), never on Windows.
- U1 and U5 change stored data and locking: each gets a unit review before
  integration (DELIVERY §5, point 3).
- Client units come after the images delivery: `GiftCard` already shows
  the gift's image there; these units do not touch image code or the gift
  form.

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Record D8 (the moment an occasion has passed, for expiry), D10's "bought reservations keep the leaver's name" and D11's "bought in a deleted occasion stays taken" in `docs/NEEDS.md`, Reserving; the hidden-gift reveal moment stays open there | NEEDS is the source of features (CLAUDE.md) | Before delivery starts |
| Pledges on a gift with no price carry no amount (D9); a participant-chosen currency would be a request-body addition | Group gifts on unpriced gifts | Revisit if owners report it, no migration needed (`pledge_currency` exists) |
| Group gift composition frozen once bought (D6: no join or leave, only removal, leave of the occasion, account deletion) | Settling up outside the app | Revisit with the notifications plan |
| A purge of expired unbought claims (data minimisation; D8 keeps them until the gift is claimed again) | Stored data, GDPR export | The data-export plan or the hidden-gifts plan, whichever first |
| Showing a giver that a gift "taken" in this occasion is theirs from another occasion (today: "taken", like for anyone) | Invitee of two occasions of one list | Revisit on user feedback |
| Notifications to givers when the owner edits or deletes a gift, and to group participants when one is removed | Notifications plan | That plan |
| A summary of activity in the "for someone else" owner's list detail (today: per occasion only, D14) | Client | Revisit on user feedback |

## Execution units

### Wave 1

#### U1 — Server: claims, reserve, release, bought, and the activity read

- **Goal:** Givers reserve, release and mark gifts bought, and read an
  occasion's activity, with the claim tables, expiry, the giver check and
  exactly-one concurrency; recipients get 404 on all of it.
- **Scope:** `server/app/reserving/**` (new: `__init__.py`, `models.py`,
  `schemas.py`, `rules.py`, `router.py`), `server/app/lists/access.py`
  (add `giving_occasion` only), `server/app/main.py` (include the router),
  `server/alembic/env.py` (import the models),
  `server/alembic/versions/**` (one new revision),
  `server/tests/lists/**` (new `test_reservations.py`,
  `test_concurrent_reservations.py`, `claims_invariants.py`, `locks.py`;
  `test_roles.py` extended; `test_concurrent_join.py` only to import
  `wait_until_blocked_on_a_lock` from `locks.py`).
- **Context:** this plan D1–D8, D12, Conventions;
  `server/app/lists/router.py` (`join` and `remove_member` for the lock
  patterns, `_invalid`, explicit response models);
  `server/app/lists/access.py`; the migration
  `server/alembic/versions/efc657e64bf8_occasions_and_members.py` as the
  example of a new-tables revision; `server/tests/lists/test_roles.py` and
  `test_concurrent_join.py` as the examples for tests. Tests live under
  `server/tests/lists/` to share its conftest (scratch database, accounts,
  `rows`).
- **Do:**
  1. `reserving/models.py`: `GiftClaim`, `ClaimParticipant` per D1, D2,
     with the check constraints and indexes; register in `alembic/env.py`.
  2. One revision (autogenerate, then read it); `down_revision` is the
     current single head (`alembic heads` shows one).
  3. `reserving/rules.py`: `has_passed(date, now) -> bool` per D8 and the
     SQL condition for a live claim (bought, or its occasion not passed);
     `purge_expired(db, gift_id, now)`; `remove_participant(db, gift_id,
     user_id)` that deletes the row and the claim when it is unbought and
     empty (U3 and U5 use it).
  4. `access.py`: `giving_occasion` (D4), taking the occasion `FOR SHARE`
     before the membership check (D7 step 1).
  5. `reserving/schemas.py`: `OccasionClaims`, `GiftClaimOut`,
     `ParticipantOut` (D6), the 409 body.
  6. `reserving/router.py`: `GET …/claims`, `POST` and `DELETE
     …/reservation`, `POST …/bought` per D6, D7, D8. `taken` computed per
     D6. `bought` on a group claim the caller is in is part of this unit
     (U3 adds the pledge routes that create group claims; test it with a
     group claim inserted directly in the database).
  7. `claims_invariants.py`: `assert_claims_consistent(engine)` checking
     D2's invariants and that every participant of an unbought claim is a
     giver of its occasion.
  8. `test_roles.py`: move the scenario's occasion dates to
     `date.today() + timedelta(days=60)`; `Endpoint` gains the status for
     the owner of the "for me" list (`404` for every activity route) and
     `expected` takes the list; rows for the four routes; the scenario
     gains a second gift with activity in each list (reserved in the first
     occasion by its invitee, bought); `owners_view` also records the
     claims as the first occasion's invitee sees them, so a refused call is
     shown to change no activity; every response to the "for me" owner
     contains none of the keys `claims`, `participants`, `pledge_amount`,
     `state`, `bought`, `passed`.
  9. `test_reservations.py`: reserve, double reserve by the same giver →
     200 and one row; a second giver → 409 `taken`; release → free;
     release when holding none → 204; release after bought → 409 `bought`;
     bought from free, from my reservation, idempotent; bought on someone
     else's reservation → 409 `taken`; a gift of another list → 404; the
     owner of a "for someone else" list reserves, and the occasion's
     invitee sees their name; the invitee of the second occasion sees
     `taken` with no participants, no bought flag, no occasion id, and
     gets 409 `taken`; expiry: an occasion dated long ago → `passed: true`,
     writes 409 `passed` except marking bought one's own still-present
     claim (200, and the gift stays `taken` elsewhere), its unbought claim
     no longer shown nor `taken` elsewhere, and claiming the gift in another
     occasion purges it; a
     bought claim of a passed occasion stays `taken`; `has_passed` at
     D + 1 11:59:59 UTC (false) and 12:00:00 UTC (true); no user id in any
     claims response; the "for me" owner gets 404 on every route with the
     random-id body, for each gift state.
  10. `test_concurrent_reservations.py` (real concurrent requests,
      `locks.py` helpers): two invitees of one occasion reserve the same
      gift, released together 20 times → exactly one 200 and one 409 each
      round, one claim row; the same across two occasions of the list; a
      reservation held open uncommitted while a second waits on the key
      → 409 after commit, 200 after rollback; a reservation racing the
      owner's deletion of the gift → 200 or 404, never 500; racing the
      owner's edit of the gift → both succeed; racing a removal of the
      reserver (taken `FOR UPDATE` here directly, as the U2 lists test
      does) → never a claim by a non-member. Each test ends with
      `assert_claims_consistent`.
- **Acceptance:** `uv run --directory server ruff check`;
  `uv run --directory server alembic upgrade head` then `alembic check`;
  `uv run --directory server pytest` (against PostgreSQL) passes, including
  the tests named in Do 8–10 and `test_every_route_is_in_the_matrix`.
- **Out of scope:** pledge routes (U3), release on leave, removal and
  account deletion (U5), occasion deletion keeping bought claims (U5), any
  client change, notifications, a purge job.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); exactly-one cannot
  be shown by the primary key alone; a recipient-facing response would have
  to change; the images delivery left more than one Alembic head.
- **Depends on:** the gift images plan delivered on this branch.

#### U2 — Welcome page copy

- **Goal:** The welcome page says what the app does after this plan: the
  recipient never sees what was chosen, invitees see who gives what and
  team up.
- **Scope:** `client/lib/src/welcome/welcome_screen.dart`,
  `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/test/welcome/**`, `client/test/goldens/welcome_screen_*.png`.
- **Context:** this plan D15 (the exact copy); WEB_LAYOUT_PLAN D8;
  `docs/DESIGN.md` (Localisation). Example to follow: the existing
  `_Features` cards and `client/test/welcome/welcome_screen_test.dart`.
- **Do:**
  1. Replace `welcomePurpose` in both ARB files with D15's text.
  2. Rename `welcomeControlTitle` / `welcomeControlBody` to
     `welcomeSurpriseTitle` / `welcomeSurpriseBody` (with their `@`
     descriptions in EN) and set D15's text.
  3. The third card uses the new keys and `Icons.visibility_off_outlined`.
  4. Update the welcome tests' expected strings (EN and the French run).
  5. Regenerate the welcome goldens with `.\goldens.ps1`.
- **Acceptance:** `flutter analyze` and `flutter test` in `client/` pass
  (ARB parity test included); `welcome_screen_test.dart` finds the new
  purpose sentence and third card title in English and in French and no
  longer finds "You stay in control"; goldens regenerated with
  `.\goldens.ps1` and passing `.\goldens.ps1 -Check`.
- **Out of scope:** the headline, the first two cards, the layout, any
  other screen; any claim about comments or notifications.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed (X3); the new copy does not
  fit the compact or expanded layout without a layout change.
- **Depends on:** — (ships with the rest of the plan on this branch).

### Wave 2

#### U3 — Server: group gifts

- **Goal:** Givers start, join, change their pledge on and leave a group
  gift; the last to leave frees the gift; two givers pledging at once end
  in one group gift.
- **Scope:** `server/app/reserving/router.py`,
  `server/app/reserving/schemas.py`, `server/app/reserving/rules.py`,
  `server/tests/lists/test_group_gifts.py` (new),
  `server/tests/lists/test_concurrent_group_gifts.py` (new),
  `server/tests/lists/test_roles.py`.
- **Context:** this plan D2, D6, D7, D9; U1's reservation routes and tests
  as the example to follow.
- **Do:**
  1. `PUT` and `DELETE …/pledge` per D6, D7 (claim row `FOR UPDATE` before
     changing participants; `remove_participant` from U1), D9 (amount
     bounds, the gift's currency stored with the pledge, 422 without a
     currency).
  2. `test_roles.py`: rows for both routes; the scenario gains a group gift
     in the second occasion of each list: with one pledge on the "for me"
     list (its only giver there is `ME_INVITEE_ELSEWHERE`; the owner is the
     recipient), with two on the "for someone else" list (its owner and
     `OTHER_INVITEE_ELSEWHERE`) (review R1-2).
  3. `test_group_gifts.py`: start, join, change amount, amount `null`,
     leave; last one out → gift free; pledge on a reserved gift (mine or
     someone else's) → 409 `taken`; on a gift held in another occasion →
     409 `taken`; join or leave after bought → 409 `bought`; any
     participant marks bought; amount 0, negative, 19.999 and
     10000000000 → 422; amount on a gift without price → 422; an owner
     changing the gift's currency leaves stored pledges in theirs; the
     invitee of another occasion sees only `taken`; the "for me" owner gets
     404 for every state.
  4. `test_concurrent_group_gifts.py`: two givers pledge on a free gift
     together 20 times → one group claim, two participants; a pledge racing
     a reservation → exactly one wins; a join racing the last participant's
     leave → the joiner ends in a group gift (old or new), never an empty
     claim; a pledge racing mark bought → the pledge is either in the
     bought group or refused 409 `bought`. Each ends with
     `assert_claims_consistent`.
- **Acceptance:** `ruff check`; `alembic upgrade head` then
  `alembic check` (no new revision); `pytest` passes, including the tests
  of Do 2–4.
- **Out of scope:** release on leave, removal and account deletion (U5),
  pledge currencies other than the gift's, settling up, notifications.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a group claim
  invariant needs a schema change.
- **Depends on:** U1.

#### U4 — Client: activity on the invitee's occasion screen

- **Goal:** Invitees see who reserved, bought or pledged on each gift and
  reserve, release, mark bought, start, join and leave group gifts from the
  occasion screen.
- **Scope:** `client/lib/src/shared/shared_repository.dart`,
  `client/lib/src/shared/occasion_screen.dart`,
  `client/lib/src/shared/gift_sheet.dart` (new: the gift's sheet with
  participants and actions), `client/lib/l10n/app_en.arb`,
  `client/lib/l10n/app_fr.arb`, `client/test/shared/**`,
  `client/test/lists/support/fake_lists_server.dart`.
- **Context:** this plan D6 (contract, including the pledge routes U3
  builds in parallel), D9, D13; `docs/DESIGN.md` (Invitee colour,
  Components). Example to follow: the occasion screen's details sheet and
  leave confirmation, `client/test/shared/occasion_screen_test.dart` and
  `shared_golden_test.dart`.
- **Do:**
  1. Repository: `OccasionClaims`, `GiftClaim`, `ClaimParticipant` models;
     `claims(occasionId)`, `reserve`, `release`, `markBought`, `pledge(amount)`,
     `leaveGroup`; a 409 surfaces its `code`.
  2. Fake server: claims per occasion and the six routes with the server's
     rules (taken, bought, passed, idempotent release and leave), and a
     request log the tests can read.
  3. Occasion screen: loads view and claims; chips per D13 (rose
     `inviteeActivity`); the sheet with participants, pledge total when
     every pledge is in the gift's currency, and the actions the state
     allows; none when `passed`; confirmations for release and leave; "Mark
     as bought" says it is final; reload claims after each action or 409; a
     failure shows a snack bar. The pledge dialog shows the gift's currency
     and an optional amount field, no field when the gift has no price.
  4. ARB strings EN and FR for chips, actions, dialogs and errors.
  5. Tests: repository against the fake (each call's method, path and body;
     409 codes); a chip per state; the sheet's actions per state (free,
     reserved by me, reserved by another, group with and without me,
     bought, taken, passed); each action calls the right route and reloads;
     a 409 `taken` reloads and shows the new state; French run of the
     sheet. Goldens light and dark: occasion view with every chip, the
     sheet for a group gift with pledges, the pledge dialog.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 5;
  goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** the owner's screens and the giver mode for "for someone
  else" lists (U6), comments, images (delivered by the images plan),
  offline queueing, the welcome page.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); `GiftCard` or
  `StatusChip` need a change to show a state.
- **Depends on:** U1 (U3's routes are used through the fake, from D6).

### Wave 3

#### U5 — Server: removal, leave, account and occasion deletion effects

- **Goal:** A giver who leaves, is removed or deletes their account and an
  owner who deletes an occasion leave claims exactly as D10 and D11 say,
  with unchanged answers and no race leaving an orphan claim.
- **Scope:** `server/app/reserving/release.py` (new),
  `server/app/lists/router.py` (`leave_occasion`, `remove_member`,
  `delete_occasion` only), `server/app/accounts/router.py` (`delete_me`
  only), `server/tests/lists/test_reservation_release.py` (new),
  `server/tests/lists/test_concurrent_release.py` (new),
  `server/tests/lists/test_account_deletion.py`.
- **Context:** this plan D7, D10, D11; `remove_member` for the occasion
  lock; U1's and U3's routes to create claims in tests;
  `test_concurrent_join.py` as the example for race tests.
- **Do:**
  1. `release_activity` per D10.
  2. `leave_occasion`: take the occasion `FOR UPDATE`, release, then delete
     the membership. `remove_member`: release after its existing lock, in
     the same transaction. Answers unchanged.
  3. `delete_me`: lock the user row `FOR UPDATE`, release in every
     occasion, then the existing list and user deletion.
  4. `delete_occasion`: lock the occasion `FOR UPDATE`, delete its unbought
     claims, then the occasion (the foreign key keeps bought ones with a null
     occasion, D11; review R1-1). List and account deletion: delete the
     lists' claims explicitly before the cascades, so no `SET NULL` can meet
     an unbought claim whatever order Postgres fires the cascades in.
  5. `test_reservation_release.py`, for leave and for removal: an unbought
     reservation is freed; a bought one stays with the name; a pledge on an
     unbought group gift goes, and the group survives other participants;
     the last participant's removal frees the gift; a pledge on a bought
     group gift goes and the gift stays bought; claims in another occasion
     are untouched; the answer is 204 with or without activity. Account
     deletion: the same in every occasion, and a bought reservation stays
     bought with no participants. Occasion deletion: unbought claims go,
     a bought one stays `taken` for the list's other occasion. Gift
     deletion cascades its claim. Each ends with `assert_claims_consistent`.
  6. `test_concurrent_release.py`: a reservation racing the reserver's
     leave, removal, and account deletion (barrier, 20 rounds, and a held
     transaction) → never a claim by a non-member and never a 500; a join
     of a group racing the removal of its last other participant; an
     occasion deletion racing a reservation in it (held transaction) → 204,
     never a 500 (review R1-1).
  7. `test_account_deletion.py`: first date `share()`'s occasion relative
     to today (`date.today() + timedelta(days=60)`), as U1 does for
     `test_roles.py` (review R1-3); then: an account with a bought
     reservation and a pledge is deleted → no row names them, the bought gift
     stays bought.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`;
  `pytest` passes, including the tests of Do 5–7 and the existing
  `test_concurrent_join.py` and `test_roles.py`.
- **Out of scope:** notifications to the other participants, a purge job,
  handover, co-owners.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a release needs a
  schema change; an existing answer would have to change.
- **Depends on:** U1, U3.

#### U6 — Client: owners of a "for someone else" list act as givers

- **Goal:** The owner of a "for someone else" list opens each occasion's
  gifts and reservations and acts like an invitee; the owner of a "for me"
  list sees and calls nothing new.
- **Scope:** `client/lib/src/app_router.dart`,
  `client/lib/src/lists/occasions_section.dart`,
  `client/lib/src/shared/occasion_screen.dart`,
  `client/lib/src/shared/shared_repository.dart`,
  `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/test/lists/**`, `client/test/shared/**`,
  `client/test/app_router_test.dart`.
- **Context:** this plan D4, D14; U4's occasion screen and sheet. Example to
  follow: the occasion members route (`lists/:id/occasions/:occasionId/members`)
  and its card action in `occasions_section.dart`, with
  `client/test/lists/occasions_test.dart`.
- **Do:**
  1. `OwnedOccasion` carries the list's kind and, for an owner view, the
     gifts and occasion fields the screen needs.
  2. Route `lists/:id/occasions/:occasionId` → the occasion screen in giver
     mode: the owner's view plus claims, U4's chips, sheet and actions, no
     leave menu, the privacy banner naming the recipient.
  3. On a "for someone else" list, each occasion card gains "Gifts and
     reservations". On a "for me" list, no such action; `/shared/:id` still
     sends any owner to the list.
  4. Tests: the action exists only for "for someone else" lists; giver
     mode shows chips and acts; on a "for me" list, opening list detail, its
     occasion cards and `/shared/:id` makes no request to any `/claims` or
     activity route (fake server's request log) and shows no rose chip;
     the giver route for a "for me" list goes to the list. Goldens light
     and dark: a "for someone else" occasion card, the giver view.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 4;
  goldens regenerated with `.\goldens.ps1` and passing
  `.\goldens.ps1 -Check`; `flutter build web --release`.
- **Out of scope:** activity in the list detail (Open decisions), handover,
  the invitee screens beyond the mode switch.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); giver mode needs
  more than U4's widgets fed from the owner's view.
- **Depends on:** U4.

### Wave 4

#### U7 — Server: the recipient sees nothing, endpoint by endpoint

- **Goal:** A test suite proves D12: an owner of a "for me" list gets the
  same status, body and headers from every endpoint they can call, whatever
  the activity on their gifts.
- **Scope:** `server/tests/lists/test_surprise.py` (new). Server code only
  if a test fails, through X3.
- **Context:** this plan D3, D4, D10–D12, the Review envelope;
  `server/tests/lists/test_roles.py` (`owners_view`, `walk`, the random-id
  probe) as the example to follow.
- **Do:**
  1. A "for me" list with two gifts identical in every field (G1, G2), two
     occasions dated in the future and one long passed, an invitee in each.
  2. For each activity state of G1 (none; reserved; reserved and bought;
     group gift with pledges; group bought; taken by the other occasion;
     claim of the passed occasion, bought and not; bought for an occasion
     since deleted), with G2 free: every endpoint the owner can call on G1
     answers what it answers on G2, after swapping the two ids: status,
     body and headers apart from `Date`. The endpoint list is derived from
     the OpenAPI document, as `test_every_route_is_in_the_matrix` does, and
     the test fails on a route it does not cover, so routes added by the
     gift-images plan (`/api/images…`, the gift's `image` field) are in it
     (envelope answer, review round 1). Covered: `GET /api/lists`,
     `GET /api/lists/{id}`, `PATCH` and `DELETE /api/gifts/{id}` (on twin
     copies), `GET /api/occasions/{id}`, `GET …/members`, removing the
     invitee who holds the activity versus one who holds none,
     `PATCH` and `DELETE /api/occasions/{id}`, every activity route (404,
     the random-id body). Gift order in every list response is the
     creation order.
  3. A recursive scan of every response the owner gets in those runs: no
     activity key (`claims`, `participants`, `pledge_amount`, `state`,
     `bought`, `passed`, `taken`) and no invitee's display name outside
     `GET …/members`.
  4. The same comparisons for a co-owner of the "for me" list (row added
     directly, as `test_account_deletion.py` does), who was a member of the
     occasion before: blind from then on (D4).
  5. The "for someone else" owner, by contrast, sees the activity through
     the claims route, so the suite fails if D4's check is inverted.
- **Acceptance:** `ruff check`; `pytest` passes with `test_surprise.py`;
  no server file changed, or each change escalated and approved (X3).
- **Out of scope:** hidden gifts, comments, notifications (later plans
  extend this suite).
- **Latitude:** local design.
- **Escalate if:** any comparison fails (an F1 finding: report it, do not
  fix it inside this unit); a file outside Scope is needed (X3).
- **Depends on:** U1, U3, U5.

## Definition of done

- On VAL, two invitees of one occasion open the same gift; one reserves it,
  the other sees "Reserved by <name>" and cannot reserve it; the first
  releases it and the second reserves it, then marks it bought.
- Two invitees start and join a group gift with pledges in the gift's
  currency; one leaves; the last to leave makes the gift available again.
- An invitee of a second occasion of the same list sees a gift reserved in
  the first as "Taken", with no name or occasion, and cannot take it.
- After an occasion's date has passed (12:00 UTC the next day), its
  unbought reservations and group gifts are gone and its gifts can be
  taken in another occasion; a gift bought in it stays taken.
- The owner of a "for someone else" list sees each occasion's activity and
  reserves, pledges and marks bought like an invitee.
- The owner of a "for me" list gets the same answers from every endpoint
  whatever the activity, and gets 404 from every activity route
  (`test_roles.py`, `test_surprise.py`); their screens show nothing rose.
- Two simultaneous reservations of one gift, in one occasion or two, end
  with exactly one claim, in tests running real concurrent requests against
  PostgreSQL.
- Removal, leave, account deletion, gift deletion and occasion deletion
  leave claims as D10 and D11 say, with unchanged answers.
- The welcome page shows D15's copy in English and French.
- All DELIVERY.md §2 checks pass on server and client, goldens included.
