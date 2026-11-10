# Review ledger — Premium and the paywall

Subject: docs/plans/PREMIUM_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-10 ("start with
the following package of features related to the paywall. do it silently"),
the orchestrator approves the triaged table after enforcing the floors, and
answers envelope questions with its recommendation.

## Round 1 — 2026-11-10, reviewed at b4a32b6

Envelope question, answered by the orchestrator: activity on an already
revealed gift is outside the surprise for waits, so `keep`'s own wait on a
giver's `FOR KEY SHARE` (accepted by HIDDEN_GIFTS_PLAN D10) stays accepted.
R1-1 remains a defect only for the wait it passes on to `add_gift`.

### R1-1 — `add_gift` can wait on a giver through the advisory lock a concurrent keep holds
- Trigger: a giver comments on or pledges to a revealed gift while its owner keeps it and an owner adds a gift to the same list → keep holds the advisory lock and blocks on the gift → the add blocks on the advisory lock
- Scores: trigger=plausible, impact=security, detect=silent, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D3, floor F1)
- Override: —
- Outcome: fixed (in plan)

### R1-2 — Webhook, portal and account deletion are gated on being able to sell
- Trigger: the owner withdraws the offer or clears any selling setting → the webhook answers 404 → Stripe drops events after its retries → a renewal paid in that window loses Premium silently, and every subscriber's account deletion answers 409
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=M/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D3, floor F3)
- Override: —
- Outcome: fixed (in plan)

### R1-3 — No way back after a webhook delivery window is missed
- Trigger: the webhook is unreachable across a renewal for longer than Stripe's retries → the paying subscriber becomes free at `period_end` + 3 days until the next event, up to a year later
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D3, floor F3)
- Override: —
- Outcome: fixed (in plan)

### R1-4 — `past_due` can keep Premium for a whole unpaid period
- Trigger: a card declines at renewal, and Stripe's "if all retries fail" setting leaves the subscription as it is → Premium persists up to a year unpaid
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D3, floor F3)
- Override: —
- Outcome: fixed (in plan)

### R1-5 — Account deletion when the customer was deleted at Stripe
- Trigger: the customer is deleted by hand in the Stripe dashboard → `cancel_all` gets `resource_missing` → the deletion is unspecified and retries fail
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Defer (D10): the plan's own flow keeps customers, and proceeding on `resource_missing` is unsafe, since a key for another Stripe account answers the same
- Revisit when: a `DELETE /api/me` fails on `MissingAtStripe`, or a procedure starts deleting Stripe customers
- Override: —
- Outcome: open

## Round 2 — 2026-11-10, reviewed at a678d55

### R2-1 — "Clear any selling variable" also breaks the portal when that variable is `PUBLIC_BASE_URL`
- Trigger: the owner clears `PUBLIC_BASE_URL` to withdraw the offer → subscribers lose Manage subscription, and share and email links break too
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Override: orchestrator, under the standing instruction: Fix now — the revisit condition holds, because U3 is about to write this runbook; the fix is naming the variables
- Outcome: fixed (in plan: D9, U3 Do 1)

### R2-2 — No recovery step for a canceled subscription whose lost event is past Stripe's 30 days
- Trigger: a cancellation's final event is lost during a gap and nobody reads the status for 30 days → the event cannot be resent → the WARNING repeats at each read of that user; Premium is not wrongly granted
- Scores: trigger=plausible, impact=maintainability, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the WARNING is traced to such a subscription, or the repeated line hides other lapses
- Override: —
- Outcome: open

## Round 3 — 2026-11-10, unit review of U1, reviewed at 34e809b

### R3-1 — A granting row with a null `period_end` gives nothing and is never logged
- Trigger: Stripe answers with an active subscription and no `current_period_end` on the subscription or its items, or a future translator bug stores none → the row grants nothing, and the lapse warning never reports it
- Scores: trigger=theoretical (triager: was plausible), impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D4)
- Guard: `warn_if_lapsed` logs a separate fixed WARNING for a granting row with no period end, with a test; who gets premium is unchanged
- Override: —
- Outcome: guard added (b7d10ea)

## Round 4 — 2026-11-10, unit review of U4, reviewed at 326ce30

No findings. Envelope question, answered by the orchestrator: a giver-held lock
whose duration is bounded by the server's own rollback of an immediately
rejected request is not a wait the surprise forbids. This is the one case
known: keep's insert checks the image foreign key while a giver's refused
re-attach of the same image holds it `FOR UPDATE`. No actor can prolong it,
and no owner could observe it.
