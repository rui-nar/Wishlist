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

## Running it day to day

- **A refund or a withdrawal:** in Stripe, refund the payment, then cancel the
  subscription immediately. The person becomes free and loses nothing.
- **A new price:** create a new one in Stripe (a price cannot be edited), then
  change `STRIPE_PRICE_ID` and `BILLING_PRICE_AMOUNT` together and run `up -d`.
  Existing subscribers stay on the old price, and their events log
  `has another price`, which is expected.
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
| An account deletion refused with 409 | [Account deletion refused with 409](DEPLOYMENT.md#account-deletion-refused-with-409) |
