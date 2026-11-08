# Lists, gifts and sharing — the first usable version

## Problem

With accounts in place (`docs/plans/ACCOUNTS_PLAN.md`), the product still does
nothing a user wants. The owner asked for a first deployable version where a
signed-in person can create and delete lists, add, edit and remove gift wishes,
and share a list with invitees. This plan delivers that slice of
`docs/NEEDS.md`:

- **Lists and occasions:** permanent lists, shared for occasions, with
  invitees belonging to an occasion.
- **Gifts:** title, description, shop links, an indicative price.
- **Access:** occasion links, revoking a link, removing an invitee.

What invitees *do* (reserving, group gifts, hidden gifts, comments),
notifications, images, limits and premium come in later plans. The data model
chosen here must not need rewriting when they arrive.

## Current state

- After the accounts plan: `users`, `user_identities`, `sessions`; the
  `current_user` and `db_session` dependencies; `server/app/accounts/` as the
  feature layout; `DELETE /api/me`.
- The client has go_router with a sign-in guard and a `from` return location,
  `AuthController`, `ApiClient`, the design system (`GiftCard`, `StatusChip`,
  `PrivacyBanner`) and EN/FR ARB files.
- `/api/config` returns `google_client_id`.

## Decisions

- **D1 — Lists have owners, through a table.** `lists`: `id` (UUID),
  `title` (1–100), `recipient_kind` (`self` | `other`), `recipient_name`
  (1–100, required when `other`, null when `self`), `created_at`, `updated_at`. `list_owners`:
  (`list_id`, `user_id`), both FKs cascading, primary key on the pair. The
  creator is the only owner for now; co-owners are a need (`docs/NEEDS.md`),
  so ownership is a table from the start rather than a `lists.owner_id`
  column that a later plan would have to migrate. Who may add co-owners is
  still an open question in the needs; no endpoint adds one yet.
- **D2 — "For me" or "for someone else" is chosen at creation.** It decides
  who is blind once invitee activity exists. The kind cannot change through
  the API (a "for me" list may never become "for someone else", `docs/NEEDS.md`;
  the other direction is the handover feature, later). The recipient's name
  can be edited.
