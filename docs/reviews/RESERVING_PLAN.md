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

## Round 2 — 2026-11-08, unit review of U1 (DELIVERY.md §5 point 3), reviewed at 950031c

No findings. Envelope questions, answered by the orchestrator under the
standing instruction:
1. U1 without U5 gives a "for me" owner a 500 when deleting an occasion (or a
   list or account) holding an unbought claim. Intended: the branch is not
   released or tagged for VAL until U5 lands; no stopgap.
2. The activity read locked the occasion `FOR SHARE`, so a recipient's
   occasion edit could wait on an invitee's read. Not covered by the noise
   exclusion when no lock is needed: the read no longer locks (writes keep
   D7's locks), with a test.
3. An owner's image change locked the gift `FOR UPDATE`, which waits on a
   giver's `FOR KEY SHARE`. Asked to change it to `FOR NO KEY UPDATE`; the
   implementer showed (probe) that changing the unique `gifts.image_id` is a
   key update whatever lock is requested, and the claim's foreign key takes
   `FOR KEY SHARE` anyway. Decision (orchestrator): accept the
   millisecond wait as noise, like an owner deleting a gift being reserved;
   no schema change. D7 amended. The read-lock change (2) is ee275d8.

## Round 3 — 2026-11-08, unit review of U4 (DELIVERY.md §5 point 3), reviewed at fcb1133

Envelope answer (orchestrator, standing instruction): the D8 exception stays;
`OccasionClaims` is extended so a giver sees their own unbought claims of a
passed occasion (as reserved or group with `mine`, flagged expired, never
counted as taken elsewhere), and the client offers Mark as bought on them when
the occasion has passed. The recipient-blindness tests (U7) must keep passing.

### R3-1 — Marking one's own claim bought after the date is unreachable from the client
- Trigger: an invitee who handed a reserved gift over opens the occasion after 12:00 UTC the next day → their claim is not in the read and no action is offered → the gift is free elsewhere and can be bought twice
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=M/shared, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: open

### R3-2 — Leaving the screen during a write shows a failure for a write that succeeded
- Trigger: back pressed while a reserve is in flight → the reload runs on an unmounted state and throws → generic failure snackbar
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Defer (D10)
- Revisit when: a giver reports an error after a write that went through, or any change to `_act` or `_reloadClaims` (then capture l10n before the await). R3-3's fix changes `_act`, so it is fixed with it.
- Override: —
- Outcome: open

### R3-3 — Nothing shows an action in flight, and taps are swallowed silently
- Trigger: a slow write → the user taps again → nothing happens, no feedback
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: open
