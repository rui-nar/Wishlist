# Admin panel — Plan

## Problem

The owner runs Wishlist and has no view of it except the database. They asked,
on 2026-11-10, to sign in to an admin panel where they can:

- see the registered users, by email;
- see each one's plan, and switch a user to Premium by hand;
- delete an account;
- see the space each user's photos take;
- see the number of lists and the number of gifts per list.

The request is silent: choices are recorded in `docs/NEEDS.md`.

## Current state

- No admin, role or privileged user exists anywhere.
- `server/app/accounts/router.py` `delete_me`: account deletion. It stops
  Stripe first, then locks and deletes. It uses the session only for the user id
  and `lock_for_deletion`.
- `server/app/billing/models.py`: `entitlements.source IN ('stripe','apple',
  'google')`. `entitlements.is_premium` needs `active` or `past_due` and a
  `period_end` later than 3 days ago. `closing.stop_billing` only looks at
  Stripe rows. `GET /api/billing` already returns `source`.
- `server/app/media/models.py`: `images` records `uploaded_by` (set to NULL
  when that user goes), with no size. Each image is two files on disk, written
  once.
- `server/app/lists/visibility.py` `counted`: the gifts the owner sees on a
  list, which excludes hidden and received gifts. `GET /api/lists` uses it for
  `gift_count`.
- `server/tests/lists/test_surprise.py::test_every_route_is_called` requires
  every route to be called by the recipient. `test_roles.py` covers the
  prefixes in `GUARDED_PREFIXES`.

## Decisions

- **D1 — Who is admin: `ADMIN_USER_IDS`**, a comma-separated list of account
  ids in the environment. Rules out admin by email address: accounts are never
  identified by their address (accounts plan D1). With several ways of signing
  in, the address does not prove the account. Empty means no admin. The owner
  finds their id once with `psql` (U5).
- **D2 — Admin routes answer 404 to everyone else**, including when signed out
  and when no admin is configured. Nothing tells a visitor that an admin panel
  exists. `GET /api/me` gains `is_admin`, which is true only for the admin,
  so the client shows the entry. Two other ways would give it away (review
  R1-2). Outside DEV (VAL is public too, review R2-1), FastAPI's `/openapi.json` and `/docs` are not served;
  tests keep reading `app.openapi()` in-process. A catch-all
  `/api/admin/{path:path}` on every method, behind `AdminUser`, answers 404
  where Starlette would otherwise answer 405 for a known path.
- **D3 — A recent sign-in for changes.** Changing a plan or deleting an
  account needs a session created in the last 12 hours. Otherwise the answer is
  401 `reauth_required`, and the client signs out and back in. A copied admin
  token weeks old can read, not change. Rules out a second password, which the
  owner would have to manage.
- **D4 — Every admin change is recorded** in `admin_actions`: `id`,
  `admin_user_id` (null once that account goes), `action`, `target_user_id`
  (no foreign key, so it outlives the account), `detail` (JSON of ids and
  dates only), `created_at`. Logs carry ids and fixed words, never an address.
- **D5 — The users list:** `GET /api/admin/users?q=&cursor=`, 50 per page,
  newest first, `q` matching inside the address, case-insensitive. Per user:
  id, email, display name, created, ways of signing in, plan (free or premium,
  source, until when), lists owned, photos (count and bytes).
- **D6 — One user:** `GET /api/admin/users/{id}` adds the lists they own, each
  with title, created date, `gift_count` from `visibility.counted`, and the
  number of owners. **Counts only:** no gift, reservation, pledge, comment or
  occasion member is shown. The admin is a user of the app too. Hidden and
  received gifts never count, so nothing here changes with what givers do,
  even on a list for the admin. Rules out showing gift titles, which nobody
  asked for.
- **D7 — Photo space is counted by uploader**, the account that sent the file,
  **only for images attached to a gift the list's recipient can see**: a gift
  on a list, received or not, or a revealed hidden gift. A hidden gift's photo
  and a pending upload are a giver's activity. Counted, they would move a
  giver's figures when they prepare a surprise for the admin (review R1-1).
  They count for no one, and the panel shows no instance-wide total, which
  would move too. Counting by list owner would put a giver's photo on the
  recipient's account. `images.bytes` (nullable) holds the size of both files,
  set at upload. Rows that predate it are filled by a backfill of their own on
  the media thread's timer, a few hundred per run. It runs whether or not
  `BACKUP_DIR` is set and whatever the purge's horizon, since it only reads
  sizes (review R1-4). Until then the panel says "measuring". An image whose
  uploader is gone counts for no one.