- **D3 — Gifts.** `gifts`: `id`, `list_id` (FK cascade), `title` (1–200),
  `description` (0–2000), `links` (Postgres `text[]`, at most 10, each an
  absolute `http` or `https` URL of at most 2048 characters), `price_amount`
  (`numeric(12,2)`, ≥ 0, at most 10 integer digits and 2 decimals, checked by
  the request schema so a larger or more precise value answers 422 instead of
  overflowing or being rounded; optional) and `price_currency` (ISO 4217 code from a
  fixed list in the server, required when an amount is given), `created_at`,
  `updated_at`. Gifts are listed oldest first. Images are a later plan
  (media storage, link fetching, purge rules: R2-5 of the DevOps review).
  "Received" marking is a later plan too (it ends an occasion's lifecycle).
- **D4 — Occasions and invitees.** `occasions`: `id`, `list_id` (FK cascade),
  `name` (1–100), `date` (a calendar date, no time; the exact moment it is
  "reached" is an open question for hidden gifts, not needed yet),
  `join_token` (nullable, unique), `created_at`. `occasion_members`:
  (`occasion_id`, `user_id`), FKs cascade, `joined_at`. Invitees belong to an
  occasion, not to the list (`docs/NEEDS.md`).
- **D5 — Joining by link.** The owner creates an occasion's link: a random
  token (`secrets.token_urlsafe(16)`), stored as is so the owner can copy the
  link again later. The link is `<PUBLIC_BASE_URL>/join/<token>`
  (`PUBLIC_BASE_URL` from settings, returned by `/api/config` for the mobile
  apps; on the web the client uses its own origin). Opening it requires
  signing in (the accounts plan's `from` return). The client then shows a
  confirmation screen built from `POST /api/join/preview` (occasion name and
  date, list title, recipient, owners' names) and joins only when the user
  confirms, with `POST /api/join`, which makes the user a member and returns
  the occasion's id. Both endpoints take the token in the JSON body
  (`{"token": "..."}`), never in the URL, so it does not reach access logs
  (round-1 envelope answers). Joining twice is not an error (200, same
  occasion). Regenerating the link
  replaces the token, so the old link stops working; revoking sets it to null.
  Members who already joined keep access (`docs/NEEDS.md`, Access).
- **D6 — Owners cannot join their own occasion.** An owner of the list
  (recipient or not) who opens the link gets 409 "you own this list" and the
  client opens the list instead: the 409 body carries `list_id`, and the
  preview answers with `"role": "owner"` and the `list_id`, so the client opens
  the list without offering to join (review R1-3). For a "for me" list this is the needs' rule
  ("a recipient cannot join their own occasion"); for a "for someone else"
  list the owner already sees everything an invitee sees.
- **D7 — Authorization in two functions, and 404 for everything hidden.**
  `server/app/lists/access.py` has `owned_list(db, user, list_id)` and
  `visible_occasion(db, user, occasion_id) -> (occasion, role)` where role is
  `owner` or `invitee`. Every endpoint goes through one of them. Anything the
  user may not see answers 404, the same as something that does not exist, so
  ids cannot be probed. A role test matrix (D10) proves it per endpoint.
- **D8 — Endpoints.** All require `current_user`.

  | Method and path | Who | What |
  |---|---|---|
  | `GET /api/lists` | owner | lists I own, with gift count and occasion count |
  | `POST /api/lists` | anyone | create; I become the owner |
  | `GET /api/lists/{id}` | owner | the list, its gifts and its occasions (with link and member count) |
  | `PATCH /api/lists/{id}` | owner | title, recipient name |
  | `DELETE /api/lists/{id}` | owner | delete with its gifts, occasions and memberships |
  | `POST /api/lists/{id}/gifts` | owner | add a gift |
  | `PATCH /api/gifts/{id}` | owner | edit any field |
  | `DELETE /api/gifts/{id}` | owner | remove |
  | `POST /api/lists/{id}/occasions` | owner | create an occasion (name, date) |
  | `PATCH /api/occasions/{id}` | owner | rename, change date |
  | `DELETE /api/occasions/{id}` | owner | delete, with its memberships |
  | `POST /api/occasions/{id}/link` | owner | create or regenerate the link |
  | `DELETE /api/occasions/{id}/link` | owner | revoke the link |
  | `GET /api/occasions/{id}/members` | owner | who joined (display names) |
  | `DELETE /api/occasions/{id}/members/{user_id}` | owner | remove an invitee |
  | `POST /api/join/preview` `{"token"}` | anyone signed in | occasion name and date, list title, recipient, owners' names, and `role` (`owner`, `member` or `none`), with `list_id` for an owner and `occasion_id` for a member; 404 for an unknown or revoked token |
  | `POST /api/join` `{"token"}` | anyone signed in | join → `{"occasion_id"}`; 404 for an unknown or revoked token; 409 `{"list_id"}` for an owner |
  | `GET /api/shared` | invitee | occasions I joined: occasion name and date, list title, recipient, owner names |
  | `GET /api/occasions/{id}` | owner or invitee | the occasion, its list and its gifts, in a per-role model (below) |
  | `DELETE /api/occasions/{id}/membership` | invitee | leave the occasion |

  The invitee's view of an occasion (`GET /api/occasions/{id}` for a member,
  and `GET /api/shared`) has its own response model: occasion id, name and
  date; list title; the recipient's display name (`recipient_name`, or the
  owners' display names for a "for me" list); the owners' display names; the
  gifts. It never contains a join token, a member list or the list's other
  occasions: those are in owners' models only (review R1-1, R1-4).

  Responses are Pydantic models listing their fields explicitly; no endpoint
  serialises a model object wholesale, so a later column (a reservation, a
  hidden flag) never appears in a response unless a plan adds it.
- **D9 — Account deletion (extends ACCOUNTS D8).** Deleting a user deletes the
  lists they are the only owner of (with everything under them) and their
  memberships; lists with another owner keep existing (no such list can exist
  yet, but the rule is written now). This follows `docs/NEEDS.md`, "Deleting
  an account".
- **D10 — The surprise rule is tested per role from now on.** A test module
  `server/tests/lists/test_roles.py` builds one scenario (a "for me" list and
  a "for someone else" list, each with an occasion, an invitee, an owner and a
  stranger) and checks, for every endpoint of D8, what each role gets. Today
  there is no invitee activity to hide, so the matrix proves access (owners and
  members see what they should, strangers and removed members get 404, owners
  of a "for me" list cannot become invitees) and content: every response an
  invitee or a stranger receives is scanned recursively and contains no
  `join_token` key and no id of an occasion they are not a member of. Later plans add their activity
  to the same scenario and assert the recipient sees none of it. Members'
  identities are shown only to the list's owners and are not activity.
- **D11 — Client structure.** `client/lib/src/lists/` (my lists, list
  detail, list form, gift form, occasion form and share sheet) and
  `client/lib/src/shared/` (shared with me, occasion view, join screen). A
  small repository class per feature wraps `ApiClient`; screens use
  `provider` like the accounts screens. Home (`/`) becomes "My lists", with a
  second destination "Shared with me" in a `NavigationBar`; the account screen
  stays in the app bar.
- **D12 — Links open outside the app.** Gift links open with `url_launcher`
  in the external browser; only `http` and `https` are accepted by the server
  (D3) and checked again by the client before launching.
- **D13 — Prices are indicative and shown in the viewer's locale.** Amount and
  currency are stored as given; the client formats them with `intl` in the
  current locale (`149,00 €` in French, `€149.00` in English). No conversion.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **Join tokens never travel in API URLs.** The API takes them in request
  bodies; the client's `/join/<token>` route keeps the token in the browser's
  history, which is accepted (whoever reads it already holds the link).
- **Joining is explicit.** Opening a link shows what will be joined and asks
  for confirmation; nothing is joined on a click alone.
- **Share links are bearer capabilities.** Anyone holding an occasion's link
  can join it after signing in; forwarding is expected (`docs/NEEDS.md`,
  Access). The owner's control is regenerating or revoking the link and
  removing members. A recipient known only by name who receives a forwarded
  link can join: an accepted limitation of the needs. Tokens are 128-bit
  random, stored in plain text in the database (the owner must be able to copy
  the link again); a database leak is already a full compromise.
- **Gift content is user input shown to other users.** Titles, descriptions
  and links are rendered as plain text by Flutter; no HTML is ever built from
  them. Links are restricted to `http` and `https`.
- **Concurrency.** Owner edits are last-write-wins (one owner today; offline
  sync and co-owners are later plans). Joining and removing a member at the
  same moment must leave a consistent state (the member row exists or not; no
  error other than 404).
- **Scale.** No limits are enforced yet (Open decisions); request validation
  caps field sizes and link counts so a single request stays small.

## Boundaries crossed

- **Schema (F4):** `lists`, `list_owners`, `gifts`, `occasions`,
  `occasion_members`, in migrations that keep the previous release working
  (new tables only).
- **API contract (F4):** the endpoints of D8. Additions later; no shape
  changes.
- **Stored data:** users' lists and gifts; deletion as in D9.
- **Share link format:** `/join/<token>` becomes a URL people paste into
  messages; it must keep working for as long as the link is not regenerated.

## Conventions

- Every endpoint resolves its object through `owned_list` or
  `visible_occasion` (D7); `test_roles.py` covers every endpoint for every
  role. A new endpoint without a row in the matrix fails review.
- Response models list fields explicitly (D8).
- 404 for anything hidden; 409 only for "you own this list" on join; 422 for
  validation (FastAPI's default).
- Every user-visible string in both ARB files; widgets from the design system;
  goldens for each new screen in light and dark.

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Free-plan limits (1 list, 20 gifts) are not enforced until the premium plan | Users created before enforcement may hold more; they keep them and cannot grow (`docs/NEEDS.md`) | The premium plan |
| Gift images (upload, fetch from shop link, size limits) | Media storage, backups (R2-5) | A later plan |
| Who can add co-owners | `list_owners` endpoints | The co-owners plan |
| Mobile app links (`/join/<token>` opening the installed app) | Android App Links, iOS universal links | Before the first store release |
| `PUBLIC_BASE_URL` for VAL and PROD | Share links from the mobile apps | When the domain is decided |

## Execution units

### Wave 1

#### U1 — Server lists and gifts

- **Goal:** Owners create, read, update and delete lists and their gifts
  through the API, with authorization and account-deletion rules.
- **Scope:** `server/app/lists/**`, `server/app/main.py`,
  `server/alembic/env.py`, `server/alembic/versions/**` (one new revision),
  `server/app/accounts/router.py` (deletion only), `server/tests/lists/**`.
- **Context:** D1–D3, D7–D9 of this plan; `server/app/accounts/` (models,
  schemas, router, deps) and `server/tests/accounts/` as the example.
- **Do:**
  1. `lists/models.py`: `List`, `ListOwner`, `Gift` (D1, D3), with check
     constraints for the recipient rule and the price rule.
  2. `lists/currencies.py`: the accepted ISO 4217 codes (the active ones).
  3. `lists/schemas.py`: create/update/read models with the limits of D3;
     URL validation (absolute, `http`/`https`, length).
  4. `lists/access.py`: `owned_list` (D7); `visible_occasion` is added by U2.
  5. `lists/router.py`: the list and gift rows of D8.
  6. Account deletion: `DELETE /api/me` deletes the lists the user owns
     alone before deleting the user (D9), in the same transaction.
  7. One Alembic revision; read it.
  8. Tests:
     - list CRUD; recipient rules (`other` requires a name, `self` refuses
       one, the kind cannot be changed by `PATCH`); a title or recipient name
       of 101 characters → 422;
     - gift CRUD; validation (title length, 11 links refused, `javascript:`
       and relative URLs refused, a currency without an amount refused, an
       unknown currency refused, a negative price refused, 10000000000 and
       19.999 → 422);
     - `test_roles.py` with the scenario of D10 for the endpoints of this
       unit: owner allowed; another user, and an unauthenticated request, get
       404 and 401 respectively; ids of other users' lists and gifts are
       indistinguishable from random UUIDs;
     - deleting a list deletes its gifts; deleting the account deletes the
       user's lists and gifts and nothing of another user's.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`;
  `pytest` passes.
- **Out of scope:** occasions and sharing (U2), images, limits, co-owner
  endpoints, ordering by priority.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3); the `text[]` column
  does not round-trip through SQLAlchemy cleanly.
- **Depends on:** the accounts plan delivered.

### Wave 2

#### U2 — Server occasions, links and members

- **Goal:** Owners create occasions and share them by link; signed-in users
  join; invitees read the occasion's list and gifts; owners revoke links and
  remove invitees; invitees leave.
- **Scope:** `server/app/lists/**`, `server/app/settings.py`,
  `server/app/main.py` (`/api/config` gains `public_base_url`),
  `server/alembic/versions/**` (one new revision), `server/tests/lists/**`,
  `server/tests/accounts/**` (the config test only).
- **Context:** D4–D10 of this plan; U1's router and `test_roles.py` as the
  example.
- **Do:**
  1. Models `Occasion`, `OccasionMember` (D4); one revision.
  2. `PUBLIC_BASE_URL` setting (empty in DEV: the web client composes the link
     from its own origin) and `public_base_url` in `/api/config`.
  3. `visible_occasion` in `access.py`.
  4. The occasion, link, member, join, shared and membership rows of D8.
  5. Account deletion: memberships cascade; covered by a test.
  6. Extend `test_roles.py` to every endpoint of this unit and these cases:
     - an invitee sees the occasion's list and gifts, and only through
       `GET /api/occasions/{id}` and `GET /api/shared`; every owner endpoint
       answers 404 to them;
     - an invitee of occasion A cannot read occasion B of the same list;
     - a stranger gets 404 everywhere, including with a valid occasion id;
     - owners of a "for me" list and of a "for someone else" list get 409 on
       join with their `list_id`, and `role: owner` with `list_id` on preview;
       a member gets `role: member` with the occasion id; anyone else
       `role: none` and no ids;
     - content: every response to an invitee, a stranger or a preview is
       scanned recursively and contains no `join_token` key and no id of an
       occasion the caller is not a member of (an invitee of occasion A sees
       nothing of occasion B, even though both are on one list);
     - the invitee model names the recipient: `recipient_name` for a "for
       someone else" list, the owner's display name for a "for me" list;
     - the token is accepted only in the body: `POST /api/join/<token>` is
       404;
     - an unknown, regenerated-away or revoked token → 404;
     - a removed invitee gets 404 afterwards and can rejoin only with a
       current link;
     - an invitee who leaves gets 404 afterwards;
     - members' display names are returned only to owners.
  7. Join twice → 200, one membership row; join concurrently with removal
     (two threads) → no 500.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`;
  `pytest` passes.
- **Out of scope:** reservations, hidden gifts, comments, notifications,
  mobile app links.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3); a role case in the
  matrix cannot be expressed with the scenario of D10.
- **Depends on:** U1.

#### U3 — Client lists and gifts

- **Goal:** In the app, owners see their lists, create, rename and delete
  them, and add, edit and remove gifts.
- **Scope:** `client/lib/src/lists/**`, `client/lib/src/home/**`,
  `client/lib/src/app_router.dart`, `client/lib/l10n/**`,
  `client/pubspec.yaml`, `client/pubspec.lock`, `client/test/lists/**`,
  `client/test/home/**`.
- **Context:** D1–D3, D8, D11–D13; the accounts plan's
  `client/lib/src/auth/` screens and tests as the example; `docs/DESIGN.md`
  and the Lagoon mock-up for the look; `GiftCard` for each gift.
- **Do:**
  1. `ListsRepository` over `ApiClient` (U1's endpoints).
  2. Screens: My lists (empty state, create button), list form (title, "for
     me" / "for someone else" with a name), list detail (gifts as `GiftCard`s
     with price and link count; add gift; tap to edit; delete from the edit
     screen with confirmation; rename and delete the list from a menu), gift
     form (title, description, links as a growable list of fields with
     `http`/`https` validation, price and currency with EUR as the default).
  3. Routes `/lists/:id`, `/lists/:id/gifts/new`, `/gifts/:id/edit` (or the
     equivalent under the list), guarded by sign-in.
  4. `url_launcher` for gift links (D12).
  5. Price formatting with `intl` (D13).
  6. Tests: repository against a `MockClient`; each screen's states (loading,
     empty, error, content); form validation (empty title, bad URL, currency
     without amount); delete asks for confirmation; French run of the gift
     form. Goldens: My lists (empty, with lists), list detail, gift form, in
     light and dark.
- **Acceptance:** `flutter analyze`; `flutter test`; `.\goldens.ps1 -Check`;
  `flutter build web --release`.
- **Out of scope:** occasions and sharing screens (U4), images, reordering.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U1 (API contract; can start from D8 and U1's schemas).

### Wave 3

#### U4 — Client occasions and sharing

- **Goal:** Owners create occasions and copy or share their links, see and
  remove invitees, revoke links; invitees join from a link and browse what was
  shared with them.
- **Scope:** `client/lib/src/lists/**`, `client/lib/src/shared/**`,
  `client/lib/src/home/**`, `client/lib/src/app_router.dart`,
  `client/lib/l10n/**`, `client/pubspec.yaml`, `client/pubspec.lock`,
  `client/test/lists/**`, `client/test/shared/**`, `client/test/home/**`.
- **Context:** D4–D6, D8, D11; U3's screens and tests as the example;
  `PrivacyBanner` on the invitee's occasion view, as in the mock-up.
- **Do:**
  1. In list detail, an Occasions section: create (name, date picker),
     each occasion with its date, member count and actions: copy link,
     share link (`share_plus`), regenerate (with a warning that the old link
     stops working), revoke, see members and remove one (confirmation),
     rename, delete.
  2. `/join/:token`: signed-out users go through sign-in and come back (the
     accounts plan's `from`); then `POST /api/join/preview` and a
     confirmation screen (occasion, date, list, recipient, owners; "Join" and
     "Cancel"); "Join" calls `POST /api/join` and opens the occasion; a
     member is taken straight to the occasion; on 404 explain the link is no
     longer valid; for an owner (preview role or a 409) open
     the list as its owner.
  3. "Shared with me" destination: occasions joined (occasion, date, list,
     recipient, owner), each opening a read-only occasion view: list title,
     recipient, the privacy banner ("<recipient> doesn't see what you do
     here" wording from the ARB), gifts as `GiftCard`s with links and price;
     leave the occasion from a menu.
  4. The share link uses `public_base_url` from `/api/config` when set,
     otherwise the web client's own origin.
  5. Tests: join flow (signed out → sign-in → back → joined; 404; 409);
     occasion actions call the right endpoints; members list and removal;
     shared-with-me states; the invitee view has no edit controls. Goldens:
     occasion section, shared with me, occasion view, join error, light and
     dark.
- **Acceptance:** `flutter analyze`; `flutter test`; `.\goldens.ps1 -Check`;
  `flutter build web --release`.
- **Out of scope:** reservations and other invitee actions, notifications,
  mobile app links.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U2, U3.

## Definition of done

- On VAL, the owner signs in with Google, creates a "for me" list and a "for
  someone else" list, adds gifts with links and prices, edits and removes
  them, and deletes a list.
- The owner creates an occasion, copies its link, and a second Google account
  opening the link in another browser signs in, joins, and sees the list and
  its gifts read-only under "Shared with me".
- Regenerating or revoking the link stops new joins; the joined invitee keeps
  access; removing the invitee removes their access.
- The owner opening their own occasion link lands on their list, not as an
  invitee.
- `test_roles.py` covers every endpoint for owner, invitee, invitee of another
  occasion, stranger and signed-out user; a stranger gets 404 for every id.
- Deleting an account removes the lists it owned alone and its memberships.
- Every screen works in English and French, light and dark, with goldens.
