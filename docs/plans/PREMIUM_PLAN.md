# Premium: the free plan's limits and the yearly subscription

## Problem

Every account is unlimited and nothing can be bought. NEEDS, "Free and
premium", decides a free plan (1 list, at most 20 gifts per list)
and a yearly premium subscription, sold from the first release, with Stripe on
the web and the store purchases later, all feeding one premium status on the
server. None of it exists: there is no plan concept, no limit, no payment and
no legal page.

This plan delivers that section of `docs/NEEDS.md`:

- **Limits** on what an owner can grow: lists and gifts on a list. Only owners
  pay; being an invitee is always free. Nothing is deleted when premium ends.
- **One premium status** per person, with a source (`stripe`, `apple`,
  `google`), fed today by Stripe only.
- **Stripe on the web:** Checkout for the subscription, the Customer Portal to
  manage or cancel it, a signature-verified webhook. VAT through Stripe Tax,
  tax-inclusive prices, and the 14-day withdrawal acknowledgement at checkout,
  as TraxJourney's `docs/BILLING.md` describes.
- **Placeholders** for everything the owner has not decided (price, keys, legal
  texts), configured by environment. With nothing configured, no purchase is
  offered, no limit applies and nothing fails.
- **The surprise:** limits, errors, counts and status never depend on invitee
  activity.

The owner's standing instruction of 2026-11-10 is to proceed silently and put
configurable placeholders where the owner's decisions are needed. This push
reaches VAL only. No real charge can happen without the owner adding live keys
on PROD.

Apple and Google purchase validation is out of scope until the mobile apps
exist: the seam is designed (D3), no validator is built.

## Current state

- **Counting:** `server/app/lists/visibility.py` `counted(list_id)` is the one
  count of "gifts on the list": `on_list`, so hidden and revealed gifts (no
  `list_id`) and received gifts are outside it. `ListSummary.gift_count` uses
  it (`server/app/lists/router.py` `my_lists`). HIDDEN_GIFTS_PLAN D12 leaves
  "whether keep is refused over the free limit" to this plan.
- **What makes a list longer:** `create_list` (a new list), `add_gift`,
  `put_back` (`DELETE /api/gifts/{id}/received`, through
  `hidden_gifts/lifecycle.py` `set_received`), and `keep_gift`
  (`POST /api/gifts/{id}/keep`, through `keep_revealed`, a new row under a new
  id). Nothing else raises `counted`: givers' hidden gifts carry `for_list_id`.
- **Owners:** `list_owners` (list, user). No endpoint adds a co-owner and no
  endpoint hands a list over yet; `test_surprise.py` inserts Cora's row
  directly.
- **Who locks what:** every request holds its user `FOR KEY SHARE`
  (`accounts/deps.py`); givers take the occasion `FOR SHARE` and the gift
  `FOR KEY SHARE` (`lists/access.py`). A hidden gift's insert takes `lists`
  `FOR KEY SHARE` through its foreign key. `digests.py` `_lock_key` is the
  precedent for a transaction advisory lock on a hashed text key.
- **Slow work outside locks:** `accounts/deps.py` `unlocked_session` and
  `lock_signed_in`, used by image upload ("does slow work before it writes").
- **Account deletion:** `accounts/router.py` `delete_me`, on `UserToDelete`
  (user `FOR UPDATE` from the dependency).
- **An external service, the model to follow:** Brevo
  (`notifications/mailer.py`, `Settings.missing_email_settings`,
  `app.state.mailer`, a fake in `tests/conftest.py` `make_client`, a start-up
  log naming the missing variables). **An unauthenticated route:**
  `POST /api/unsubscribe/{token}` in `notifications/router.py`.
- **Refusals with a code:** returned as `JSONResponse`, not raised
  (`hidden_gifts/router.py` `_refusal`, `lists/router.py` `_not_revealed`),
  declared with `responses=`.
- **Matrices:** `server/tests/lists/test_roles.py` (`GUARDED_PREFIXES`,
  `ENDPOINTS`, `COVERED_ELSEWHERE`, `test_every_route_is_in_the_matrix`) and
  `test_surprise.py` (`test_every_route_is_called`, over the whole OpenAPI
  document; world against control; twins). `test_owner_work.py` compares the
  owner's statements with and without activity.
- **VAL is seeded from PROD** (`deploy/val/seed-from-prod.sh`), so VAL holds
  PROD's rows and real addresses.
- **Client:** `ApiException(statusCode, body)` (`api/api_client.dart`);
  `HiddenGiftRefused` and `NotRevealed` turn coded refusals into typed
  exceptions; `account_screen.dart`, `gift_form_screen.dart` `_save`,
  `list_form_screen.dart` `_save`, `list_detail_screen.dart` `_act`;
  `app_router.dart` `_publicPaths`; `unsubscribe_screen.dart`, a public page;
  `url_launcher` with a test fake (`installFakeUrlLauncher`).
- **Alembic head:** `c4f7d2a81e65` (notifications).

## Decisions

### The premium status

- **D1 — One entitlement table, one row per purchase.** New table
  `entitlements`: `id` (UUID), `user_id` (FK `users` `ON DELETE CASCADE`,
  indexed), `source` (`stripe` | `apple` | `google`, check constraint),
  `external_id` (`varchar(255)`: the Stripe subscription id, later Apple's
  original transaction id or Google's purchase token), `status` (`active` |
  `past_due` | `incomplete` | `ended`, check constraint), `period_end`
  (timestamptz, null), `cancel_at_period_end` (bool), `started_at` (null),
  `read_at` (timestamptz, not null: D13's guard), `terms_accepted_at` and
  `terms_version` (null: the consent proof, D12), `created_at`, `updated_at`;
  unique (`source`, `external_id`). Rules out a `plan` column on `users` (one
  purchase source, and nothing to tell a Stripe renewal from a store renewal)
  and a Stripe-shaped table (the stores would need a second one and a second
  reading of premium). New table `billing_customers`: `user_id` (FK `users`
  `ON DELETE CASCADE`), `source`, `customer_id` (`varchar(255)`); primary key
  (`user_id`, `source`), unique (`source`, `customer_id`): the Stripe customer
  exists before any subscription (D12).
- **D2 — Premium is computed, never stored.** A person is premium when one of
  their rows has `status` in (`active`, `past_due`) and `period_end + 3 days >
  now`, evaluated at each read by the server's clock, as a claim's expiry is
  (RESERVING D8). Nothing runs when premium ends, so nothing can delete or
  change anything. `past_due` keeps premium while Stripe retries a card
  (BILLING.md, Grace); the 3 days absorb a late renewal webhook and make a row
  whose provider went silent end by itself. A fixed constant, not a setting:
  it is a tolerance, not a commercial term. Rules out a daily job flipping a
  flag (a missed run gives away or takes away premium) and trusting `status`
  alone (a lost `deleted` event would grant premium forever).
- **D3 — The seam for the stores.** `app/billing/entitlements.py` knows no
  provider: `apply(db, facts, read_at)` takes an `EntitlementFacts` dataclass
  (`source`, `external_id`, `user_id`, `status`, `period_end`,
  `cancel_at_period_end`, `started_at`), and `is_premium`, `summary` read rows
  of any source. Stripe is one translator, `billing/stripe_events.py`. An
  Apple or Google validator later adds a translator and a route, and touches
  neither the table, the limits nor the status route. No validator, route or
  client purchase is built for them now.

### The limits

- **D4 — What is limited, and the answer.** Free: `FREE_MAX_LISTS` (default 1)
  lists, `FREE_MAX_GIFTS_PER_LIST` (default 20) gifts per list, counted by
  `visibility.counted`; both are read per request from the settings. A request
  is refused only if it would make something grow past the limit. The four
  growing paths are checked, and no other:

  | Path | Refused when |
  |---|---|
  | `POST /api/lists` | the user's counted lists (D5) are at the limit |
  | `POST /api/lists/{id}/gifts` | the list is at the limit (not premium, D5) |
  | `DELETE /api/gifts/{id}/received` | the gift is on the list, really received, and the list is at the limit (D6) |
  | `POST /api/gifts/{id}/keep` | the gift is revealed and the list is at the limit (D6) |

  The refusal is **402** with `{"detail": "…", "code": "plan_limit",
  "resource": "lists" | "gifts", "limit": n}`, returned, never raised, and
  declared with `responses=`. No `used` figure: the client has no use for it.
  Every other route of an over-limit list works: reading, sharing, editing,
  occasions, images, marking received, deleting (NEEDS: readable, shareable
  and editable, cannot grow). Rules out 403 and 409 (402 lets a client tell
  "this needs paying" from any other refusal, as in TraxJourney).
- **D5 — Co-owned lists: any owner's premium covers the list.** A list has no
  gift limit when at least one of its current owners is premium, whoever is
  acting. A free user's list count is the lists they own that no premium owner
  covers. So one person paying covers a shared list, and two co-owners never
  get different answers on the same list, which would be arbitrary. Rules out
  the acting user's premium (a couple's list would refuse one of them), the
  creator's (no such column, and a creator can leave), and requiring every
  owner to pay. Accepted: a free co-owner can infer that the other owner is
  premium; that is not invitee activity.
