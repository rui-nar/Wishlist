# Premium through Apple's in-app purchase — Plan

## Problem

On 2026-11-11 the owner decided that Premium can be bought on iPhone, through
Apple's in-app purchase, from the first iOS release (`docs/NEEDS.md`,
Constraints). Apple requires its own purchase for a digital subscription sold
inside an iOS app. `PREMIUM_PLAN.md` D3 left a seam for exactly this: a
translator and a route per store, with no change to entitlements, limits or
the status route.

## Current state

- `server/app/billing/entitlements.py`: `apply(db, facts, read_at)` records any
  source. `is_premium` and `summary` read every source. `entitlements.source`
  already allows `apple`.
- `server/app/billing/stripe_gateway.py` and `stripe_events.py` are the
  Stripe translator. The webhook trusts an event only as a pointer and
  re-reads the subscription (premium plan D13).
- `closing.stop_billing` cancels Stripe subscriptions before an account is
  deleted, and ignores other sources.
- The client offers a purchase on the web only (D18). The plan screen shows
  the Stripe portal's Manage button on `can_manage`.
- `IOS_APP_PLAN.md` builds the iOS app. This plan needs its project (U1) and
  its bundle id (an Open decision there).

## Decisions

- **D1 — The product.** One auto-renewable subscription, yearly, in one
  subscription group. The owner creates it in App Store Connect. Its id is
  `APPLE_PRODUCT_ID`. The price is set in App Store Connect per storefront,
  and the app shows StoreKit's localised price, never `BILLING_PRICE_AMOUNT`.
  No introductory offer, no Family Sharing.
- **D2 — Linking a purchase to an account:** StoreKit 2's `appAccountToken`,
  set to the account's id, which is a uuid as Apple requires. The server
  refuses a transaction whose token is not the signed-in account (409
  `other_account`). Rules out matching by Apple ID, which the server never
  sees.
- **D3 — The client reports, the server checks with Apple.** After a purchase
  or a restore, the client posts the signed transaction (JWS) to `POST
  /api/billing/apple/transactions`. The server:
  - verifies the JWS chain against Apple's root certificate with Apple's
    `app-store-server-library`;
  - checks the bundle id, the product id, the environment and the token;
  - reads the authoritative state from the **App Store Server API** (all
    subscription statuses for that `originalTransactionId`);
  - records one entitlement: `source = apple`, `external_id` the
    `originalTransactionId`, `period_end` the `expiresDate`, `started_at` the
    `originalPurchaseDate`, and `cancel_at_period_end` when auto-renew is off.

  The API needs an In-App Purchase key: `APPLE_IAP_ISSUER_ID`,
  `APPLE_IAP_KEY_ID` and `APPLE_IAP_PRIVATE_KEY` (secret). Rules out trusting
  the client's JWS alone, which can be replayed and is a snapshot.
- **D4 — App Store Server Notifications V2** at `POST
  /api/billing/apple/notifications`, unauthenticated, as Stripe's webhook is.
  The signed payload is verified, then trusted only as a pointer. The handler
  re-reads that `originalTransactionId` from the API and applies it, so order
  and repeats do not matter (as premium plan D13). The account is the latest
  transaction's `appAccountToken` when it names an existing account. Only
  when the transaction carries no token is it the account the stored
  entitlement names (review R1-2). A resubscription made under another account
  then moves to that account and stays there. When neither gives an account,
  the notification is logged and answered 200.
- **D5 — Status mapping.** Premium lasts through Apple's **billing grace
  period** and no longer (owner, 2026-11-11). The runbook turns the grace
  period on in App Store Connect (16 days).

  | Apple's state | Entitlement status | `period_end` |
  |---|---|---|
  | Active | `active` | `expiresDate` |
  | Billing grace period | `past_due` | `gracePeriodExpiresDate` (review R1-5) |
  | Billing retry past the grace period | `ended` (grants nothing) | `expiresDate` |
  | Expired, or revoked (refund, Family Sharing loss) | `ended` | `expiresDate` |

  A refund ends Premium at once. A retry that later succeeds comes back as
  `active` through its notification. `warn_if_lapsed` is quiet for these rows,
  since the grace period's date is the real end.