- **D8 — Manual Premium:** a new entitlement source `manual`, with `external_id`
  a new uuid, `status` `active`, and a `period_end` the admin chooses (one year
  ahead by default, a date at most 10 years ahead). The admin can end it: status
  `ended`. It can coexist with a Stripe subscription, and either grants Premium.
  `stop_billing` ignores it, and it goes with the account. `GET /api/billing`
  says `source: manual`, and the plan screen shows "Premium, granted until
  <date>". The Manage button still follows `can_manage` alone, so someone who
  also pays through Stripe can still reach the portal (review R1-3). An expired
  manual grant is its expected end, so `warn_if_lapsed` leaves `manual` rows
  out (review R1-6). Rules out an "unlimited" flag outside entitlements, which
  every Premium check would have to learn.
- **D9 — Deleting an account from the panel** goes through the same code as
  `DELETE /api/me`: its body moves into `accounts/deletion.py`
  `delete_account(db, state, user_id)`, with Stripe stopped first, the same
  locks and the same refusals (502 and 409 `billing_unavailable`). The admin
  types the account's address to confirm. The server checks it,
  case-insensitively, and answers 422 when it differs. The admin cannot delete
  their own account here (409 `use_account_screen`): their request holds their
  own row, and their account screen already does it.
- **D10 — The client.** `/admin` (the users) and `/admin/users/:id` (one user)
  in the same app. On a wide screen there is a table; on a phone, cards. Reached
  from the account screen when `is_admin`. A signed-in non-admin opening
  `/admin` sees "not found". Read-only parts work on every platform. The two
  changes ask for confirmation.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **A new privileged role.** Any way for a non-admin to read or change through
  `/api/admin`, or to learn that it exists, is F1. An admin is trusted (E3),
  but an old copied token of theirs is not (D3).
- **The surprise floor applies to the admin**, a user like any other: any
  admin answer that differs with invitee activity on a list the admin is the
  recipient of is F1. That includes counts, sizes and order.
- **Irreversible actions.** A deletion of the wrong account, or one that leaves
  a Stripe subscription billing, is F2 or F3.
- **Scale.** A few hundred users. The list is paginated, and sizes are read
  from the database, never from the disk in a request.
- **Out of the envelope:** several admins with different rights, an
  impersonation feature, exporting user data.

## Boundaries crossed

- **Schema (F4):** one migration. It adds `images.bytes` (nullable) and the
  `admin_actions` table. It also adds `manual` to the `source` CHECK on
  `entitlements` and `billing_customers`. The previous release ignores the
  column and table. A `manual` row is honoured by the previous release
  (`_in_force` does not read `source`), so rollback stays image-only. Downgrade
  deletes `manual` rows first.
- **API (F4):** new routes under `/api/admin`. `GET /api/me` gains `is_admin`,
  which old clients ignore (E5). `GET /api/billing` may say `manual`, and old
  clients show it as Premium. `/openapi.json` and `/docs` stop being served
  outside DEV, and nothing uses them.
- **Stored data:** the audit rows, and photo sizes.
- **Environment:** `ADMIN_USER_IDS`, empty by default.

## Conventions

- Admin routes use one dependency, `AdminUser`, which answers 404, never 403.
  A test lists every `/api/admin` route and checks it for signed out, a
  non-admin, and no admin configured.
- `/api/admin` joins `GUARDED_PREFIXES`; its routes go in `COVERED_ELSEWHERE`
  with their own tests, and are called by the recipient in `test_surprise.py`.
- A gift count goes through `visibility.counted` only.
- No address in any log. The audit's `detail` holds ids and dates only.
- Every string in both ARB files; goldens light and dark through `.\goldens.ps1`.
- U1 and U2 get a unit review before integration (DELIVERY §5, point 3).
- Commits a user would notice carry a `Release-Note:` trailer in English.

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| A second admin, or rights per admin | D1 | Revisit if anyone but the owner needs access |
| Telling a person their Premium was granted or their account deleted | Email | Revisit on the owner's request |

## Execution units

### Wave 1

#### U1 — Server: admin identity, schema, photo sizes

- **Goal:** The admin is recognised, recent sign-in can be checked, and the
  schema and photo sizes are in place.
