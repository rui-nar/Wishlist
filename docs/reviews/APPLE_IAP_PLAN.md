# Review ledger — Premium through Apple's in-app purchase

Subject: docs/plans/APPLE_IAP_PLAN.md
Envelope: the plan's `## Review envelope`, with PREMIUM_PLAN's and REVIEW.md defaults

Decisions approved by the owner ("as recommended", 2026-11-11), with the
envelope questions answered as recommended: Sandbox on PROD only for listed
accounts, TestFlight testers on the VAL app; Premium through Apple's billing
grace period only; a charge after a warned deletion is accepted, and the
admin sees Apple subscriptions apart like Stripe's; limits only while Stripe
sells.

## Round 1 — 2026-11-11, reviewed at the plan's first draft (uncommitted)

### R1-1 — Sandbox on PROD gives testers Premium for free
- Trigger: a TestFlight tester on a PROD build buys → a free Sandbox transaction is honoured on PROD.
- Scores: trigger=concrete, impact=security, detect=logged, later=cheap, fix=M/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D6)

### R1-2 — A notification can credit a resubscription to the wrong account
- Trigger: one Apple ID, two accounts; a resubscription under B → a notification resolved from the stored row writes it back to A.
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D4)

### R1-3 — The deletion warning has no reliable signal
- Trigger: an Apple subscriber with a longer other row, or in retry, or deleted by the admin → no warning, Apple keeps charging.
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=expensive, fix=M/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D9: `apple_renewing`, admin block)

### R1-4 — `offer` undefined when one store sells; limits for users who cannot pay
- Trigger: Apple sells, Stripe does not, limits on → clients fail to parse, or web users are blocked with no way to pay.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=expensive, fix=M/shared, confidence=verified
- Decision: Fix now (D5)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D7: `apple_offer`, limits on Stripe only)

### R1-5 — Premium would end 3 days into a card failure
- Trigger: a renewal fails → `period_end` is the past `expiresDate` → Premium ends at day 3, with the lost-events warning.
- Scores: trigger=concrete, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D5)

### R1-6 — A deleted account's subscription is unusable by the same person's new account
- Trigger: delete account A with a running subscription, sign up as B, restore → 409 `other_account`.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a 409 `other_account` naming no existing account is logged on PROD, or such a support request arrives
- Guard: —
- Override: —
- Outcome: open

### R1-7 — No manual repair after a long notification gap
- Trigger: PROD unreachable across a renewal past Apple's retries → Premium ends for a charged customer.
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: "entitlement past its grace … source=apple" is logged on PROD, or PROD is down longer than Apple's retries
- Guard: —
- Override: —
- Outcome: open

### R1-8 — The iPhone account screen hides the plan entry
- Trigger: U2 keeps to its scope → See Premium, Manage and legal links stay web-only.
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan U2 Scope)

## Round 2 — 2026-11-11, unit review of U1, reviewed at 3556ba2

### R2-1 — A report can take a subscription back from the account the stored row names
- Trigger: accounts A and B on one Apple ID, the row on B, the latest transaction without a token; A restores → the row moves to A, B drops to Free silently.
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (a2fc11d)

### R2-2 — The admin row has no signal that Apple may still charge
- Trigger: a canceling in-force row hides a second row in billing retry → the admin deletes with no warning.
- Scores: trigger=plausible, impact=silent-wrong, detect=logged, later=cheap, fix=S/local, confidence=verified (corrected from inferred)
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (a2fc11d)

### R2-3 — On PROD a Sandbox notification never reaches the Sandbox verifier
- Trigger: App Review buys with the demo account → Sandbox notifications answered 400, retried, with a misleading configuration warning.
- Scores: trigger=concrete, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (a2fc11d)

## Round 3 — 2026-11-11, integrated review, reviewed at 061c9cc

### IAP-R3-1 — The Apple-purchases release step has "\r" for its line continuation
- Trigger: the owner pastes the block → the guard is broken and a second run appends empty APPLE_* lines.
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (9f17ab7)

### IAP-R3-2 — The phone apps cannot read the plan from a rolled-back server
- Trigger: PROD rolled back one release with phone builds installed → `apple_renewing` and `google_renewing` missing, the strict cast throws.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=expensive, fix=S/local, confidence=verified
- Decision: Fix now (D5)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (9f17ab7)

### IAP-R3-3 — An unconfirmed purchase is retried at the next start, not on reopening the page
- Trigger: the server cannot confirm with Apple → the message promises a retry on reopening the page.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: PROD logs a store purchase that could not be confirmed, a user reports one still pending after reopening the page, or those strings are edited for another reason
- Guard: —
- Override: —
- Outcome: open

### IAP-R3-4 — The runbook's real purchase on the PROD app cannot be made from TestFlight
- Trigger: the owner follows Part 3 step 9 with the TestFlight PROD build → a Sandbox purchase refused with 409.
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (9f17ab7)

## Delivery

Delivered under the owner's standing instruction of 2026-11-11, with
IOS_APP_PLAN and ANDROID_RELEASE_PLAN on one branch.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Server: the Apple translator and its routes | Opus | S5 | 1 (+ review fixes) | X3: tests/admin | yes | R1-1–R1-5, R2-1–R2-3 |
| U2 | Client: buying on iPhone | Opus | S5 | 1 | — | yes | R1-8, IAP-R3-2, IAP-R3-3 |
| U3 | Runbook | Sonnet | — | 1 | — | yes | IAP-R3-1, IAP-R3-4 |
| F1 | The store listener from launch; ApiClient.post with a body | Opus | S5 | 1 | — | yes | — |
| F2 | No Stripe link in the mobile apps (store rules) | Opus | S5 | 1 | — | yes | — |
| F3 | Integrated review fixes | Opus | S5 | 1 | — | yes | IOS-R3-1, IAP-R3-1, IAP-R3-2, IAP-R3-4 |
