# Review ledger — Reserving

Subject: docs/plans/RESERVING_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 ("implement
this and the reserving roadmap all silently"), the orchestrator approved the
triaged table after enforcing the floors, and answered envelope questions with
its recommendation.

## Round 1 — 2026-11-08, reviewed at 669bcc0

Envelope questions, answered by the orchestrator: (1) U7 derives its endpoint
list from the OpenAPI document, so the gift-images routes are covered.
(2) A giver may still mark bought their own claim of a passed occasion while
it exists; every other write on a passed occasion stays refused (D8, NEEDS).

### R1-1 — Deleting an occasion while an invitee reserves in it fails with a check violation
- Trigger: a "for me" owner deletes an occasion while an invitee reserves in it → the delete waits on the reserver's lock, then `SET NULL` meets the new unbought claim and the CHECK fails → 500 instead of 204, an answer only activity can cause
- Scores: trigger=plausible (triager: was concrete), impact=security, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D3, floor F1)
- Override: —
- Outcome: fixed (in plan: D11, U5 Do 4 and Do 6)

### R1-2 — U3's scenario asks for two pledges where the "for me" list has one giver
- Trigger: the U3 implementer cannot add two pledges in the "for me" list's second occasion
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U3 Do 2)

### R1-3 — U5's account-deletion tests use a fixed 2026-12-25 occasion date
- Trigger: CI after 2026-12-26 12:00 UTC → 409 `passed` → red suite
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U5 Do 7)
