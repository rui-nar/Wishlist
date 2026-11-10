# Apple and email sign-in — Plan

## Problem

Google is the only way in. Someone without a Google account cannot use
Wishlist, and `docs/NEEDS.md` Constraints asks for Google, Apple and email with
password. The accounts plan kept the `user_identities` table so that these
would add rows, not columns.

The owner asked for this silently on 2026-11-10. Their decisions become
env placeholders, and the choices made here are recorded in `docs/NEEDS.md`.

## Current state

- `server/app/accounts/router.py`: `POST /api/auth/google`, sessions, and
  `DELETE /api/me`. `_user_for` finds an account by `(provider, subject)`,
  never by email (accounts plan D1).
- `server/app/accounts/models.py`: `users.email` is NOT NULL, not unique, for
  display. `user_identities` is unique on `(provider, subject)` and cascades.
- `server/app/accounts/google.py`: the verifier, with fixed failure labels, in
  `app.state.google_verifier`, replaced by a fake in tests.
- `server/app/notifications/mailer.py`: `app.state.mailer.send(...)`, None until
  the email variables are set. `notifications/worker.py` runs every 15 s,
  safe with two processes (`SKIP LOCKED`). The non-production allowlist
  (`Settings.email_allowed_addresses`) is applied only in `digests.py`.
- `server/app/main.py`: `GET /api/config`, read by clients at start.
- `client/lib/src/auth/`: `sign_in_screen.dart` shows "not configured" when
  there is no Google client ID; `auth_controller.dart` holds the session.
- `client/lib/src/shared/pending_join.dart`: a share token waits in
  `sessionStorage`, which a new tab does not see.
- No rate limiting exists anywhere. `request.client.host` is correct behind
  Caddy (`--proxy-headers`, `FORWARDED_ALLOW_IPS`). No password-hash or JWT
  library is present.

## Decisions

- **D1 — Accounts stay separate per way of signing in.** An account is found
  by `(provider, subject)` only, as today. Signing in with Apple or a password
  never joins a Google account that has the same address. Joining by address
  would let whoever controls an address, or a provider with weaker checks, take
  an account over. Rules out automatic linking. Deliberate linking from a
  signed-in account is an Open decision.
- **D2 — The email address is proven before the password exists.** One flow
  serves both creating an account and resetting a password: the person types
  an address, gets a link, and chooses the password on the page it opens. Rules
  out the usual form with address and password together, where an attacker
  registers a victim's address with their own password and the victim's click
  on "verify" activates an account the attacker can enter. It also keeps
  unverified addresses, which `google.py` refuses because they are shown to
  other users, out of `users` altogether: no row exists until the link is used.
- **D3 — New tables.**
  - `password_credentials`: `user_id` (PK, FK cascade), `password_hash`,
    `updated_at`. The identity is `user_identities` with provider `email` and
    subject the normalised address.
  - `email_links`: `id` (uuid), `address`, `purpose` (`create` or `reset`),
    `language`, `created_at`, `expires_at`, `status` (`pending`, `sending`,
    `sent`, `skipped`, `failed`), `claimed_at`, `attempts`, `consumed_at`.
    Not tied to `users`: it can exist before an account does.
  - `auth_throttle`: `key_hash` (PK), `window_started_at`, `count`.
- **D4 — Normalising an address:** strip, then lowercase; a regex accepts
  exactly one `@`, no whitespace or control characters, at most 254 characters.
  Rules out provider-specific rules such as Gmail's dots.
- **D5 — `POST /api/auth/email/start`** `{email, language}` always answers 202
  with no body once the shape is valid and the throttle allows it, whether or
  not the address has an account. It inserts one `email_links` row, nothing
  else, so answers take the same time. `purpose` is `reset` if the identity
  exists, otherwise `create`. 503 when email is not configured. Rules out
  sending in the request: `mailer.send` can block about 25 s, and the time of
  an answer would reveal who has an account.