- **D6 — Keep and put back are growth, checked after the reveal.** A kept
  revealed gift becomes an ordinary gift that invitees see again, and putting
  a received gift back returns one to the list, so both are refused at the
  limit, with one rule for every path: a free list never grows past the limit.
  Without it, marking gifts received, adding others and putting them back
  walks past the limit. A refused gift loses nothing: it stays revealed, or
  received, with its id, and the owner can mark it received, dismiss it, free a
  place or go premium. The order is the surprise's: inside `keep_revealed` the
  limit is checked **after** the reveal is confirmed, so a gift on the list
  still answers 409 `not_revealed` and an unrevealed hidden gift still answers
  the random id's 404, at the limit as anywhere. A 402 is only ever given for a
  gift its owners already see as revealed, which reveals nothing the reveal
  has not. Put back checks only when the gift is on the list and still
  received once locked (a repeat is a no-op, never a 402); a revealed gift put
  back has no `list_id` and never counts. Rules out exempting keep (a second
  rule for one path, and a list past the limit with no premium).
- **D7 — The limits read nothing but owner data.** The inputs are
  `visibility.counted`, `list_owners` and `entitlements`. No limit, count,
  status or refusal reads claims, participants, comments, follows, hidden
  gifts or notifications; `billing/limits.py` imports none of their models,
  and a test fails if it does. The statements of the growing paths are
  compared with and without activity (`test_owner_work.py`), and the
  world-against-control runs repeat at the limit, with enforcement on (U9).
