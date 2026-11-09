# Review ledger — Comments and notifications

Subject: docs/plans/COMMENTS_NOTIFICATIONS_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-09 ("go with
hidden gifts & comments & notifications. same thing, do it all silently"),
the orchestrator approves the triaged table after enforcing the floors, and
answers envelope questions with its recommendation.

## Round 1 — 2026-11-09, reviewed at 0a7111d

Envelope question, answered by the orchestrator: for member removal the
floor is exactly one event row plus the per-claim release work RESERVING
already accepted; identical statements are required only of the owner's
gift edit and deletion.

### R1-1 — Dropping the claims FK makes the previous release 500 on list and account deletion after a rollback
- Trigger: admin rolls PROD back to the previous release on this schema → an owner deletes a gift with an unbought reservation (the claim is orphaned) → later deletes the list or account → `delete_gift_claims` misses the orphan, `SET NULL` meets `ck_gift_claims_occasion_id` → 500
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=expensive, fix=S/local, confidence=verified
- Decision: Fix now (D5, floor F4)
- Override: —
- Outcome: fixed (in plan)

### R1-2 — Fan-out undefined for a claim bought in a deleted occasion; failing events retried forever
- Trigger: a gift is bought, the owner deletes the passed occasion (claim's occasion set null), then edits or deletes the gift → the fan-out has no occasion for `notifications.occasion_id` → the event fails and is retried with no cap, and the buyer is never told
- Scores: trigger=concrete, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

### R1-3 — Expired unbought claims are notified of owner edits and deletions
- Trigger: an invitee reserved and never bought, the occasion passed, the claim row stays → the owner edits the gift → the ex-reserver is emailed about a reservation that ended
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan)

### R1-4 — Deleting a received gift emails its buyers
- Trigger: owner marks a bought gift received, later deletes it from Received → `gift_deleted` fans out to the buyers, though received is not notified
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

### R1-5 — An owner of a "for someone else" list is emailed about their own edits
- Trigger: the owner reserved a gift of their list as a giver, then edits it → `gift_changed` targets them too
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

### R1-6 — Contract mismatch with HIDDEN_GIFTS_PLAN on cascades from gifts
- Trigger: U3 drops `gift_claims.gift_id → gifts` → the hidden-gifts tests asserting synchronous cascade on keep, dismiss and delete fail; HIDDEN D6, D7, D9, D15 and this plan's Conventions describe behaviour the code no longer has
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

## Round 2 — 2026-11-09, reviewed at c05577d

### R2-1 — `participants_left` notifies about expired group gifts
- Trigger: a member of a passed occasion's unbought group gift leaves or deletes their account → the remaining participants are emailed about a group gift that already ended
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan)

### R2-2 — U3 keeps in the ORM a check constraint the migration drops
- Trigger: the U3 implementer follows Scope ("drop the FK only") → `GiftClaim` still declares `ck_gift_claims_occasion_id`; `alembic check` does not notice
- Scores: trigger=concrete, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

## Round 3 — 2026-11-09, unit review of U1, reviewed at e554e46

No findings.

## Round 4 — 2026-11-09, unit review of U3, reviewed at 19bba44

### R4-1 — Plan D11 still specifies the two-column unique key on `notifications`
- Trigger: the worker unit's implementer follows D11 as written → re-adds the two-column constraint or builds the fan-out around it → someone sharing two group gifts with a leaver is told of only one
- Scores: trigger=concrete, impact=maintainability, detect=silent (triager: was user-visible), later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D11)