- **D6 — The worker sends the links.** A new step in `notifications/worker.py`
  claims pending rows with `SKIP LOCKED`, applies the non-production
  allowlist (a refused address becomes `skipped`), and sends with the existing
  mailer. Retries follow the digests' rule for a temporary failure. Links
  past `expires_at` are not sent. The sweep deletes rows a day after they
  expire. The email goes out within about 15 s.
- **D7 — The link token** is `<row id>.<HMAC-SHA256(NOTIFICATION_SECRET,
  "email-link:" + row id)>`, base64url. The worker can build it from the row,
  nothing secret is stored, a copy of the database forges nothing, and VAL's
  seeded rows do not work with VAL's different secret. The prefix keeps it
  apart from the unsubscribe tokens that use the same secret. Rules out a raw
  token, which the worker would need stored, or a new variable for the owner.
- **D8 — Links live 1 hour and are used once.** The link is
  `<PUBLIC_BASE_URL>/create-account#<token>` or `/reset-password#<token>`: in the
  fragment, so it reaches neither Caddy's logs nor a `Referer`, as share links
  do. The client takes it out of the address bar at once.
- **D9 — `POST /api/auth/email/complete`** `{token, password, display_name?}`
  consumes the row in one statement (`UPDATE … WHERE id AND consumed_at IS NULL
  AND expires_at > now RETURNING`). A bad, used or expired token is 410 with a
  fixed body. Then, looking at the identity **now**, not at `purpose`:
  - none: creates the user, the identity and the credential, with the savepoint
    of `_user_for` for two concurrent first uses. `display_name` is required
    for `create` links and defaults to the part before the `@` otherwise.
  - exists: replaces the password, **deletes every session of the account**,
    and marks the address's other links consumed.
  Answers `SignedIn`. The holder of the link has proven the mailbox, so a stale
  `purpose` needs no refusal.
- **D10 — `POST /api/auth/email/sign-in`** `{email, password}`: `SignedIn`, or
  401 with one fixed body for every failure. An unknown address verifies
  against a dummy hash, so it costs the same time.
