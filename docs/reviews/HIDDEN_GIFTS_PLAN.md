# Review ledger — Hidden gifts and received marking

Subject: docs/plans/HIDDEN_GIFTS_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-09 ("go with
hidden gifts & comments & notifications. same thing, do it all silently"),
the orchestrator approves the triaged table after enforcing the floors, and
answers envelope questions with its recommendation.

## Round 1 — 2026-11-09, reviewed at 0a7111d

Envelope questions, answered by the orchestrator: (1) moving a date earlier
keeps the later reveal date; the client shows, identically on every
occasion, a warning when a date is moved earlier, so a typo can be noticed
before it is saved. (2) An owner's removal of an invitee also deletes that
person's unbought hidden gifts (the owner's remedy against an abusive
invitee, per-row work the RESERVING envelope accepts for removal); leaving
on one's own keeps them. (3) The rollback runbook states the window in
which `latest_date` is not maintained, instead of claiming no leak.

### R1-1 — A received hidden gift leaves "Received" when its occasion's date moves later, and is deleted with the occasion
- Trigger: owner marks a revealed hidden gift received → moves the occasion's date to next year → the gift leaves Received → owner deletes the occasion → the received gift is deleted
- Scores: trigger=plausible, impact=data-loss, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3, floor F2)
- Override: —
- Outcome: open

### R1-2 — Cascades from gifts that COMMENTS_NOTIFICATIONS_PLAN D13 removes
- Trigger: the comments delivery drops `gift_claims.gift_id → gifts` → D6, D9, D15 and the U3/U5 tests describe cascades that no longer exist
- Scores: trigger=concrete, impact=maintainability, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: open

### R1-3 — Dismissing or editing a revealed hidden gift emails its buyer, while keep and received do not
- Trigger: the recipient dismisses (DELETE) or edits (PATCH) a revealed hidden gift → `gift_deleted`/`gift_changed` reaches the giver who bought it
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/shared, confidence=verified (triager: was inferred)
- Decision: Defer (D8)
- Override: orchestrator, under the standing instruction: Fix now — the product question is decided (NEEDS, Notifications: a revealed gift's dismissal or edit notifies nobody, like keep and received); fixed in COMMENTS_NOTIFICATIONS_PLAN (whether a gift is revealed is the owner's own data, so the condition keeps D12)
- Outcome: open

## Round 2 — 2026-11-09, reviewed at c05577d

Envelope question, answered by the orchestrator: when an owner's removal of
an author deletes their hidden gift, its remaining participants are notified
that the gift was removed (recorded in NEEDS, Notifications).

### R2-1 — Put back on a received hidden gift whose reveal date moved later loses it
- Trigger: owner marks a revealed hidden gift received → moves the occasion's date later → puts the gift back → it leaves every owner view → deleting the occasion deletes it
- Scores: trigger=plausible, impact=data-loss, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3, floor F2)
- Override: —
- Outcome: open

### R2-2 — Removal deletes a hidden gift right after `participants_left` listed it
- Trigger: owner removes an invitee who wrote an unbought hidden group gift others pledged on → the gift is deleted in the same transaction → the fan-out finds no gift row; pledgers get nothing, or the whole event fails
- Scores: trigger=concrete (triager: was plausible), impact=degraded-ux, detect=silent, later=cheap, fix=S/shared, confidence=verified
- Decision: Defer (D8)
- Override: orchestrator, under the standing instruction: Fix now — the notification is now a NEEDS requirement, and a failing fan-out would also drop the notifications about the leaver's other group gifts
- Outcome: open

## Round 3 — 2026-11-09, unit review of U1, reviewed at 29ec85f

### R3-1 — Dismissing a revealed hidden gift can deadlock with its author's account deletion
- Trigger: the author of a hidden gift who bought it deletes their account while the recipient dismisses it → `delete_gift` holds the gift and waits on the claim; `delete_me` holds the claim (release) and waits on the gift (`hidden_by` SET NULL) → deadlock, one 500
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/shared, confidence=verified
- Decision: Defer (D10)
- Override: orchestrator, under the standing instruction: Fix now — D10's lock order (user → occasions → gifts → claims) is a stated invariant of the plan and the fix is one helper in `lifecycle.py`; account deletion answering 500 is what RESERVING R9-3 was fixed for
- Outcome: open