- **Scope:** `server/app/settings.py`, `server/app/accounts/deps.py`,
  `server/app/accounts/router.py` (`is_admin` in `UserOut` only),
  `server/app/accounts/schemas.py`, `server/app/admin/__init__.py`,
  `server/app/admin/models.py` (new), `server/app/billing/models.py` (the
  CHECKs and the `MANUAL` constant only), `server/app/media/models.py`,
  `server/app/media/images.py` (record `bytes` at upload),
  `server/app/media/purge.py` and `server/app/main.py` (the media thread: the
  backfill, outside the purge's guards; the production `openapi_url`),
  `server/app/billing/entitlements.py` (`warn_if_lapsed` only),
  `server/alembic/env.py`, `server/alembic/versions/**`,
  `server/tests/admin/**` (new), `server/tests/media/**`,
  `server/tests/accounts/**`, `server/tests/test_migrations.py`,
  `deploy/prod/.env.example`, `deploy/val/.env.example`, `.env.example`.
- **Context:** D1–D4, D7, D8 (schema only), Boundaries crossed. Example:
  `accounts/deps.py` `CurrentUser`; the billing migration `c4f7d2a81e65`.
- **Do:** `admin_user_ids` setting; `AdminUser` and `RecentAdminUser`
  dependencies (D2, D3); the migration; `bytes` at upload; the backfill step;
  `is_admin` in `/api/me`; the env examples.
- **Acceptance:** tests for the dependencies (404 cases, 401
  `reauth_required` past 12 hours), upload records the size, the backfill
  fills old rows and skips missing files; the migration up and down with a
  `manual` row; `ruff check`.
- **Out of scope:** routes.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

### Wave 2

#### U2 — Server: the admin routes and shared deletion

- **Goal:** The admin can list users, read one, grant or end Premium, and
  delete an account.
- **Scope:** `server/app/admin/router.py`, `server/app/admin/schemas.py`,
  `server/app/admin/queries.py` (new), `server/app/accounts/deletion.py`
  (new), `server/app/accounts/router.py` (`delete_me` calling it),
  `server/app/main.py` (include the router), `server/tests/admin/**`,
  `server/tests/lists/test_roles.py` (the prefix and `COVERED_ELSEWHERE`
  rows), `server/tests/lists/test_surprise.py` (calls).
- **Context:** D5, D6, D8, D9, the Conventions. Example: `billing/router.py`
  for refusals with a `code`; `lists/router.py` for `gift_count`.
- **Do:** the routes; `delete_account` moved with no change in behaviour (the
  existing deletion tests pass unchanged); the audit rows.
- **Acceptance:** tests for each route, the 404 matrix, pagination and search,
  counts and photo figures unchanged by invitee activity in two worlds (the
  admin as recipient, looking at the giver's row and the admin's own, with a
  hidden gift with a photo and a pending upload), the catch-all 404,
  manual Premium granted, ended, honoured by `is_premium`, and coexisting with
  Stripe, deletion confirming the address, refusing self, stopping Stripe;
  the full `tests/accounts`, `tests/billing`, `tests/lists/test_roles.py` and
  `test_surprise.py`; `ruff check`.
- **Out of scope:** client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1.

### Wave 3

#### U3 — Client: the admin panel and the manual plan

- **Goal:** The owner uses the panel from the account screen, and a manual
  Premium reads correctly.
- **Scope:** `client/lib/src/admin/**` (new), `client/lib/src/app_router.dart`,
  `client/lib/src/auth/account_screen.dart`, `client/lib/src/auth/auth_controller.dart`
  (`isAdmin`), `client/lib/src/billing/plan_screen.dart`,
  `client/lib/src/billing/billing_repository.dart`, `client/lib/l10n/*.arb`,
  `client/test/**`.
- **Context:** D2, D3, D5–D10. Example: `lists/my_lists_screen.dart`
  for loading and failure; `billing/plan_screen.dart` for confirmations.
- **Do:** the two screens, search, paging, sizes in readable units, the two
  actions with confirmation (typed address for deletion), `reauth_required`
  handled, the account entry, and the manual plan line.
- **Acceptance:** widget tests for each state and action; goldens light and
  dark, phone and wide; `flutter analyze`, `flutter test -j 2`, goldens
  `-Check`.
- **Out of scope:** server.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U2.

#### U4 — Runbook

- **Goal:** The owner can make themselves admin.
- **Scope:** `docs/DEPLOYMENT.md`.
- **Context:** D1, D3. Example: the runbook's `pg` query blocks.
- **Do:** an "Admin" section: find your id (`select id, created_at from users
  where email = '<owner-address>'`, choosing the right one if several),
  set `ADMIN_USER_IDS`, `up -d`, check that `/api/me` says `is_admin`; the
  12-hour rule; the audit table; the release step for the variable.
- **Acceptance:** no real address or id committed.
- **Out of scope:** code.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U2.

## Definition of done

- With `ADMIN_USER_IDS` empty, nothing changes for anyone, and `/api/admin`
  answers 404.
- The admin sees every user with their plan, lists, photo space and gift
  counts, can grant and end Premium, and can delete an account.
- No admin answer changes with invitee activity.
- All checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