- **D6 — Environments** (owner, 2026-11-11; review R1-1).
  - VAL is the VAL app (IOS_APP_PLAN D1). It accepts Sandbox transactions
    only. Testers buy there, for free.
  - PROD accepts Production transactions, and Sandbox ones **only from the
    accounts listed in `APPLE_SANDBOX_ACCOUNT_IDS`**: the demo account given
    to Apple's review, which buys with Sandbox against the production server.
    Any other Sandbox transaction on PROD is refused (409 `sandbox_refused`)
    and logged with its id.
  - Rules out accepting every Sandbox transaction on PROD, which would give
    testers Premium for free, and refusing them all, which fails App Review.
- **D7 — Selling on iOS** needs `APPLE_PRODUCT_ID`, the three IAP key
  variables and `APPLE_BUNDLE_ID`, separately from Stripe's selling state.
  - `GET /api/billing` gains a separate nullable `apple_offer`
    (`{"product_id": …}`) when this is on (review R1-4). The existing `offer`
    keeps its shape and stays Stripe's, so shipped clients parse it as
    before. The iOS app offers the purchase from `apple_offer`; the web and
    Android from `offer`.
  - **Limits apply only while Stripe sells** (owner, 2026-11-11):
    `limits_enforced` is unchanged. Apple selling alone never blocks a web
    or Android owner who has no way to pay.