- **D8 — Concurrency: an advisory lock only owners' growth takes.** Two adds at
  19 must not make 21. Each growing path takes
  `pg_advisory_xact_lock(hashtextextended(key, 0))` before it counts, with key
  `plan_growth:gifts:<list id>` or `plan_growth:lists:<user id>`
  (`digests.py` `_lock_key`), and holds it to commit. No giver route takes it,
  so an owner's request can never wait on invitee activity, and locks taken
  by givers do not change what an owner's request waits for. It is taken
  right after the user's `FOR KEY SHARE`, before any other row lock
  (`keep_revealed`, `set_received`: before the occasion's), so it adds no
  cycle to the lock order of RESERVING D7. Rules out `FOR UPDATE` on the `lists` row (it conflicts with
  the `FOR KEY SHARE` a giver's hidden-gift insert takes through its foreign
  key: the very wait the surprise forbids) and on the `users` row (every
  request of that user holds `FOR KEY SHARE`), and a post-commit recount
  (compensating deletes).
- **D9 — Two switches, and safe defaults.**
  `Settings.billing_purchasable` is true when `missing_billing_settings` is
  empty (D16 lists it). `BILLING_ENFORCE_LIMITS` (default false) asks for
  limits, and they apply only when it is on **and** purchases are possible:
  `limits_enforced = billing_enforce_limits and billing_purchasable`. Nobody
  can ever be blocked from growing a list while there is no way to pay. With
  enforcement off, the growing paths take no lock and count nothing, exactly
  today's behaviour. Unset, `POST /api/billing/*` answer 404 and
  `GET /api/billing` says no offer. The owner turns enforcement on after
  looking at what existing accounts hold (the runbook gives the query):
  anyone already past the limit simply cannot grow. Rules out one switch
  (TraxJourney's two-step rollout, "enable the first one alone at first",
  exists for this) and enforcement without a purchase path.

### Stripe

- **D10 — The official SDK, behind one module.** `stripe>=16.0.0,<17` (major
  capped, as `psycopg` and SQLAlchemy are), imported lazily and only in
  `billing/stripe_gateway.py`, so an environment without keys never loads it
  (the app's memory limits are tight, DEPLOYMENT.md). `app.state.stripe_gateway`
  is a `StripeGateway`, or None when not purchasable; tests replace it with a
  fake in `make_client`, so no test reaches Stripe. One HTTP timeout of 15 s
  and 2 network retries (BILLING.md). Its methods return small dataclasses and
  raise `GatewayUnavailable` (retryable) or `MissingAtStripe`; no secret, email
  or response body is ever in an exception or a log line, only ids and fixed
  words. Rules out raw HTTP as for Brevo: Stripe's form encoding, idempotency
  keys, and signature scheme are what the SDK is for.
- **D11 — Routes.** All in `billing/router.py`.

  | Method and path | Auth | What | Answers |
  |---|---|---|---|
  | `GET /api/billing` | user | plan, limits, offer, legal links | 200 `BillingStatus` |
  | `POST /api/billing/checkout` | user, unlocked | a Checkout URL | 200 `{"url": …}`; 404 not purchasable; 409 `already_premium`; 502 `billing_unavailable`; 503 `billing_misconfigured` |
  | `POST /api/billing/portal` | user, unlocked | a Customer Portal URL | 200 `{"url": …}`; 404 not purchasable; 409 `no_subscription`; 502 `billing_unavailable` |
  | `POST /api/billing/webhook` | signature | Stripe's events | 204; 404 not purchasable; 400 invalid; 502 retry |

  `BillingStatus`: `plan` (`free` | `premium`), `source` (null or the row's),
  `status` (null | `active` | `past_due` | `canceling`), `renews_at`,
  `ends_at` (null or datetime), `limits` (`max_lists`, `max_gifts_per_list`:
  numbers, or null for premium), `enforced` (bool), `offer` (null, or
  `{"amount": "…", "currency": "EUR", "interval": "year"}`), `can_manage`
  (bool: a Stripe customer exists and purchases are possible), `legal`
  (`terms_url`, `privacy_url`, `withdrawal_url`, each null). With several rows
  in force, the latest `period_end` is shown. Every value is owner data (D7).
  Checkout and portal use `UnlockedSession` and `lock_signed_in`: no row lock
  is held across a call to Stripe. Bodies are empty: success and cancel URLs
  are built on `PUBLIC_BASE_URL`, never taken from the client.
- **D12 — Checkout.** In order:
  1. Already in force, any source: 409 `already_premium`.
  2. The price is read from Stripe and must be active, yearly, `amount` and
     `currency` equal to `BILLING_PRICE_AMOUNT` and `BILLING_PRICE_CURRENCY`,
     and `tax_behavior=inclusive`. Otherwise 503 `billing_misconfigured` with
     an ERROR log naming the variable. The app never advertises a price other
     than the one charged, and a tax-exclusive price cannot be sold by mistake.
     Amounts are in major units of a two-decimal currency.
  3. The customer: the stored `billing_customers` row, or one created with
     the Stripe idempotency key `wishlist-customer-<user id>`, with the user's
     email and name and `metadata.user_id`, stored (`ON CONFLICT DO NOTHING`)
     after `lock_signed_in`. Rules out `customer_email` (BILLING.md's way): a
     customer known before payment lets open sessions be expired, and lets
     Stripe's "limit customers to one subscription" setting work.
  4. The customer's open sessions are expired, then a session created:
     `mode=subscription`; the price, quantity 1; the customer;
     `client_reference_id` and `subscription_data.metadata.user_id`;
     `metadata.terms_version`; `locale` from the user's language;
     `consent_collection.terms_of_service=required`;
     `custom_text.terms_of_service_acceptance.message` (D17, by language);
     success and cancel URLs `<PUBLIC_BASE_URL>/account/plan?checkout=success`
     and `…=cancelled`. With `STRIPE_AUTOMATIC_TAX`, also
     `automatic_tax.enabled`, `billing_address_collection=required` and
     `customer_update` (`address` and `name`: `auto`).
     A refusal blaming the terms URL logs the ERROR of BILLING.md step 5 and
     answers 503.
  - Double payment left over (two tabs paying within the same moment): the
    owner enables Stripe's one-subscription setting, and the webhook logs an
    ERROR when a customer holds two subscriptions in force (Guard).
  - The consent proof: on `checkout.session.completed` with
    `consent.terms_of_service = accepted`, the row gets `terms_accepted_at`
    and `terms_version`. Stripe keeps each session's consent too.
- **D13 — The webhook re-reads the subscription; ordering takes care of
  itself.** Webhooks arrive late, twice and out of order, and `event.created`
  has one-second granularity, so a `created` (incomplete) and an `updated`
  (active) of the same second cannot be ordered: a timestamp guard would leave
  a paying customer free. So the event only says which subscription to look at:
  1. Purchasable, else 404. The body is read up to 1 MiB (over: 400), and
     `gateway.verify` checks the signature (`Webhook.construct_event`, 5
     minutes tolerance; a fixed 400 otherwise).
  2. Types handled: `checkout.session.completed`,
     `customer.subscription.created`, `.updated`, `.deleted`. Anything else:
     204, nothing done.
  3. `read_at = clock()` **before** the read, then
     `gateway.subscription(id)`, the current state, with no database lock
     held. A failure: 502, Stripe redelivers.
  4. `stripe_events.facts(...)` is pure: active and trialing → `active`;
     `past_due`; `incomplete` → `incomplete`; `incomplete_expired`, `canceled`,
     `unpaid`, `paused` → `ended`. Reads `current_period_end` from the
     subscription or its items and `cancel_at` as well as
     `cancel_at_period_end` (BILLING.md: the payload generations). The user:
     `metadata.user_id` as a UUID, else `billing_customers`, else logged and
     ignored with 204 (a subscription that is not ours). A price other than
     `STRIPE_PRICE_ID` still grants premium, with a WARNING: the customer is
     paying.
  5. In one transaction: the user `FOR KEY SHARE`; the upsert `ON CONFLICT
     (source, external_id) DO UPDATE … WHERE entitlements.read_at <=
     EXCLUDED.read_at`.
  6. The user is gone (a purchase completing after an account deletion, D15):
     the subscription, unless ended, is cancelled at Stripe and a WARNING
     logged with its id. 502 if that fails.
  - **Why this converges.** Every change at Stripe emits an event after it, so
    a handler starting later reads at least that change. The handler with the
    latest `read_at` has seen every change before its start, and any later
    change has its own later handler. A slow handler that read earlier can only
    lose to it.
  - **Idempotent by construction:** a repeated event reads the same state and
    writes the same row. There is no event ledger: it would save one API call
    per duplicate and need its own retention. A replayed signed body is
    bounded by the signature's tolerance and does nothing new.
  - The consent is written whatever the guard says, in the same transaction:
    it arrives once and nothing supersedes it.
- **D14 — The Customer Portal** is the only place to manage or cancel: card,
  invoices, cancellation at period end, resumption. Its configuration is set by
  the owner in the Stripe dashboard (DEPLOYMENT.md): no plan switching, cancel
  at period end. A cancellation is a `customer.subscription.updated` then
  `deleted` at period end, through D13. Rules out building those screens, and
  BILLING.md's provisioner (`stripe_catalog.py`): it exists for three tiers
  and their lookup keys; one yearly price is a dashboard step and one id.
- **D15 — Deleting an account stops billing first.** `DELETE /api/me` moves to
  `UnlockedSession`. Before any lock, for an account with a
  `billing_customers` row: `gateway.cancel_all(customer)` expires open
  sessions and cancels every subscription not ended, at once, asking Stripe
  rather than our rows (BILLING.md). Stripe is unreachable: 502
  `billing_unavailable`, nothing deleted, retrying is safe. Not purchasable
  while a row can still bill: 409 `billing_unavailable`, logged, with the
  runbook's procedure (BILLING.md's "no force-delete"). Then
  `lock_for_deletion`, new in `accounts/deps.py` (the user `FOR UPDATE`, as
  `user_to_delete` did, which goes), and the existing deletion, which removes
  both tables' rows by cascade. The Stripe customer stays: its invoices are
  the accounting record. A purchase completing meanwhile is cancelled on
  arrival (D13 step 6); user ids are random and never reused. Inside 14 days of
  `started_at`, a WARNING names the subscription, for the owner to refund by
  hand (D19).
- **D16 — What "purchasable" needs, and VAL.** `Settings.missing_billing_settings`,
  by variable name, like `missing_email_settings`:
  - always: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`,
    `BILLING_PRICE_AMOUNT` (a valid decimal), `PUBLIC_BASE_URL`;
  - outside production, `STRIPE_SECRET_KEY` counts as missing if it is a live
    key (`sk_live_`, `rk_live_`): VAL is seeded from PROD and must never be
    able to charge anyone. Rules out trusting VAL to have the right key
    (comments plan D19's reasoning);
  - in production only, also a live key, `STRIPE_AUTOMATIC_TAX=true`,
    `BILLING_TERMS_VERSION`, `BILLING_CONSENT_TEXT_EN`, `_FR`,
    `LEGAL_TERMS_URL`, `LEGAL_PRIVACY_URL`, `LEGAL_WITHDRAWAL_URL`: a first
    real sale needs the EU obligations in place (NEEDS).
  The app logs the missing names once at start. `seed-from-prod.sh` empties
  `entitlements` and `billing_customers` after the restore: PROD's ids mean
  nothing to VAL's Stripe test account. Guarded with `to_regclass`, since a
  dump can predate the tables.
  **Testing on VAL:** a Stripe sandbox or test-mode price, test keys, the
  webhook endpoint at `<val-host>/api/billing/webhook`, card
  `4242 4242 4242 4242`, `BILLING_ENFORCE_LIMITS=true`. The runbook lists the
  steps.
- **D17 — Placeholders.** The price and currency displayed:
  `BILLING_PRICE_AMOUNT`, `BILLING_PRICE_CURRENCY` (default `EUR`); empty amount
  means no offer. Legal links: `LEGAL_TERMS_URL`, `LEGAL_PRIVACY_URL`,
  `LEGAL_WITHDRAWAL_URL`; empty, the client links to its own public pages
  `/legal/terms`, `/legal/privacy`, `/legal/withdrawal`, each saying plainly
  that it is a placeholder and that nothing there is binding. The consent box:
  `BILLING_CONSENT_TEXT_EN`, `_FR`, `BILLING_TERMS_VERSION`. Outside production
  an unset text falls back to a constant starting `[TEST ONLY - placeholder,
  not legal text]`; production will not sell without the owner's texts (D16).
  No wording in the code or the repository is presented as final legal text.
  No publishable key: Checkout is a server-created redirect, so Stripe.js is
  not on any page and no `STRIPE_PUBLISHABLE_KEY` exists.
- **D18 — Client.** `GET /api/billing` drives everything, and a client never
  decides a limit itself.
  - **Nothing shows when there is nothing to show:** free, no offer, not
    enforced is today's account screen, no section (PROD now; BILLING.md: "no
    paywall exists anywhere").
  - **Account screen:** a "Your plan" section: Free or Premium, renewal or end
    date, the past-due line; "See Premium" (with an offer, free) or "Manage
    subscription" (`can_manage`, web); the three legal links.
  - **`/account/plan`:** a real route, because Stripe redirects the browser to
    it (BILLING.md). The free and premium lines generated from `limits`, never
    written alongside them; the price with "VAT included", formatted from
    `offer`; "Continue to payment"; the legal links. After
    `?checkout=success` it reads the status again up to 5 times, 2 seconds
    apart, then says the payment is being processed: the webhook can land after
    the redirect. Back falls back to `/account` when the stack is empty.
  - **Limit refused:** a dialog naming the limit, with "Not now" and, on the
    web, "See Premium". The form stays, with what the user typed. Enforcement
    implies an offer (D9), so the button never leads nowhere.
  - **Web only:** on Android and iOS no purchase, price or link to the web is
    shown (store rules, NEEDS). Status and limit messages still appear.
    Checkout opens in the same tab (`webOnlyWindowName: '_self'`).
- **D19 — Withdrawal: acknowledged at checkout, refunded by hand for now.**
  The acknowledgement and express consent are at checkout, as BILLING.md does
  it, "on the page that concludes the contract". BILLING.md's in-app
  withdrawal (ledger, credit notes, leases) is not in this plan's scope: for
  now the owner refunds in the Stripe dashboard, and `started_at` and the
  consent fields are stored so that it can be added without a migration. Live
  keys need that decision first (Open decisions).

## Review envelope

REVIEW.md defaults apply, with RESERVING_PLAN's and
COMMENTS_NOTIFICATIONS_PLAN's envelopes, and these additions:

- **The surprise floor extends to limits.** Any refusal, count, status, field,
  statement sequence or wait of an owner's request that differs with invitee
  activity is F1. That includes the order of answers on keep (D6) and any
  lock a giver's write could hold against an owner's growing path (D8). Lock
  waits between two owners of one list are out.
- **A new external service: Stripe.** Outbound HTTPS with a secret key; its
  answers can be late, wrong, missing or hostile (E2). Stripe receives the
  buyer's email, name, user id and language; it collects the card and address
  itself. No test reaches it.
- **A new unauthenticated route:** `POST /api/billing/webhook`. Anyone can
  call it. A request without a valid signature changing any state is F1. A
  validly signed event is trusted only as a pointer: the state comes from
  Stripe (D13).
- **Money.** A paying customer left without premium (silent), or a charge
  after an account deletion, is F3. Premium granted without a payment is not
  a floor by itself, unless reachable by a user's own action.
- **Concurrency.** Two owner requests at the limit, two webhook handlers on
  one subscription, a webhook during an account deletion, and two app
  processes during a container recreation are in. Exactly one request can take
  the last place.
- **Configuration is trusted (E3), but a wrong key in the wrong environment
  is in the envelope:** a live key on VAL must not be able to charge (D16).
- **Scale.** Yearly subscriptions, a few hundred users: a handful of webhook
  deliveries per purchase, each with one Stripe read. Each route that calls
  Stripe can hold an API worker thread up to 45 s.
- **Out of the envelope:** Stripe account set-up, VAT registration, legal
  correctness of the owner's texts, in-app withdrawal (D19), store purchases
  (D3), dunning emails (Stripe's own).

## Boundaries crossed

- **Schema (F4):** one migration after `c4f7d2a81e65`, new tables
  `entitlements` and `billing_customers` only. The previous release ignores
  them: rollback stays image-only (DevOps D15). Downgrade drops both, losing
  the local status and consent records; Stripe remains the source of both.
- **API contract (F4):** new routes D11. Existing response bodies do not
  change. New status codes, only when limits are enforced: 402 `plan_limit` on
  `POST /api/lists`, `POST /api/lists/{id}/gifts`,
  `DELETE /api/gifts/{id}/received`, `POST /api/gifts/{id}/keep`. New on
  `DELETE /api/me`, only with a Stripe customer: 502 and 409
  `billing_unavailable`. Clients without this release show their generic
  failure message (no mobile build is published, E5).
- **Stored data:** purchases and consent proof per account, deleted with the
  account (Stripe keeps its customer and invoices, for accounting). A later
  data-export plan includes the plan and purchase rows. VAL's seeding drops
  them (D16).
- **Stripe is a contract with the past:** `metadata.user_id` on subscriptions
  already sold must stay readable by later releases, and
  `/account/plan?checkout=…` must keep working.
- **Client:** new routes `/account/plan`, `/legal/terms`, `/legal/privacy`,
  `/legal/withdrawal` (the last three public).
- **Environment:** the 15 variables of U3, all optional, with safe defaults.

## Conventions

- Every new route is in both matrices: `/api/billing` joins
  `GUARDED_PREFIXES`, and each route goes to `COVERED_ELSEWHERE` with its own
  by-role test, since none names a list object and `ENDPOINTS` rows need one;
  each is called by the recipient in `test_surprise.py`. No route is excepted.
- `billing/limits.py` imports only `visibility`, list ownership and
  `entitlements`. A limit is counted through `visibility.counted` and nothing
  else (`test_only_the_visibility_module_names_the_hidden_gift_columns`
  stays green).
- A refusal is returned with a `code`, writes nothing, and carries no count of
  activity.
- No row lock across a Stripe call: `UnlockedSession`, then `lock_signed_in`
  or `lock_for_deletion`.
- `import stripe` appears only in `billing/stripe_gateway.py`.
- Tests never reach Stripe: `app.state.stripe_gateway` is a fake in every
  test. The signature check, which needs no network, runs for real.
- Tests of limits use the `billing_on` settings fixture (`client.app.state.settings`
  replaced with a `model_copy`), and a clock from `app.state.clock`.
- No secret, email, name or Stripe response body in any log or exception; only
  ids and fixed words. The repository holds variable names and descriptions
  only (it is public), never a key, id or price of the owner's.
- Every string in both ARB files, sentence case, no emoji; goldens light and
  dark through `.\goldens.ps1` only. The limit message mentions the plan and
  the limit, never anything about givers.
- Units with schema, the surprise, an unauthenticated route or account deletion
  (U1, U4, U5, U7, U9) get a unit review before integration (DELIVERY §5,
  point 3).
- Commits a user would notice carry a `Release-Note:` trailer in English.

## Open decisions

None of these blocks delivery: each has a placeholder or a safe default.

| Decision | Affects | Needed by |
|---|---|---|
| The price and currency (`BILLING_PRICE_AMOUNT`, `BILLING_PRICE_CURRENCY`) | The offer | Before VAL's purchase test, any test value works; the real one before live keys |
| Stripe account for Wishlist: its own or TraxJourney's | Keys, tax registration, statement descriptor | Before VAL's purchase test |
| OSS VAT registration, Stripe Tax set-up | `STRIPE_AUTOMATIC_TAX`, PROD | Before live keys |
| Terms of service, privacy policy, withdrawal text, the consent wording (owner, with legal review) | `LEGAL_*`, `BILLING_CONSENT_TEXT_*`, `/legal/*` | Before live keys |
| In-app withdrawal and refund (BILLING.md's ledger), against the hand refund of D19. To check with legal counsel: EU Directive 2023/2673 adds a withdrawal function for contracts concluded online, applying from June 2026 | A later plan | **Before live keys** |
| Handing a list over to a free owner already at the limit | The handover plan (not built) | That plan. Rule to keep: a handover is not growth and is not refused |
| Apple and Google purchases | A translator and a route per store (D3) | The mobile release plan |
| Turning `BILLING_ENFORCE_LIMITS` on in PROD | Existing accounts over the limit | After live keys and the runbook's query |
| An upgrade prompt before the limit is reached (a counter on the list) | Client | Revisit on user feedback |

## To record in NEEDS

For the orchestrator, under "Free and premium", dated 2026-11-10 (owner's
instruction to proceed silently):

- **Co-owned lists:** a list has no gift limit when at least one of its owners
  is premium, and then counts for none of its free co-owners.
- **Keep and put back are growth:** refused at the limit, like a new gift. The
  gift stays where it is (revealed or received); the owner can still mark it
  received, dismiss it, delete it, free a place or go premium. Limits apply
  only when something would actually grow.
- **Premium ends** at the end of the paid period, with a 3-day tolerance; a
  failed renewal keeps premium while Stripe retries the card.
- **Limits are a switch of their own**, off by default, and never apply while
  no purchase is possible. All numbers are configurable.
- **Purchases are on the web only** until the mobile apps have store
  purchases; the apps show the plan and the limits, and no price or purchase.
- **Deleting an account** cancels its subscription at once; Stripe keeps the
  customer and invoices for accounting.
- **Withdrawal:** acknowledged at checkout; for now a refund is made by hand
  in Stripe. An in-app withdrawal is decided before the first real sale.
- **Placeholders the owner supplies:** price, Stripe account and keys, legal
  texts and consent wording. Add these to "Open questions".

## Execution units

### Wave 1

#### U1 — Server: the entitlement model, settings and reading premium

- **Goal:** Purchases can be stored from any source, premium is computed from
  them, and every billing setting exists with its safe default.
- **Scope:** `server/app/billing/__init__.py`, `server/app/billing/models.py`,
  `server/app/billing/entitlements.py` (all new), `server/app/settings.py`,
  `server/alembic/env.py`, `server/alembic/versions/**` (one new revision),
  `server/tests/billing/conftest.py`, `server/tests/billing/test_entitlements.py`,
  `server/tests/billing/test_settings.py` (all new),
  `server/tests/conftest.py` (the `billing_on` fixture only),
  `server/tests/test_migrations.py`.
- **Context:** this plan D1–D3, D9, D16, D17, Boundaries crossed. Examples:
  `server/app/notifications/models.py` and revision `c4f7d2a81e65` (tables,
  check constraints), `Settings.missing_email_settings` for the properties,
  `server/tests/notifications/conftest.py` for the test package.
- **Do:**
  1. `models.py`: `Entitlement`, `BillingCustomer` per D1; registered in
     `alembic/env.py`; one revision after `c4f7d2a81e65`.
  2. `settings.py`: the fields of U3's table; integer fields `ge=0`; properties
     `missing_billing_settings` (D16), `billing_purchasable`,
     `limits_enforced` (D9), `billing_price` (a `Decimal` or None).
  3. `entitlements.py`: `EntitlementFacts`; `apply` (D13's upsert and guard;
     the user `FOR KEY SHARE` first, returning "user gone"); `is_premium`,
     `premium_condition(user_id, now)` (a SQL expression, D2), `summary`,
     `record_consent`.
  4. `billing_on` fixture: a dict of test values making
     `limits_enforced` true (`sk_test_`-shaped placeholder strings).
  5. Tests: `apply` inserts, updates, is idempotent; a stale `read_at` changes
     nothing and an equal one applies; premium true for `active` and
     `past_due` in period and through the 3 days, false after, for `incomplete`
     and `ended` and for a null `period_end`; premium from a row of each
     source, `apple` and `google` included;
     consent recorded whatever the guard; settings: everything unset →
     not purchasable, not enforced; enforcement without Stripe → not enforced;
     a live key outside production → reported missing; a test key in production
     → missing; each production-only variable reported; invalid amount →
     missing; defaults 1 and 20. `test_migrations.py`: upgrade and downgrade
     with rows present; account deletion cascades.
- **Acceptance:** `uv run --directory server ruff check`;
  `alembic upgrade head` then `alembic check`; `pytest` passes, including the
  named tests.
- **Out of scope:** routes, the Stripe SDK, limits on any route.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the Alembic head is not
  `c4f7d2a81e65`.
- **Depends on:** —

#### U2 — Client: the copy and the legal placeholder pages

- **Goal:** Every string of the feature exists in English and French, and the
  three public legal placeholder pages exist.
- **Scope:** `client/lib/l10n/app_en.arb`, `client/lib/l10n/app_fr.arb`,
  `client/lib/src/legal/legal_placeholder_screen.dart` (new),
  `client/lib/src/app_router.dart` (the three routes and `_publicPaths` only),
  `client/test/legal/**` (new), `client/test/app_router_test.dart`.
- **Context:** this plan D17, D18; `docs/DESIGN.md`. Example:
  `client/lib/src/unsubscribe/unsubscribe_screen.dart`, its golden and
  screen tests, and its route in `app_router.dart`, for a public page.
- **Do:**
  1. ARB keys (`legalPlaceholderBody` says the text is provisional):

     | Key | EN | FR |
     |---|---|---|
     | `planSectionTitle` | Your plan | Votre formule |
     | `planFree` | Free plan | Formule gratuite |
     | `planPremium` | Premium | Premium |
     | `planRenews(date)` | Renews on {date} | Renouvellement le {date} |
     | `planEnds(date)` | Ends on {date} | Se termine le {date} |
     | `planPastDue` | Your last payment failed. Update your card to keep Premium. | Votre dernier paiement a échoué. Mettez à jour votre carte pour conserver Premium. |
     | `planSee` | See Premium | Découvrir Premium |
     | `planManage` | Manage subscription | Gérer mon abonnement |
     | `planFreeLimits(lists, gifts)` | Free: {lists, plural, =1{1 list} other{{lists} lists}}, up to {gifts} gifts per list | Gratuit : {lists, plural, =1{1 liste} other{{lists} listes}}, jusqu'à {gifts} cadeaux par liste |
     | `planPremiumLimits` | Premium: unlimited lists and gifts | Premium : listes et cadeaux illimités |
     | `planPricePerYear(price)` | {price} per year, VAT included | {price} par an, TVA incluse |
     | `planBuy` | Continue to payment | Continuer vers le paiement |
     | `planMobileUnavailable` | Subscriptions are not available in the app yet. | L'abonnement n'est pas encore disponible dans l'application. |
     | `planCheckoutCancelled` | Payment cancelled. Nothing was charged. | Paiement annulé. Rien n'a été débité. |
     | `planCheckoutProcessing` | Your payment is being processed. Your plan will update shortly. | Votre paiement est en cours de traitement. Votre formule sera mise à jour sous peu. |
     | `planThanks` | You are on Premium. Thank you. | Vous êtes passé à Premium. Merci. |
     | `planLoadFailed` | Could not load your plan. | Impossible de charger votre formule. |
     | `planActionFailed` | That did not work. Try again in a moment. | Cela n'a pas fonctionné. Réessayez dans un instant. |
     | `planLimitTitle` | Free plan limit reached | Limite de la formule gratuite atteinte |
     | `planLimitLists(limit)` | The free plan includes {limit, plural, =1{1 list} other{{limit} lists}}. Your lists stay as they are. | La formule gratuite comprend {limit, plural, =1{1 liste} other{{limit} listes}}. Vos listes restent telles quelles. |
     | `planLimitGifts(limit)` | The free plan includes {limit} gifts per list. The gifts on this list stay as they are. | La formule gratuite comprend {limit} cadeaux par liste. Les cadeaux de cette liste restent tels quels. |
     | `planNotNow` | Not now | Pas maintenant |
     | `legalTerms` | Terms of service | Conditions générales |
     | `legalPrivacy` | Privacy | Confidentialité |
     | `legalWithdrawal` | Right of withdrawal | Droit de rétractation |
     | `legalPlaceholderBody` | This page is a placeholder. Its text has not been supplied yet, and nothing here is binding. | Cette page est provisoire. Son texte n'a pas encore été fourni et rien ici n'engage. |
  2. `legal_placeholder_screen.dart`: title by document, the body above.
  3. Routes `/legal/terms`, `/legal/privacy`, `/legal/withdrawal`, public.
  4. Tests: each page signed out and signed in (`authRedirect`), its title and
     body in both languages. Goldens light and dark of one page.
- **Acceptance:** `flutter analyze`; `flutter test` (ARB parity included);
  goldens through `.\goldens.ps1` and passing `.\goldens.ps1 -Check`.
- **Out of scope:** the account screen, `/account/plan`, the dialog, any real
  legal text.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed (X3); a key or text above
  does not fit the ARB format.
- **Depends on:** —

#### U3 — Infrastructure: environment and the owner's steps

- **Goal:** The owner can turn on a Stripe test purchase on VAL, and later live
  sales, from the runbook, with nothing secret committed, and VAL never
  inherits PROD's purchases.
- **Scope:** `deploy/prod/.env.example`, `deploy/val/.env.example`,
  `deploy/val/seed-from-prod.sh`, `docs/DEPLOYMENT.md`, `docs/DEVELOPMENT.md`.
- **Context:** this plan D9, D12, D14, D16, D17; the email block of the
  `.env.example` files and the notifications entry of DEPLOYMENT.md's
  "Release-specific steps" as the examples to follow.
- **Do:**
  1. Both `.env.example`, a new "Billing" block. Numbers and booleans are
     written with their defaults (an empty value would stop the app):

     | Variable | Default | Empty or default means |
     |---|---|---|
     | `BILLING_ENFORCE_LIMITS` | `false` | no limit applies |
     | `FREE_MAX_LISTS` | `1` | |
     | `FREE_MAX_GIFTS_PER_LIST` | `20` | |
     | `STRIPE_SECRET_KEY` | empty | no purchase. Secret |
     | `STRIPE_WEBHOOK_SECRET` | empty | no purchase. Secret |
     | `STRIPE_PRICE_ID` | empty | no purchase |
     | `STRIPE_AUTOMATIC_TAX` | `false` | no Stripe Tax; required in production |
     | `BILLING_PRICE_AMOUNT` | empty | no offer |
     | `BILLING_PRICE_CURRENCY` | `EUR` | |
     | `BILLING_TERMS_VERSION` | empty | required in production |
     | `BILLING_CONSENT_TEXT_EN`, `BILLING_CONSENT_TEXT_FR` | empty | test placeholder outside production; required in production |
     | `LEGAL_TERMS_URL`, `LEGAL_PRIVACY_URL`, `LEGAL_WITHDRAWAL_URL` | empty | the app's placeholder pages; required in production |

     VAL's says a live key is refused there.
  2. `seed-from-prod.sh`: after the restore, a `DO` block empties
     `entitlements` and `billing_customers` when they exist (D16), through the
     db container's `psql -v ON_ERROR_STOP=1`.
  3. DEPLOYMENT.md: placeholders `<stripe-secret-key>`,
     `<stripe-webhook-secret>`, `<stripe-price-id>`; a "Release-specific steps"
     entry for this release: copy the block into each `.env`; update
     `seed-from-prod.sh` on the host. Then **Stripe test on VAL:** a Stripe
     sandbox; a product with a yearly, tax-inclusive price in test mode; the
     public details' terms URL (`https://<val-host>/legal/terms`), without
     which Checkout fails; the portal configuration (cancel at period end, no
     plan change); the "limit customers to one subscription" setting; the
     webhook endpoint with the four events of D13; the variables; `docker
     compose up -d`; the start log no longer naming them; test card; check
     `GET /api/billing`; cancel in the portal. **Enforcement:** the count query
     to run first (read-only, counts only). **Before live keys, on PROD:** OSS
     registration, Stripe Tax, the texts and URLs, and the Open decisions.
     **Account deletion refused with 409:** the procedure, adapted from
     BILLING.md.
  4. DEVELOPMENT.md: DEV has no billing unless the variables are set; `stripe
     listen --forward-to localhost:8000/api/billing/webhook`.
- **Acceptance:** `shellcheck deploy/val/seed-from-prod.sh`; the
  `deploy-smoke` workflow passes; every variable above appears in both
  examples and DEPLOYMENT.md; `git grep` finds no key, host or address in the
  changed files.
- **Out of scope:** server code; the owner's Stripe account; the compose files
  (`env_file:` passes the variables).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the compose files need
  a change.
- **Depends on:** —

### Wave 2

#### U4 — Server: the limits on the four growing paths

- **Goal:** With limits enforced, a free owner cannot grow past the limit by
  any path, one concurrent request takes the last place, nothing is deleted,
  and no invitee activity affects the answer or makes an owner wait.
- **Scope:** `server/app/billing/limits.py` (new),
  `server/app/lists/router.py` (`create_list`, `add_gift`, `put_back`,
  `keep_gift` and a refusal helper only),
  `server/app/hidden_gifts/lifecycle.py` (`keep_revealed`, `set_received`
  only), `server/tests/lists/test_plan_limits.py`,
  `server/tests/lists/test_concurrent_plan_limits.py` (both new),
  `server/tests/lists/test_owner_work.py`.
- **Context:** this plan D4–D9, Conventions. Examples: `_not_revealed` and
  `NotRevealed` for a coded refusal, `digests.py` `_lock_key` for the advisory
  lock, `test_concurrent_reservations.py` and `locks.py` for concurrency,
  `test_owner_work.py` for the statement comparison.
- **Do:**
  1. `limits.py`: `PlanLimitReached(resource, limit)`, `PlanLimitRefusal`;
     `ensure_room_for_list(db, settings, user_id, now)` and
     `lock_gift_growth(db, settings, list_id)`,
     `ensure_room_for_gift(db, settings, list_id, now)`, each doing nothing
     unless `settings.limits_enforced`.
  2. `create_list`, `add_gift`: check after the ownership resolves, before
     anything is written; catch and return 402.
  3. `keep_revealed` and `set_received` take `settings`. Keep: on a gift of the
     list, `NotRevealed` first, as today; lock; then, after the reveal is
     confirmed, `ensure_room_for_gift`. Put back: the gift on the list locked
     as growth, read again, and refused only if still received (D6).
  4. `test_plan_limits.py`: the limit and the next request (lists, gifts);
     402's exact body; received, hidden and revealed gifts do not count;
     marking received frees a place; put back at the limit 402 (it stays
     received), of a gift on the list a no-op, of a revealed gift never 402;
     keep at the limit 402 (still revealed, same id), under it a new id;
     keep on an unrevealed id at the limit: the random id's 404; on a gift on
     the list at the limit: 409 `not_revealed`; an over-limit list: reads,
     edits, occasions, links and images all work; premium: no limit; premium
     ended by the clock: nothing deleted, no growth; a premium co-owner covers
     the list for both, and it does not count for a free co-owner (D5, the row
     inserted as `test_surprise.py` does); enforcement off, or on without
     Stripe: no limit and no advisory lock (statements); the variables change
     the limits; an invitee at their own limit, and a "for someone else" owner
     at the limit, can still join, reserve, pledge, comment and add hidden
     gifts; `limits.py` imports no claim, comment, follow, notification or
     hidden-gift module (D7, read from its source).
  5. `test_concurrent_plan_limits.py`, 20 rounds each (`together`): adds at
     one place left → one 201; create list; keep racing add; put back racing
     add; and a giver's open transaction (a hidden gift inserted and a claim
     held, not committed) does not delay the owner's add, create, keep or put
     back (each finishes while it is open).
  6. `test_owner_work.py`: with enforcement on, `POST /api/lists/{id}/gifts`,
     `POST /api/lists` and put back on twins with each activity and without:
     identical statements.
- **Acceptance:** `ruff check`; `pytest` passes, including the tests of Do 4–6,
  `test_received.py`, `test_hidden_gifts.py`,
  `test_only_the_visibility_module_names_the_hidden_gift_columns`.
- **Out of scope:** routes under `/api/billing`, Stripe, the client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a growing path exists
  beyond D4's four; a limit cannot be decided without reading activity; an
  owner's request is found waiting on a giver's transaction.
- **Depends on:** U1.

#### U5 — Server: Stripe, the billing routes and the webhook

- **Goal:** With Stripe configured, a user can buy, manage and see their
  subscription, and premium follows Stripe through a verified webhook,
  whatever the order of its events.
- **Scope:** `server/app/billing/stripe_gateway.py`,
  `server/app/billing/stripe_events.py`, `server/app/billing/schemas.py`,
  `server/app/billing/router.py` (all new), `server/app/main.py` (the gateway,
  the router, the start log), `server/pyproject.toml`, `server/uv.lock`,
  `server/tests/conftest.py` (`FakeStripe` in `make_client`),
  `server/tests/billing/test_status.py`, `test_checkout.py`, `test_portal.py`,
  `test_webhook.py`, `test_stripe_events.py`, `test_stripe_gateway.py`,
  `test_concurrent_webhook.py` (all new), `server/tests/lists/test_roles.py`,
  `server/tests/lists/test_surprise.py` (D11's routes only).
- **Context:** this plan D10–D14, D16, D17, Review envelope. Read
  `E:\Dev\TraxJourney\docs\BILLING.md` and `src/billing/stripe_gateway.py`,
  `webhook_events.py` (reference only: the payload generations, the consent
  parameters; do not copy its ordering). Examples:
  `notifications/mailer.py` and `tests/notifications/test_mailer.py` (an
  external service behind a class, typed outcomes, no secret in logs),
  `notifications/router.py` (an unauthenticated route), `media/router.py`
  `_read_body` (a capped body) and `lock_signed_in` (work before the lock).
- **Do:**
  1. `pyproject.toml`: `stripe>=16.0.0,<17`, with a comment; `uv lock`.
  2. `stripe_gateway.py`: per D10; `verify`, `price`, `ensure_customer`,
     `expire_open_sessions`, `checkout`, `portal`, `subscription`, `cancel`.
  3. `stripe_events.py`: pure, per D13 step 4.
  4. `schemas.py`, `router.py`: D11, D12, D13, D14.
  5. `main.py`: `app.state.stripe_gateway` built only when purchasable; the
     router; one start-up log naming `missing_billing_settings` when some of
     Stripe's are set or enforcement is asked for.
  6. Tests, with `FakeStripe` recording calls, and an explicit clock:
     - status: free, premium, past due, canceling; limits null for premium;
       offer null unset; `enforced` true only with Stripe; the legal URLs;
     - checkout: 404 unset; parameters exactly D12's, consent and locale by
       language; tax on and off; success and cancel URLs from
       `PUBLIC_BASE_URL`; 409 if premium; 503 for a monthly, exclusive, wrong
       amount or wrong currency price; customer reused, created once under
       two concurrent checkouts; open sessions expired; 502 when Stripe
       fails; no lock held during a Stripe call (a concurrent account
       deletion does not wait);
     - portal: 404 unset; 409 without a customer; the return URL;
     - webhook: 404 unset; 400 on bad signature, no signature, a body over
       1 MiB; an unhandled type 204; out of order: a `deleted` before an
       `updated`, a `created` read as active; a duplicate leaves one row;
       Stripe failing: 502, then a redelivery applies; consent recorded once
       on `checkout.session.completed`; an unknown price grants premium with a
       WARNING; a subscription with no known user: 204, no row; a user gone:
       cancelled, and an ended one is not; two subscriptions in force: an
       ERROR; no secret, email or body in any log (`caplog`);
     - `stripe_events`: each status mapping, both period-end shapes,
       `cancel_at`, malformed values;
     - `stripe_gateway`: a signature made locally with the real SDK accepted,
       a wrong one refused, a stale timestamp refused, with no network; every
       Stripe error class mapped;
     - `test_concurrent_webhook.py`: an older read committing after a newer
       one does not overwrite it; a webhook during an account deletion waits,
       then finds the user gone.
  7. `test_roles.py`: `/api/billing` in `GUARDED_PREFIXES`, the four routes in
     `COVERED_ELSEWHERE` with `test_billing_status_by_role`,
     `test_billing_sessions_by_role`, `test_stripe_webhook_by_role` (every
     actor: no signature, no effect, the same answer).
  8. `test_surprise.py`: `reads` calls the four routes (`Recorder.call`,
     webhook with `content=`), so `test_every_route_is_called` passes.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including the tests of Do 6–8,
  `test_every_route_is_in_the_matrix`, `test_every_route_is_called`.
- **Out of scope:** limits (U4), account deletion (U7), the client, in-app
  withdrawal, an event ledger, `stripe_catalog`-style provisioning.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the SDK's 16.x API
  differs from D12 or D13 in a way that changes the contract; a state cannot be
  read back from Stripe; a schema change is needed.
- **Depends on:** U1.

#### U6 — Client: the plan on the account screen and the upgrade flow

- **Goal:** A user sees their plan on the account screen, can buy Premium on
  the web through `/account/plan`, can manage their subscription, and sees
  nothing of this when there is nothing to offer.
- **Scope:** `client/lib/src/billing/billing_repository.dart`,
  `client/lib/src/billing/plan_screen.dart`,
  `client/lib/src/billing/legal_links.dart` (all new),
  `client/lib/src/auth/account_screen.dart`,
  `client/lib/src/app_router.dart` (`/account/plan` only),
  `client/test/billing/**` (new), `client/test/auth/account_screen_test.dart`,
  `client/test/support/fakes.dart`, `client/test/goldens/**`,
  `client/test/auth_screens_golden_test.dart`, ARB files (only a key U2 lacks,
  reported).
- **Context:** this plan D11 (the contract U5 builds in parallel), D17, D18.
  Examples: `auth/preferences_repository.dart` (repository and `of`),
  `account_screen.dart`, `lists/price.dart` (formatting an amount),
  `lists/gift_links.dart` and `installFakeUrlLauncher`, and BILLING.md "Where
  the plan UI lives" (the redirect's two known bugs).
- **Do:**
  1. `billing_repository.dart`: `BillingStatus` from `GET /api/billing`;
     `startCheckout`, `openPortal` returning URLs.
  2. Account screen: the section per D18, absent for free, no offer, not
     enforced; a failed read leaves the screen as it is today, with no error.
  3. `/account/plan`: per D18, under the sign-in guard.
  4. `legal_links.dart`: the three links, a server URL or the local page.
  5. Tests: every status of the section; nothing for the unset state; web and
     mobile (`kIsWeb` behind a test seam); checkout opens the URL in the same
     tab; 409 `already_premium` reloads; 503 and 502 say `planActionFailed`;
     portal opens; `?checkout=success` re-reads up to 5 times and stops on
     premium, else the processing message; `cancelled` says so; back on an
     empty stack goes to `/account`; legal links: server URL and fallback;
     French. Goldens light and dark: account screen free with offer and
     premium (the existing golden unchanged for the unset state), plan screen
     free and premium.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 5; goldens
  through `.\goldens.ps1` and `.\goldens.ps1 -Check`; `flutter build web
  --release`.
- **Out of scope:** the limit dialog (U8), the list screens, store purchases.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the redirect cannot
  return to `/account/plan` through the sign-in guard.
- **Depends on:** U2.

### Wave 3

#### U7 — Server: deleting an account stops its billing first

- **Goal:** Deleting an account cancels its Stripe subscriptions before
  anything is removed, without holding a lock across Stripe, and refuses
  rather than leave someone billed.
- **Scope:** `server/app/billing/closing.py` (new),
  `server/app/accounts/router.py` (`delete_me` only),
  `server/app/accounts/deps.py` (`lock_for_deletion` replacing
  `user_to_delete`), `server/tests/billing/test_account_deletion.py` (new),
  `server/tests/lists/test_concurrent_account_deletion.py`.
- **Context:** this plan D15, D13 step 6; BILLING.md "Deleting an account".
  Examples: `lock_signed_in` in `deps.py`, its use in `media/router.py`,
  `tests/lists/test_concurrent_account_deletion.py`.
- **Do:**
  1. `closing.py`: `stop_billing(db, gateway, user_id, now)` per D15.
  2. `delete_me` per D15; the lock order and every comment on it stay true.
  3. Tests: no customer: no Stripe call; a customer: open sessions expired,
     subscriptions cancelled, before the rows go; Stripe failing: 502, nothing
     deleted, retrying works; not purchasable with a row that can bill: 409,
     and with an ended row: deleted; a repeated call: 401, as today; a WARNING
     inside 14 days, none after; a concurrent request of that user does not
     wait during the Stripe call (held by the fake); the Stripe customer is
     never deleted.
- **Acceptance:** `ruff check`; `pytest` passes, including the tests of Do 3,
  `test_concurrent_account_deletion.py`, `test_account_deletion.py`.
- **Out of scope:** refunds (D19), the webhook (U5).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the lock order of
  `delete_me` cannot be kept; a test about concurrency has to weaken.
- **Depends on:** U1, U5.

#### U8 — Client: the limit message

- **Goal:** When creating a list or gift, keeping a revealed gift or putting
  one back is refused by the limit, the owner sees what happened and can go to
  Premium, and nothing they typed is lost.
- **Scope:** `client/lib/src/billing/plan_limit_dialog.dart` (new),
  `client/lib/src/lists/lists_repository.dart`,
  `client/lib/src/lists/gift_form_screen.dart`,
  `client/lib/src/lists/list_form_screen.dart`,
  `client/lib/src/lists/list_detail_screen.dart`,
  `client/test/lists/**`, `client/test/lists/support/fake_lists_server.dart`,
  ARB files (only a key U2 lacks, reported).
- **Context:** this plan D4, D6, D18. Examples: `HiddenGiftRefused` and
  `NotRevealed` for typed refusals, `gift_form_screen.dart` `_save`,
  `list_detail_screen.dart` `_act`, `confirmAction` for a dialog.
- **Do:**
  1. `PlanLimitReached(resource, limit)` from a 402 `plan_limit`, on
     `createList`, `addGift`, `putBack`, `keep`.
  2. `plan_limit_dialog.dart`: per D18 (`planLimitTitle`, `planLimitLists` or
     `planLimitGifts`, `planNotNow`, `planSee` on the web, leading to
     `/account/plan`).
  3. Forms and `_act` show it; a form stays on screen with its fields, the
     pending image included. Hidden-gift forms never can get it.
  4. Tests: each of the four paths; the form keeps its values; "See Premium"
     navigates on the web and is absent on mobile; a 402 without our code is
     the generic failure; the hidden-gift form is untouched; French. Goldens
     light and dark of the dialog.
- **Acceptance:** `flutter analyze`; `flutter test`; the tests of Do 4; goldens
  through `.\goldens.ps1` and `.\goldens.ps1 -Check`.
- **Out of scope:** a pre-emptive counter or disabled buttons (Open decisions).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a form loses its state
  when the dialog opens.
- **Depends on:** U2, U6.

### Wave 4

#### U9 — Server: the surprise at the limit, end to end

- **Goal:** A suite proves that, with limits enforced and a list at the limit,
  the recipient's every answer is the control's whatever the activity, and
  that each role meets the limit as the rules say.
- **Scope:** `server/tests/lists/test_surprise.py`,
  `server/tests/lists/test_roles.py`,
  `server/tests/lists/test_owner_work.py`. Server code only if a test fails,
  through X3.
- **Context:** this plan D4–D8, Review envelope; the existing `build`,
  `Recorder`, `reads`, `differences`, `compared` of `test_surprise.py`, and
  `test_a_revealed_gift_shows_as_the_gift_alone` as the example of a run that
  goes past the occasion.
- **Do:**
  1. `test_surprise.py`, `test_the_recipient_sees_nothing_at_the_limit`, for
     every state of `STATES` and `HIDDEN_STATES`, owner and co-owner, world
     against control, enforcement on through `billing_on` and
     `free_max_gifts_per_list` = the world's gifts, `free_max_lists` = 1:
     `POST /api/lists` and `POST /api/lists/{id}/gifts` answer 402 in both;
     `GET /api/billing` equal; G1 received, a place freed, a new gift 201, G1
     put back 402, twin of G2; `POST /gifts/{H}/keep` on an unrevealed hidden
     id: what a random id gets; then all of `reads`. Renaming and twins as
     in `test_the_recipient_sees_nothing`.
  2. A premium owner and a free one, same world: the same refusals, with
     activity and without.
  3. Revealed at the limit: keep answers 402, for the world's revealed gift
     only, the control's random id 404, as
     `test_a_revealed_gift_shows_as_the_gift_alone` allows; the rest compared.
  4. `test_roles.py`, `test_the_limit_by_role`: with the scenario at the
     limit, for each actor and list: an owner's gift and list creations 402,
     identical on both lists; invitees and the giving owner keep every giver
     route; strangers and the removed get the 404 and a random id's answer;
     signed out 401.
  5. `test_owner_work.py`: `keep` on twin revealed gifts with and without a
     thread and followers, enforcement on: identical statements.
- **Acceptance:** `ruff check`; `pytest` passes with the extended suites; no
  server file changed, or each change escalated and approved (X3).
- **Out of scope:** new features.
- **Latitude:** local design.
- **Escalate if:** any comparison fails (an F1 finding: report it, do not fix
  it inside this unit); a file outside Scope is needed (X3).
- **Depends on:** U4, U5, U7.

## Definition of done

- With no billing variable set (DEV, CI, PROD now): every account is
  unlimited, no purchase, price or plan section shows, `/api/billing/checkout`,
  `/portal` and `/webhook` answer 404, and nothing fails.
- On VAL with Stripe test keys, a test price and enforcement on: a free user
  gets the limit message on a second list and a 21st gift, buys Premium with a
  test card, is premium once the webhook lands, grows past both limits, and
  cancels in the portal; premium then ends with nothing deleted, the lists stay
  readable, shareable and editable, and cannot grow.
- A live key on VAL is refused and logged by name, and no live charge is
  possible without the owner's own variables on PROD.
- Checkout shows the required terms box with the consent text, tax-inclusive
  price and, with `STRIPE_AUTOMATIC_TAX`, Stripe Tax; the consent is on the
  entitlement row.
- Stripe's events delivered late, twice or out of order leave the correct
  status (`test_webhook.py`, `test_concurrent_webhook.py`); an invalid
  signature changes nothing.
- Concurrent requests at the last place: exactly one succeeds
  (`test_concurrent_plan_limits.py`), and an owner's request never waits on a
  giver's transaction.
- Keep and put back are refused at the limit after the reveal check; an
  unrevealed hidden gift's id answers 404 at the limit.
- A premium co-owner covers a shared list; invitees are never limited,
  whatever their own plan.
- The recipient's answers at the limit are identical with and without activity
  (`test_surprise.py`); every new route is in both matrices.
- Deleting an account with a subscription cancels it first; a failure deletes
  nothing.
- Legal links lead to the owner's URLs or to pages clearly marked as
  placeholders; no text is presented as final legal wording.
- `apple` and `google` sources are accepted by the model and tested through
  `apply`; no validator exists.
- All DELIVERY.md §2 checks pass on server, client and infrastructure, goldens
  included.
