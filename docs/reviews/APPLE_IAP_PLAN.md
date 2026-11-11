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