- **D8 — What the iOS plan screen shows**, as Apple's guideline 3.1.2
  requires: the subscription's name and length, the localised price, that it
  renews automatically until cancelled in Apple's settings, and links to the
  terms (`LEGAL_TERMS_URL`, or Apple's standard licence when empty) and the
  privacy policy. Also:
  - **Restore purchases**, which Apple requires.
  - **Manage** opens Apple's subscriptions page for the `apple` source, and
    Stripe's portal for `stripe`.
  - **No purchase while Premium is already in force** from any source, so
    nobody pays twice. The web refuses checkout for the same reason today.
- **D9 — Account deletion with an Apple subscription.** Apple offers no way
  for the server to cancel one, and Apple's guideline 5.1.1(v) forbids
  refusing the deletion, so the deletion goes ahead with a warning (owner,
  2026-11-11: a charge after a deletion the person was warned about is
  accepted). The warning needs its own signal (review R1-3), not `source`.
  - `GET /api/billing` gains `apple_renewing` (bool). It is true while any
    `apple` row of the account is set to renew (auto-renew on, not ended),
    whatever `summary` picks.
  - The deletion dialog on every platform shows the warning, with a link to
    Apple's subscriptions page.
  - The admin panel shows the Apple subscription in its own block, like
    Stripe's (status, start, renewal or end), and its deletion dialog warns
    the admin.
  - The server logs, with ids only, a deletion that proceeds past a renewing
    Apple subscription.
- **D10 — No consent record for Apple purchases.** Apple is the seller, and
  withdrawal and refunds go through Apple. The Stripe consent fields stay
  empty for `apple` rows.

## Review envelope

REVIEW.md defaults apply, with PREMIUM_PLAN's envelope, and these additions:

- **A new external service: the App Store Server API**, with a private key.
  Its answers can be late, wrong, missing or hostile (E2). A key or a signed
  payload in a log is F1.
- **Two new routes.**
  - `POST /api/billing/apple/notifications` is unauthenticated: a payload
    without a valid Apple signature changing any state is F1.
  - `POST /api/billing/apple/transactions` is signed in. A transaction that
    grants Premium to an account other than its `appAccountToken`, or a
    Sandbox transaction honoured on VAL's opposite, is F1.
- **Money:** a paying customer left without Premium, silently, is F3. An
  Apple subscription that goes on charging after a deletion the person (or
  the admin) was warned about is accepted. One deleted with no warning is F3.
- **Concurrency:** a notification and a client report for one transaction at
  once, and two reports, are in.
- **The surprise floor:** nothing here may depend on invitee activity.
- **Out of the envelope:** App Store Connect set-up, Apple's review, pricing,
  offer codes.

## Boundaries crossed

- **Schema:** none. `entitlements` already allows `apple`.
- **API:** the two new routes. `GET /api/billing` gains `apple_offer` and
  `apple_renewing`; `offer` keeps its shape. `source` may be `apple`. The
  admin row gains `apple_subscription`. Old clients see Premium.
- **Stored data:** Apple entitlements, deleted with the account.
- **Environment:** `APPLE_PRODUCT_ID`, `APPLE_BUNDLE_ID`,
  `APPLE_IAP_ISSUER_ID`, `APPLE_IAP_KEY_ID`, `APPLE_IAP_PRIVATE_KEY` and
  `APPLE_SANDBOX_ACCOUNT_IDS`.
- **A contract with the past:** `appAccountToken` = account id, and
  `originalTransactionId` as `external_id`, must stay readable by later
  releases.

## Conventions

- Apple's library is imported in `billing/apple_gateway.py` only, as Stripe's
  is in `stripe_gateway.py`. Tests use a fake gateway and never reach Apple.
- No key, JWS or Apple ID in any log; only transaction ids and fixed words.
- Both new routes in the role and surprise matrices.
- U1 gets a unit review (DELIVERY §5, point 3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| The price per storefront, and the App Store's Paid Apps agreement, tax and banking (owner) | D1 | Before selling |
| Google Play purchases on Android | A third translator | The Android store release |
| Introductory offers, offer codes | D1 | Revisit after the first sales |

## Execution units

### Wave 1

#### U1 — Server: the Apple translator and its routes

- **Goal:** A purchase made on iPhone grants Premium, stays in step through
  Apple's notifications, and ends when Apple says so.
- **Scope:** `server/app/billing/apple_gateway.py`, `server/app/billing/apple_events.py`
  (new), `server/app/billing/router.py`, `server/app/billing/schemas.py`,
  `server/app/settings.py`, `server/app/admin/schemas.py` and `queries.py`
  (the Apple subscription on the admin row), `server/app/accounts/deletion.py`
  (the log line of D9), `server/app/main.py` (the gateway's construction
  and the start-up log), `server/pyproject.toml`, `server/uv.lock`,
  `server/tests/billing/**`, `server/tests/lists/test_roles.py` and
  `test_surprise.py` (rows and calls), the three `.env.example` files.
- **Context:** D2–D7, D10, the envelope. Example: `stripe_gateway.py`,
  `stripe_events.py` and the webhook in `billing/router.py`.
- **Do:** as the decisions say. Apple's test certificates and signed fixtures
  are built in the tests, not downloaded.
- **Acceptance:** tests for each status of D5; the token check; environments
  (D6); a forged or tampered payload refused with nothing written; a
  notification and a report racing; repeats; an unknown transaction; the
  selling state; `ruff check`; the role and surprise matrices.
- **Out of scope:** the client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed; the library cannot verify
  offline in tests.
- **Depends on:** none.

### Wave 2

#### U2 — Client: buying on iPhone

- **Goal:** An iPhone user can buy, restore and manage Premium.
- **Scope:** `client/lib/src/billing/**`, `client/lib/src/admin/**` (the Apple
  block and the admin deletion warning), `client/lib/src/auth/account_screen.dart`
  (its plan section, legal links and deletion dialog, review R1-8),
  `client/pubspec.yaml`, `client/pubspec.lock`,
  `client/lib/l10n/*.arb`, `client/test/**`.
- **Context:** D1, D2, D7–D9. Example: `plan_screen.dart`'s web purchase.
- **Do:** `in_app_purchase` with StoreKit 2; the purchase with the token;
  posting each transaction; finishing transactions only after the server
  accepted them; restore; the disclosures; Manage; the deletion line.
- **Acceptance:** widget tests through a fake store: buy, cancel, pending,
  refused by the server, restore, already Premium, not offered; goldens;
  `flutter analyze`, `flutter test -j 2`.
- **Out of scope:** Android purchases.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1, and IOS_APP_PLAN U1.

#### U3 — Runbook

- **Goal:** The owner can set up selling on iPhone, Sandbox on VAL first.
- **Scope:** `docs/DEPLOYMENT.md`, `docs/BILLING.md`.
- **Context:** D1, D3, D4, D6, D7. Example: `docs/BILLING.md`.
- **Do:**
  - The Paid Apps agreement, tax and banking.
  - The subscription group and product.
  - The In-App Purchase key.
  - The notification URLs for Sandbox (VAL) and Production (PROD).
  - Sandbox testers.
  - The variables.
  - A test purchase, renewal, cancellation and refund on VAL.
- **Acceptance:** no real identifier committed.
- **Out of scope:** code.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1.

## Definition of done

- On VAL, a Sandbox purchase on iPhone grants Premium within seconds, and
  renewal, cancellation, billing retry and refund move it as D5 says.
- Premium from either store works on every platform, and nobody can pay twice.
- No change to entitlements, limits or the status route beyond D7.
- The checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