- **D11 — Passwords.** Argon2id through `argon2-cffi`, 19 MiB, 2 passes, 1 lane
  (OWASP's minimum), with a rehash at sign-in when the parameters change. At
  most 4 hashes run at once (a semaphore), as the VPS is shared: 40 API threads
  at the library's 64 MiB would take 2.5 GB. Length 10 to 128 characters, no
  composition rules, following NIST SP 800-63B. Checked on the server.
- **D12 — Throttling, in PostgreSQL**, since two app processes can run at
  once. Fixed windows on the SHA-256 of `kind|value`, so that no address or IP
  is stored: sign-in 10 per 15 min per address and IP together, 100 per 15 min
  per IP; start 3 per hour per address, 20 per hour per IP; complete 20 per 15
  min per IP. Counted **before** the work, in a **separate committed
  transaction** from `app.state.session_factory`, since a refused request rolls
  the request's own transaction back. Over a limit: 429 `too_many_attempts`.
  On start, an address over its limit still answers 202 and adds no row, so
  the limit does not reveal or spam anything. An address alone is never
  limited at sign-in, so an attacker cannot lock someone out. The worker sweeps
  old rows.
- **D13 — `display_name` is now typed by anyone**, unlike Google's. Trimmed,
  1 to 100 characters, no control characters, refused otherwise (422). It
  reaches other users' screens and emails, so each email template must escape
  it (tested), and it can never reach a header.
- **D14 — Apple verifier, `accounts/apple.py`**, shaped like `google.py`:
  `app.state.apple_verifier`, None when `APPLE_CLIENT_IDS` is empty, a fake in
  tests. PyJWT with `PyJWKClient` on `https://appleid.apple.com/auth/keys`,
  keys cached, 5 s timeout. RS256 only; `iss`, `aud` among the IDs, `exp`,
  `iat` and `sub` required; 10 s leeway. Fixed failure labels, never token text.
  Apple unreachable is 502, anything else 401.
- **D15 — `POST /api/auth/apple`** `{id_token, nonce, name?}`. The client sends
  Apple the SHA-256 of a random nonce and the server compares, so a token alone
  cannot be replayed. An address, when present, must be verified. It is not
  sent the same way every time and Apple's name comes **only at the first
  authorisation**, from the client (D13's rules apply). So: the address is
  refreshed when present and required to create an account; the name is never
  refreshed. Without a name: the part before the `@`, or "Apple user" for a
  relay address (`@privaterelay.appleid.com`). Relay addresses are stored
  and mailed as any other, once the sender is registered (U6).
- **D16 — Apple by platform.** One package, `sign_in_with_apple`. Web: Apple's
  JS in popup mode, so the page and a pending join survive. Android: a custom
  tab. Apple POSTs to `POST /api/auth/apple/callback`, which answers 303 to
  `intent://callback?<the form, re-encoded>#Intent;package=<APPLE_ANDROID_PACKAGE>;scheme=signinwithapple;end`
  and changes nothing on the server: the token is verified only by D15. iOS
  needs no server change: its bundle ID joins `APPLE_CLIENT_IDS`. The iOS app
  is out of this plan.
- **D17 — What Apple gets and keeps.** The server stores only `sub` and the
  address. It holds no Apple key or refresh token, so `APPLE_CLIENT_IDS` is all
  the configuration there is. Revoking at account deletion needs Apple's key
  and belongs to the iOS release (Open decisions): Apple issues a fresh code at
  each sign-in, so nothing is lost by waiting.
- **D18 — `GET /api/config`** adds `apple_client_id` (the first of the IDs, or
  null), `apple_redirect_uri` (`<PUBLIC_BASE_URL>/api/auth/apple/callback`, or
  null), and `email_sign_in` (bool: mailer set and `NOTIFICATION_SECRET`
  present). The sign-in screen offers what is configured, and says "not
  configured" only when nothing is.
- **D19 — The email link and a pending share link.** The mail may open another
  tab, which cannot see `sessionStorage`. On `start`, the client copies a pending
  join token to `localStorage` with a 1-hour expiry, and reads it back once
  `complete` signs in. Rules out putting the join token in the email. On
  another device, the person lands on their home and reopens the invitation.
- **D20 — The email link is web only for now.** No Android app link is added.
  An Android user who follows it sets a password in the browser, then signs in
  with it in the app. The email says so in one line.
- **D21 — Email wording about other accounts.** Both emails and the sign-in form
  say "If you usually sign in with Google or Apple, use that button": D1 makes
  a second account otherwise, and nothing else would tell them.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **Three new unauthenticated routes that take a credential or send mail**:
  `/api/auth/email/start`, `/complete`, `/sign-in`. Learning whether an
  address has an account, from the body, status, or time of any answer, is F1.
  Any way to enter an account without the mailbox or the password is F1.
- **A new unauthenticated route with an external caller:**
  `POST /api/auth/apple/callback`. It must change no state and redirect only to
  the configured package's intent.
- **A new external service: Apple.** Outbound HTTPS for its public keys, with
  no secret. Its answers can be late, wrong, missing or hostile (E2).
- **Mail to any address someone types.** Using the server to send repeated
  mail to a third party, within the D12 limits, is in the envelope.
- **Display names and addresses are now hostile input** reaching other users'
  screens and emails.
- **Concurrency.** Two first uses of two links for one address, two uses of one
  link, a link used during an account deletion, two app processes in the
  worker's step. Exactly one of two uses of a link succeeds.
- **Resource use.** A flood of sign-ins must not exhaust the VPS's memory,
  which TraxJourney shares (D11, D12).
- **The surprise floor is unchanged.** Nothing here reads lists, gifts or
  occasions, and no new answer may depend on them.
- **Out of the envelope:** a compromised mailbox, Apple Developer account
  set-up, breached-password lists, multi-factor sign-in, and attackers with
  many IPs beyond D12's address limits.

## Boundaries crossed

- **Schema (F4):** one migration after `d8a3f6b2c914`, adding the three tables
  of D3 only. The previous release ignores them, so rollback stays image-only.
  Downgrade drops them: email accounts could then no longer sign in, and
  their other rows stay.
- **API contract (F4):** new routes D5, D9, D10, D15, D16. `GET /api/config`
  gains fields. No existing body changes. Old clients ignore the new fields
  (E5).
- **Stored data:** password hashes, and for up to about a day an address with
  a pending link. All deleted with the account or by the sweep.
- **Apple's `sub` is a contract with the past:** it is per Apple team, so the
  Services ID must stay in the same Apple Developer team, or Apple accounts
  would be seen as new (`docs/DEPLOYMENT.md`, U6).
- **Client:** new routes `/create-account`, `/reset-password`, `/email-sign-up`,
  all public. A new script from `appleid.cdn-apple.com` on the sign-in page.
- **Environment:** `APPLE_CLIENT_IDS`, `APPLE_ANDROID_PACKAGE`, both optional,
  with Apple sign-in simply absent without them.

## Conventions

- An answer to the three email routes is decided without revealing whether the
  address exists. A test asserts identical status and body for both cases.
- No password, token, address, name or provider message in any log or
  exception: only ids and fixed labels.
- `import jwt` only in `accounts/apple.py`, `import argon2` only in
  `accounts/passwords.py`.
- Tests never reach Apple or Brevo: fakes in `app.state`.
- A clock from `app.state.clock` everywhere; never `datetime.now` in new code.
- Every string in both ARB files, sentence case, no emoji; goldens light and
  dark through `.\goldens.ps1` only.
- U1, U2 and U3 touch authentication and get a unit review before integration
  (DELIVERY §5, point 3).
- Commits a user would notice carry a `Release-Note:` trailer in English.

## Open decisions

None blocks delivery: without its configuration each way of signing in is
simply not offered.

| Decision | Affects | Needed by |
|---|---|---|
| Apple Developer account and the Services ID (owner) | `APPLE_CLIENT_IDS`; the Apple button appears only once set | Before trying Apple on VAL |
| Turning email on (Brevo, already in the runbook) | `email_sign_in`; the form appears only once set | Before trying email on VAL |
| Linking several ways of signing in to one account, from a signed-in session | Accounts | Revisit on user feedback |
| Revoking Apple's token at account deletion (store requirement) | Apple key variables | The iOS release plan |
| Android app links for the email link (D20) | Client, a `.well-known` file | The mobile release plan |
| Changing a password while signed in, multi-factor sign-in, breached-password checks | Accounts | Revisit on user feedback |

## Execution units

### Wave 1

#### U1 — Server: schema, settings, identities, throttle, passwords

- **Goal:** The tables, settings, and shared pieces the routes need exist, with
  empty routers wired in.
- **Scope:** `server/app/accounts/models.py`, `identities.py`, `passwords.py`,
  `throttle.py`, `email_links.py`, `email_router.py`, `apple_router.py` (the last
  five new), `server/app/accounts/router.py` (only moving `_user_for`),
  `server/app/settings.py`, `server/app/main.py`, `server/alembic/env.py`,
  `server/alembic/versions/**` (one new revision), `server/pyproject.toml`,
  `server/uv.lock`, `server/tests/accounts/**` (new files),
  `server/tests/test_migrations.py`, `server/tests/accounts/test_sign_in.py`.
- **Context:** this plan D1, D3, D4, D7, D11, D12, D18, Boundaries crossed.
  Example: `server/app/billing/models.py` and its migration `c4f7d2a81e65`;
  `notifications/unsubscribe.py` for signing.
- **Do:**
  1. Models and one migration for D3.
  2. Settings `apple_client_ids`, `apple_android_package`, with an
     `apple_audiences` property like `google_audiences`.
  3. `identities.user_for(db, provider, subject, email, name, refresh_name)`:
     `_user_for` moved and generalised, with `email=None` keeping the stored
     one. Google keeps its exact behaviour.
  4. `passwords.py`: D11. `hash`, `verify`, `needs_rehash`, and a dummy verify.
  5. `throttle.py`: D12, an atomic upsert in its own committed transaction.
  6. `email_links.py`: `normalise`, `make_token`, `read_token` (D4, D7).
  7. Empty routers included in `main.py`, `app.state.apple_verifier = None`,
     and D18's fields.
- **Acceptance:** new tests `test_passwords.py`, `test_throttle.py` (a limit
  holds across two concurrent callers, and survives a rollback of the caller's
  transaction), `test_email_links.py` (a token for another row, or with the
  unsubscribe prefix, is refused); `test_sign_in.py` passes unchanged except
  for D18's fields; migration up, down and `alembic check`; `ruff check`.
- **Out of scope:** any route's behaviour.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed; the migration needs anything
  beyond the three new tables.
- **Depends on:** none.

### Wave 2

#### U2 — Server: the email routes and the worker's step

- **Goal:** Anyone can create an account from a mailbox, reset a password, and
  sign in, without the server revealing who has an account.
- **Scope:** `server/app/accounts/email_router.py`, `server/app/accounts/schemas.py`,
  `server/app/accounts/router.py` (`delete_me` only),
  `server/app/notifications/worker.py`, `server/app/notifications/email_links.py`
  (new, the sending step), `server/app/notifications/email_content.py`,
  `server/tests/accounts/**` (new files), `server/tests/notifications/**` (new
  files), `server/tests/lists/test_surprise.py` (the public-route list).
- **Context:** this plan D2, D5, D6, D8–D13, D20, D21, envelope. Example:
  `notifications/digests.py` `send_due` and `_prepare`.
- **Do:**
  1. D5, D9, D10 in `email_router.py`, using U1's pieces.
  2. The worker step D6, with its allowlist check and sweep (also of
     `auth_throttle`).
  3. Two email templates in English and French, with D20's and D21's lines.
  4. `delete_me` also deletes the address's `email_links`.
- **Acceptance:** new `test_email_sign_in.py`: identical status and body for
  known and unknown addresses on start and sign-in; a link is single-use under
  two concurrent uses; two concurrent first uses for one address make one
  account; reset ends every session; a pending link does not create an account;
  an expired link is 410; limits give 429 and start stays 202; hostile names
  refused and escaped in the email HTML. New `test_email_link_worker.py`:
  the allowlist, retry, expiry, two workers send once; the existing
  `test_worker.py` passes. `ruff check`.
- **Out of scope:** client, Apple, changing a password while signed in.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed; the digests' retry rule cannot
  be reused.
- **Depends on:** U1.

#### U3 — Server: Apple

- **Goal:** A valid Apple token signs in or creates an account, on every
  platform.
- **Scope:** `server/app/accounts/apple.py` (new), `server/app/accounts/apple_router.py`,
  `server/tests/accounts/test_apple*.py` (new), `server/app/main.py` (the verifier
  line only). `schemas.py` is U2's, so the bodies stay in `apple_router.py`.
- **Context:** this plan D1, D14–D17. Example: `accounts/google.py` and
  `tests/accounts/test_sign_in.py`.
- **Do:** the verifier D14; routes D15 and D16.
- **Acceptance:** `test_apple.py`, with an RSA key made in the test and a fake
  key source: wrong issuer, audience, nonce, algorithm (including `none` and
  HS256 signed with the public key), expired, missing `sub`, unverified address
  are all 401 with one body; first sign-in with a name; a later one without a
  name or address keeps both; no address on a first sign-in is 401; a relay
  address gets "Apple user"; hostile names refused; keys unreachable is 502.
  `test_apple_callback.py`: 303 to the configured package only, a hostile
  field cannot break out of the intent URL, nothing written. `ruff check`.
- **Out of scope:** client; token revocation.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1.

### Wave 3

#### U4 — Client: email sign-in

- **Goal:** People can create an account, reset a password and sign in with an
  email address.
- **Scope:** `client/lib/src/auth/**`, `client/lib/src/api/config.dart`,
  `client/lib/src/app_router.dart`, `client/lib/src/shared/pending_join.dart`,
  `client/lib/main.dart`, `client/lib/l10n/*.arb`, `client/test/**`.
- **Context:** this plan D2, D8, D18, D19, D21. Example: the `/join` token capture
  in `main.dart` and `lib/src/unsubscribe/`.
- **Do:**
  1. Read D18's fields. The form appears when `email_sign_in` is true.
  2. Sign-in form with email and password, "Forgot your password?", and "Create
     an account with your email", both to `/email-sign-up`.
  3. `/email-sign-up` (the address, then "check your inbox").
  4. `/create-account` and `/reset-password`: the token from the fragment,
     then the form, and on success the session.
  5. D19. `SignInFailure.tooManyAttempts` for 429; 410 explains the link
     has expired and offers a new one.
  6. Goldens for the screens.
- **Acceptance:** new widget tests for each screen and failure; `app_router_test`
  covers the public routes; `pending_join` test for D19; `flutter analyze`,
  `flutter test -j 2`, `.\goldens.ps1 -Check`.
- **Out of scope:** the Apple button, the account screen.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U2.

#### U6 — Docs and deployment

- **Goal:** The owner can turn both on from the runbook.
- **Scope:** `docs/DEPLOYMENT.md`, `docs/DEVELOPMENT.md`, `deploy/prod/.env.example`,
  `deploy/val/.env.example`, `.env.example`.
- **Context:** this plan D16, D17, Boundaries crossed. Example: the runbook's
  "Google sign-in" section and "Billing with Stripe".
- **Do:** An "Apple sign-in" section: Apple Developer enrolment, App ID, one
  Services ID with both hosts and `<host>/api/auth/apple/callback` as return
  URLs, the private relay registration of the sender domain, the variables,
  and a warning to keep the same team. Release-specific lines. A note that email
  sign-in follows the email turn-on steps and needs nothing more.
- **Acceptance:** `git grep` finds no host, id or address of the owner's; the
  `.env.example` files name both variables; deploy-smoke passes.
- **Out of scope:** Google Cloud Console (a later request).
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

### Wave 4

#### U5 — Client: the Apple button

- **Goal:** Apple sign-in works on the web and Android.
- **Scope:** `client/lib/src/auth/**`, `client/pubspec.yaml`, `client/pubspec.lock`,
  `client/web/index.html`, `client/android/app/src/main/AndroidManifest.xml`,
  `client/lib/l10n/*.arb`, `client/test/**`.
- **Context:** this plan D15, D16, D18. Example: the platform split in
  `sign_in_screen.dart` and `google_sign_in_init.dart`.
- **Do:** The button per Apple's guidelines, shown when `apple_client_id` is
  set. The random nonce, its hash to Apple, the raw one to the server. The name
  from the first authorisation. Cancelling is not a failure. Android's callback
  activity in the manifest. Goldens.
- **Acceptance:** widget tests through a fake of the package's call: success,
  cancel, refused, not offered without config; `flutter analyze`,
  `flutter test -j 2`, `.\goldens.ps1 -Check`, web build.
- **Out of scope:** the iOS project.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed; the package cannot do popup
  mode or a nonce on the web.
- **Depends on:** U3, U4.

## Definition of done

- With no new variables, VAL and PROD behave as today, apart from the email form
  appearing where email is already turned on.
- A person can create an account from a mailbox, sign in with the password,
  and reset it, on the web and Android.
- With `APPLE_CLIENT_IDS` set, Apple sign-in works on the web and Android.
- No route reveals whether an address has an account.
- A used, expired or forged link does nothing.
- Deleting an email or Apple account removes it and its credentials.
- All checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
- The runbook has the Apple Developer steps.
