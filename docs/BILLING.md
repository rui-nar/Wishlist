# Billing: getting Premium up and running

What to do in Stripe and on the VPS to start selling Premium, in order: first a
test on VAL, then real sales on PROD. There is no admin screen in the app: it
is set up entirely with Stripe's dashboard and the variables in each `.env`.

[DEPLOYMENT](DEPLOYMENT.md#billing-with-stripe) remains the runbook for
incidents and rare procedures, and this guide links to it where needed. For a
local trial, see [DEVELOPMENT](DEVELOPMENT.md#billing-in-dev). The earlier plans
and some code comments cite a `BILLING.md`: they mean TraxJourney's document of
that name, not this one.

Each step says where it happens: **[Stripe]** the dashboard, **[VPS]** a shell
on the server, **[dev]** a browser on your machine. `<val-host>` and the other
placeholders are as in [DEPLOYMENT](DEPLOYMENT.md#placeholders): real values
never go in this repository.

The dashboard links and setting names were taken from docs.stripe.com on
2026-11-10. Stripe renames its menus from time to time, and the links are more
stable than the names.

## How it works

| State | What it takes | What people see |
|---|---|---|
| **Off** (today) | Nothing | No plan section, no limits, no purchase |
| **Gateway** | The two Stripe secrets | Webhooks, portal and cancelling at account deletion work; nothing on sale |
| **Selling** | Gateway, price and `PUBLIC_BASE_URL`; on PROD also tax and legal | The plan section and the purchase, on the web only |
| **Limits on** | Selling and `BILLING_ENFORCE_LIMITS=true` | Free accounts cannot grow past the limits |

Premium bought on iPhone, through Apple, is a separate set-up with its own
steps: [Part 3](#part-3-selling-on-iphone). It does not change the states above.

The app refuses a live key on VAL and a test key on PROD, as if the key were
empty. Limits never apply unless the app is selling, so nobody is blocked with
no way to pay.

## Part 1: test on VAL

### 1. Check the VPS is ready

**[VPS]** Each `.env` needs the billing lines, added once from the examples
([release steps](DEPLOYMENT.md#release-specific-steps), "The release with
premium"). `PUBLIC_BASE_URL` must be set too:

```bash
grep -c -E '^(BILLING_|FREE_MAX_|STRIPE_|LEGAL_)' /opt/wishlist-val/.env /opt/wishlist/.env   # :15 for both
grep -n '^PUBLIC_BASE_URL=' /opt/wishlist-val/.env /opt/wishlist/.env                         # each with its https:// origin
```

### 2. Choose the Stripe account

**Use an account of its own for Wishlist** rather than TraxJourney's. It is safe
to share, because the app only ever cancels subscriptions it marked as its own.
But the terms URL, the failed-payment rule, the portal and the name on card
statements are per account, so Wishlist's buyers would get TraxJourney's.

### 3. Create a sandbox for VAL

**[Stripe]** Open the account selector, then Sandboxes, and create one named
for VAL. Everything in step 4 has to be done inside it: sandboxes share nothing,
neither with each other nor with live mode.

Give each environment its own sandbox. A webhook cancels subscriptions it finds
no account for, so two environments on one sandbox would cancel each other's.

### 4. Set up the sandbox

**[Stripe]** All seven are needed:

| # | Where | What to set |
|---|---|---|
| 1 | [Product catalogue](https://dashboard.stripe.com/products) → Add product | One recurring **yearly** price (not 12 months) with **Include tax in price: yes**, not "auto". Any amount works for the test. Stripe does not let you change this later: a wrong price means a new price. Note the price id, `price_…` |
| 2 | [Public details](https://dashboard.stripe.com/settings/public) → Terms of service | `https://<val-host>/legal/terms`. Every checkout fails without it |
| 3 | [Customer portal](https://dashboard.stripe.com/test/settings/billing/portal) | Cancel subscriptions on, **at the end of the billing period**. Payment methods on. Invoice history on. Switch plan **off**. Portal login link on. **Save**: the portal does not work until saved once |
| 4 | [Checkout settings](https://dashboard.stripe.com/settings/checkout#subscriptions) | **Limit customers to one subscription**. It relies on the portal login link of the row above |
| 5 | [Retries](https://dashboard.stripe.com/revenue_recovery/retries) | If all retries fail: **Cancel the subscription**. Never leave it past due, which keeps Premium for a card that never pays |
| 6 | [Webhooks](https://dashboard.stripe.com/webhooks) → Create an event destination | Your account, snapshot payload, the default API version. Exactly four events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`. Type webhook endpoint, URL `https://<val-host>/api/billing/webhook`. Reveal the signing secret, `whsec_…` |
| 7 | [API keys](https://dashboard.stripe.com/apikeys) | Copy the secret key, `sk_test_…` |

### 5. Fill in VAL

**[VPS]** The secrets are typed at a hidden prompt, so that they stay out of the
shell history. The amount is the price from row 1, for example `12.00`. If the
price is not in euros, also set `BILLING_PRICE_CURRENCY`. The legal variables
stay empty: VAL shows placeholders.

```bash
cd /opt/wishlist-val
read -rs STRIPE_KEY                                # paste the secret key, then Enter
sed -i "s|^STRIPE_SECRET_KEY=.*|STRIPE_SECRET_KEY=$STRIPE_KEY|" .env
unset STRIPE_KEY
read -rs STRIPE_WEBHOOK                            # paste the signing secret, then Enter
sed -i "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK|" .env
unset STRIPE_WEBHOOK
sed -i 's|^STRIPE_PRICE_ID=.*|STRIPE_PRICE_ID=<stripe-price-id>|' .env
sed -i 's|^BILLING_PRICE_AMOUNT=.*|BILLING_PRICE_AMOUNT=<price-amount>|' .env
sed -i 's|^BILLING_ENFORCE_LIMITS=.*|BILLING_ENFORCE_LIMITS=true|' .env
grep -c -E '^(STRIPE_SECRET_KEY=(sk|rk)_test_|STRIPE_WEBHOOK_SECRET=whsec_)' .env   # 2
docker compose up -d --wait --wait-timeout 300
docker compose logs app | grep 'billing is not selling'                             # nothing
```

Any line printed names what is still missing. Use `up -d` after every change to
`.env`: `docker compose restart` does not re-read it.

### 6. Buy Premium on VAL

**[dev]** On `https://<val-host>`, signed in with a free account:

1. The account screen shows "Your plan" with the price.
2. A second list, and a 21st gift on a list, are refused with the limit message.
3. See Premium → Continue to payment. Card `4242 4242 4242 4242`, any future
   date, any CVC. Tick the terms box.
4. Back in the app, Premium appears and the limits are gone. In Stripe, the
   webhook's event deliveries answer 204.
5. Manage subscription → cancel. Premium stays until the end of the paid year.
6. In Stripe, cancel that subscription **immediately**. The account is free
   again, nothing was deleted, and the limit message is back.

### 7. Test a failed renewal

**Do this before going live.** Follow [A failed renewal, on
VAL](DEPLOYMENT.md#a-failed-renewal-on-val), which needs the
[Stripe CLI](https://docs.stripe.com/stripe-cli) and a simulated clock. It
proves that a card that never pays ends Premium, and settles what Stripe's docs
leave unclear: how the renewal date moves after a failed payment. Record the
result in `docs/reviews/PREMIUM_PLAN.md` as the runbook says.

### 8. Test the tax at checkout

PROD requires Stripe Tax, and the test above runs without it. **[Stripe]** In
the sandbox, go through step 3 of Part 2. **[VPS]** Set
`STRIPE_AUTOMATIC_TAX=true` in VAL's `.env` and run the `up -d` line. **[dev]**
Buy again with a free account: Checkout now asks for a billing address, and the
total stays the price you set, tax included.

## Part 2: real sales on PROD

### 1. Settle what only you can decide

Each of these must be done before a live key goes in:

- [ ] The real price and currency.
- [ ] VAT: OSS registration, with your accountant.
- [ ] Your terms of service, privacy policy and withdrawal pages, published at
      `https` addresses, and the one-line consent sentence in English and
      French. Have them reviewed: nothing in this repository is legal text.
- [ ] Ask your lawyer whether EU Directive 2023/2673 requires an in-app
      withdrawal function. The app has none: withdrawal is acknowledged at
      checkout, and refunds are made by hand.

### 2. Activate the live account

**[Stripe]** Leave the sandbox, complete the account's activation (business
details, bank account) and set the name shown on card statements.

Then repeat [step 4](#4-set-up-the-sandbox) in live mode, with two differences.
In row 2, the terms URL is your real terms page, the same address as
`LEGAL_TERMS_URL`: the app's `/legal/terms` only ever shows a placeholder. In
row 6, the URL is `https://<prod-host>/api/billing/webhook`, and the endpoint
has its own secret. The key is `sk_live_…`.

Customer portal row 3: the link in the table is for test mode. In live mode,
use [this one](https://dashboard.stripe.com/settings/billing/portal).

The app sends no billing emails of its own. Receipts and failed-payment emails
are Stripe's: turn on the ones you want in its customer email settings.

### 3. Set up Stripe Tax

**[Stripe]** In [Tax settings](https://dashboard.stripe.com/settings/tax): start
Stripe Tax, check the head office address, and choose a default product tax code
for an electronically supplied service (confirm which with your accountant).
Then in [Registrations](https://dashboard.stripe.com/tax/locations), add your
registration, type **Union OSS**, using "I've already registered". Without a
registration, Stripe collects no tax for that place.

### 4. Fill in PROD

**[VPS]** The same `read -rs` and `sed` lines as [step 5](#5-fill-in-val), in
`/opt/wishlist`, with `live` in the check instead of `test`:

```bash
grep -c -E '^(STRIPE_SECRET_KEY=(sk|rk)_live_|STRIPE_WEBHOOK_SECRET=whsec_)' .env   # 2
```

Leave out the `BILLING_ENFORCE_LIMITS` line: it stays `false` until step 6.

Then `nano .env` for these. Each value goes on one line, not quoted, and never
with ` #` inside, which would cut it there:

```text
STRIPE_AUTOMATIC_TAX=true
BILLING_TERMS_VERSION=<a name for this wording, such as 2026-11>
BILLING_CONSENT_TEXT_EN=<the English sentence>
BILLING_CONSENT_TEXT_FR=<the French sentence>
LEGAL_TERMS_URL=<https address>
LEGAL_PRIVACY_URL=<https address>
LEGAL_WITHDRAWAL_URL=<https address>
```

Change `BILLING_TERMS_VERSION` whenever the wording changes: it is stored with
each purchase as proof of what was accepted. Finish with the `up -d` and
`billing is not selling` lines of step 5.

### 5. Make one real purchase

**[dev]** Buy Premium with your own card on `https://<prod-host>`. Check that the
total, tax and links are right, and that Premium appears. **[Stripe]** Refund the
payment and cancel the subscription immediately.

### 6. Turn the limits on

Only once selling works. Anyone already past a limit keeps everything but cannot
grow. Run [the count](DEPLOYMENT.md#turning-enforcement-on) to see how many
that affects, then set `BILLING_ENFORCE_LIMITS=true` and run the `up -d` line.
To change the limits themselves, use `FREE_MAX_LISTS` and
`FREE_MAX_GIFTS_PER_LIST`.

## Part 3: selling on iPhone

Apple requires its own in-app purchase for a subscription sold inside an iOS
app, so Premium on iPhone is bought from Apple and not from Stripe
([plan](plans/APPLE_IAP_PLAN.md)). Stripe's set-up above is unchanged and
independent: either store grants the same Premium, and the app offers no
purchase while Premium is already in force from the other.

Each step says where it happens, as above, with **[Apple]** for App Store
Connect. The menu names below were written from Apple's documentation and not
checked against App Store Connect: Apple renames its menus from time to time,
so follow the meaning when a name differs.

What the server does, so the steps make sense:

- The app sends each purchase to the server, which asks Apple's App Store
  Server API what the subscription is, and records Apple's answer. The
  In-App Purchase key of step 3 is what lets it ask.
- Apple also sends notifications (renewal, cancellation, refund) to the URL of
  step 4. The server treats one as a pointer only and asks Apple again.
- **VAL** accepts Sandbox purchases only, which cost nothing. **PROD** accepts
  real purchases, and Sandbox ones only from the accounts listed in
  `APPLE_SANDBOX_ACCOUNT_IDS`: the demo account of step 6, for App Review. Any
  other Sandbox purchase on PROD is refused and logged.
- Premium lasts through Apple's billing grace period (16 days) and no longer.
  A refund ends it at once.
- Selling on iPhone does not turn the free limits on: they depend on Stripe
  selling ([Part 2](#6-turn-the-limits-on)). Only the iOS app offers the Apple
  purchase.

It needs the iOS apps of [DEPLOYMENT step 13](DEPLOYMENT.md#13-ios-app) to
exist in App Store Connect first: **two apps** with different bundle ids, the
VAL app and the PROD app. Do VAL first, test it, then PROD.

### 1. Sign the Paid Apps agreement

**[Apple]** Business (Agreements, Tax, and Banking). The Account Holder signs
the **Paid Apps** agreement, then fills in the tax forms and the bank account.
Until its status is Active, no subscription can be sold. Tax and banking are
yours to settle with your accountant: nothing in this repository is advice on
them.

The price per storefront is also yours to decide before PROD sells. The app
always shows Apple's own price for the buyer's storefront, never
`BILLING_PRICE_AMOUNT`.

### 2. Create the subscription in each app

**[Apple]** Do this once in the VAL app, then again in the PROD app. The two
apps do not share subscriptions, but give the product **the same id** in both,
so that the variable is the same on both servers.

| # | Where | What to set |
|---|---|---|
| 1 | App → Monetization → Subscriptions → Create a group | A subscription group, named for example "Premium" |
| 2 | In the group → Create | A subscription: a reference name, and a product id, `<apple-product-id>`. The id cannot be changed or reused once created |
| 3 | The subscription's duration | **1 year**, not 12 months of 1 month |
| 4 | Its price | Any price for VAL. For PROD, the real price per storefront |
| 5 | Its localisations | A display name and a description, in English and in French. Apple shows them in the purchase sheet |
| 6 | Family Sharing | **Off**, and leave it off: Apple does not let it be turned off again once on |
| 7 | Introductory and promotional offers | None |
| 8 | Billing grace period (the Subscriptions page, subscription settings) | **On, 16 days**, for all renewals, and in both environments if Apple asks |

The first time, Apple also asks for a review screenshot and notes for the
subscription, and wants it submitted with the app's version. A subscription
that is still "Missing Metadata" is not available to testers: its status must
be at least "Ready to Submit".

Keep `<apple-product-id>` and each app's bundle id (`<ios-bundle-id-val>` for
VAL, `<ios-bundle-id>` for PROD) for steps 7 and 9.

### 3. Create the In-App Purchase key

**[Apple]** Users and Access → Integrations → In-App Purchase. The page shows
the **Issuer ID**, `<apple-iap-issuer-id>`. Generate a key, named for the
environment, such as "Wishlist VAL". Its **Key ID** is `<apple-iap-key-id>`.
Download `SubscriptionKey_<apple-iap-key-id>.p8` straight away: Apple allows
the download once. It is a secret: keep it outside this repository, in your
password manager.

This is neither the App Store Connect API key of the builds nor the Sign in
with Apple key: it is a third, separate key. One key belongs to the whole team
and would work for both servers, but make one for VAL and one for PROD, so
that either can be revoked without the other.

The server needs the file on one line, each line break written `\n`.
**[dev]** On macOS:

```bash
awk 'NF { printf "%s\\n", $0 }' ~/Downloads/SubscriptionKey_<apple-iap-key-id>.p8 | pbcopy
```

On Windows, in PowerShell:

```powershell
(Get-Content $HOME\Downloads\SubscriptionKey_<apple-iap-key-id>.p8) -join '\n' | Set-Clipboard
```

The clipboard now holds the line to paste in steps 7 and 9.

### 4. Set the notification URLs

**[Apple]** Each app → General → App Information → App Store Server
Notifications. Choose **Version 2** for each URL you set.

| App | Production Server URL | Sandbox Server URL |
|---|---|---|
| VAL app | empty | `https://<val-host>/api/billing/apple/notifications` |
| PROD app | `https://<prod-host>/api/billing/apple/notifications` | `https://<prod-host>/api/billing/apple/notifications` |

VAL's app is only ever bought from in Sandbox, so it has no Production URL.
PROD's app has both: real purchases arrive on the Production URL, and App
Review's Sandbox purchases on the Sandbox one. The server accepts the Sandbox
ones only from the demo account of step 6.

Notifications reach the server only once it runs with the variables of steps 7
and 9. Until then Apple retries, and nothing is lost: the app also reports
every purchase itself.

### 5. Create Sandbox testers

**[Apple]** Users and Access → Sandbox → Test Accounts → **+**. Each tester
needs an email address that is not already an Apple Account and that you can
read, such as a plus-address of your own. Never commit it. Choose the
storefront.

**[dev]** On the iPhone with the VAL app from TestFlight, Settings →
Developer → Sandbox Apple Account: sign in as the tester. The Developer menu
appears once the iPhone has run an app installed from Xcode or TestFlight.
Use the tester for nothing but purchases: do not sign in to the iPhone itself
with it.

### 6. Create the App Review demo account

App Review buys Premium to review the PROD app, with Sandbox against the
production server. The reviewer signs in with an account that you give in the
App Review notes, so that account is a Wishlist account on PROD, and the only
one whose Sandbox purchases PROD accepts.

1. **[dev]** On `https://<prod-host>`, create the account for the reviewer,
   with an email address made for it. Never use your own account for it.
2. **[VPS]** Find its id, in `/opt/wishlist`, with the `pg` function of
   [Billing with Stripe](DEPLOYMENT.md#billing-with-stripe), as
   [Admin](DEPLOYMENT.md#admin) does:

   ```bash
   pg <<'SQL'
   select id, created_at from users where email = '<demo-account-address>' order by created_at;
   SQL
   ```

   That id is `<demo-account-id>`. It goes in `APPLE_SANDBOX_ACCOUNT_IDS` in
   step 9. The account's address and password go in App Store Connect's App
   Review Information for the version, never in this repository.

The id stays in the variable for the next review. Empty the variable to accept
no Sandbox purchase on PROD at all, and put it back before the next submission.

### 7. Fill in VAL

**[VPS]** The key is typed at a hidden prompt, so that it stays out of the
shell history, and written with `printf`, not `sed`, which would turn its `\n`
into line breaks. `APPLE_APP_APPLE_ID` does not exist on VAL.

```bash
cd /opt/wishlist-val
grep -c -E '^APPLE_(PRODUCT_ID|BUNDLE_ID|IAP_)' .env                      # 5
sed -i 's|^APPLE_PRODUCT_ID=.*|APPLE_PRODUCT_ID=<apple-product-id>|' .env
sed -i 's|^APPLE_BUNDLE_ID=.*|APPLE_BUNDLE_ID=<ios-bundle-id-val>|' .env
sed -i 's|^APPLE_IAP_ISSUER_ID=.*|APPLE_IAP_ISSUER_ID=<apple-iap-issuer-id>|' .env
sed -i 's|^APPLE_IAP_KEY_ID=.*|APPLE_IAP_KEY_ID=<apple-iap-key-id>|' .env
read -rs IAP_KEY                                   # paste the key's one line, then Enter
sed -i '/^APPLE_IAP_PRIVATE_KEY=/d' .env
printf 'APPLE_IAP_PRIVATE_KEY=%s\n' "$IAP_KEY" >> .env
unset IAP_KEY
grep -c '^APPLE_IAP_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\\n.*\\n-----END PRIVATE KEY-----$' .env   # 1
ls -l .env                                         # -rw-------
docker compose up -d --wait --wait-timeout 300
docker compose logs app | grep 'selling on iPhone is off'                  # nothing
```

A line printed names what is still missing or does not load, never a value.
Use `up -d` after every change to `.env`, as in Part 1. The release's lines
must be in `.env` first ([release
steps](DEPLOYMENT.md#release-specific-steps), "The release with Apple
purchases").

### 8. Test on VAL

**[dev]** On the iPhone, with the VAL app, signed in with a free account on
VAL, and the Sandbox Apple Account of step 5. Sandbox speeds time up: a year
lasts about an hour there, for a few renewals only (Apple's Sandbox table), so
each result below arrives within minutes or the hour. Check each one in the
app and in the admin panel ([step 10](#10-what-the-admin-panel-shows)).

1. **Purchase.** The plan screen shows the subscription's name, length and
   price, the renewal disclosure, the terms and privacy links, and Restore
   purchases. Buy it. Premium appears within seconds and no list limit
   applies. The plan screen offers no second purchase. On the web, signed in
   with the same account, Premium is there too and checkout is refused.
2. **Renewal.** Wait for the first Sandbox renewal. Premium stays, and the end
   date moves forward.
3. **Cancellation.** On the iPhone, Settings → Apple Account → Subscriptions,
   cancel the Sandbox subscription. Premium stays until the end of the paid
   period, then ends. The plan screen's Manage button opens that same page.
4. **Billing retry and grace.** Make a renewal fail: the Sandbox Apple Account
   page on the iPhone (Settings → Developer → Sandbox Apple Account →
   Manage) has options for interrupting purchases and for the renewal rate,
   and App Store Connect's tester page may offer more. Which option makes a
   renewal fail was not checked. While Apple is in its grace period, Premium
   stays and the admin panel reads `past_due`; once the grace period is over,
   Premium ends.
5. **Refund.** Ask for Apple's Sandbox test refund of the transaction (Apple's
   documentation on testing refund requests says where: the option depends on
   the tool, and was not checked). Premium ends at once. Buying again grants
   it again, with no manual step.
6. **Restore.** With the same Wishlist account, delete the app and install it
   again, or sign in on another iPhone. Premium is back for the account
   already, since the server holds it: Restore purchases then finds the
   subscription again without a second charge. Signed in with a *different*
   Wishlist account, Restore is refused, since the purchase belongs to the
   first.
7. **Deletion.** With a renewing subscription, the account deletion dialog
   warns that Apple's subscription is not cancelled by it, with a link to
   Apple's subscriptions page. Delete the test account at the end.

In the server's logs, `docker compose logs app | grep 'apple:'` lists what
Apple sent and what was refused, by transaction id. It never shows a key or a
signed payload.

### 9. Fill in PROD

**[VPS]** Only after the test above, and once the PROD app is in App Store
Connect with its subscription (step 2) and its URLs (step 4). The same lines as
[step 7](#7-fill-in-val), in `/opt/wishlist` with the PROD app's bundle id,
`<ios-bundle-id>`, and PROD's own key, plus two variables. `<apple-app-apple-id>`
is the PROD app's **Apple ID** in App Store Connect (App Information), digits
only: the server needs it to check Apple's production notifications.

```bash
cd /opt/wishlist
grep -c -E '^APPLE_(PRODUCT_ID|BUNDLE_ID|APP_APPLE_ID|IAP_|SANDBOX_ACCOUNT_IDS)' .env   # 7
sed -i 's|^APPLE_APP_APPLE_ID=.*|APPLE_APP_APPLE_ID=<apple-app-apple-id>|' .env
sed -i 's|^APPLE_SANDBOX_ACCOUNT_IDS=.*|APPLE_SANDBOX_ACCOUNT_IDS=<demo-account-id>|' .env
```

Then the five lines of step 7 (product, bundle, issuer, key id and the key), and
its `up -d` and `selling on iPhone is off` lines. That log line also names a
missing or non-numeric `APPLE_APP_APPLE_ID`.

Then make one real purchase on the production app with your own Apple Account,
check Premium, and refund it from Apple's [report a
problem](https://reportaproblem.apple.com) page.

### 10. What the admin panel shows

The Apple subscription has its own block in the user's row, beside Stripe's:
its status (`active`; `past_due` while Apple retries the payment inside the
grace period; `canceling` when it is set to stop; `ended`), its start, and its
renewal or end date. A manual Premium shows apart. Neither the panel nor the
server can cancel an Apple subscription: only its owner can, in their Apple
settings. The panel's deletion dialog warns the admin when the person still
has a renewing one, and the deletion goes ahead, as for the person's own. The
server logs it, by ids only.

## Running it day to day

- **A refund or a withdrawal:** in Stripe, refund the payment, then cancel the
  subscription immediately. The person becomes free and loses nothing.
- **A new price:** create a new one in Stripe (a price cannot be edited), then
  change `STRIPE_PRICE_ID` and `BILLING_PRICE_AMOUNT` together and run `up -d`.
  Existing subscribers stay on the old price, and their events log
  `has another price`, which is expected.
- **An Apple refund:** Apple decides it, and the person asks Apple. The
  server ends Premium when Apple's notification arrives. There is nothing to do
  here, and nothing to refund by hand.
- **Stop selling:** clear `STRIPE_PRICE_ID` or `BILLING_PRICE_AMOUNT`. Sales and
  limits stop, and existing subscribers carry on. **Never clear the two secrets
  while a subscription runs**: renewals would go unrecorded, and its owner could
  not delete their account.

## If something goes wrong

Logs are in `docker compose logs app`, in the environment's directory.

| What you see | What it means |
|---|---|
| `billing is not selling; missing or invalid: X` | Set X. `STRIPE_SECRET_KEY` here can also mean a test key on PROD or a live key on VAL |
| `the price at Stripe does not match STRIPE_PRICE_ID` | The price is missing, archived, not yearly, not tax-inclusive, or from another account or mode |
| `the price at Stripe does not match BILLING_PRICE_AMOUNT` (or `_CURRENCY`) | The variable differs from the Stripe price |
| `Stripe refused checkout because the account has no terms of service URL` | Row 2 of step 4 |
| The plan page's Manage button fails | Most likely the portal was never saved (row 3 of step 4) |
| Paid, but Premium does not appear | Open the webhook's event deliveries in Stripe. A 400 with `failed its signature check` in the logs is a wrong `STRIPE_WEBHOOK_SECRET`; a 404 means the gateway is not configured |
| `entitlement past its grace`, or the server was down for days | [After a webhook delivery gap](DEPLOYMENT.md#after-a-webhook-delivery-gap) |
| `selling on iPhone is off; missing or invalid: X` | Set X. `APPLE_IAP_PRIVATE_KEY` here also means a key that does not load: it must be one line, each line break written `\n` |
| `apple: a notification failed its check` | If every notification does: `APPLE_BUNDLE_ID`, `APPLE_APP_APPLE_ID` (PROD) or the URL's environment in [step 4 of Part 3](#4-set-the-notification-urls) is wrong |
| `apple: Sandbox transaction … refused for account …` | A Sandbox purchase on PROD from an account that is not in `APPLE_SANDBOX_ACCOUNT_IDS`. Expected for testers; for the review's demo account, see [step 6](#6-create-the-app-review-demo-account) |
| Bought on iPhone, but Premium does not appear | `docker compose logs app \| grep 'apple:'`. A transaction `of another product` is a wrong `APPLE_PRODUCT_ID`; `names another account` is a purchase made under a different Wishlist account than the signed-in one |
| An account deletion refused with 409 | [Account deletion refused with 409](DEPLOYMENT.md#account-deletion-refused-with-409) |
