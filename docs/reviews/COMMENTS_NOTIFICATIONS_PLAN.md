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

## Round 5 — 2026-11-10, unit review of U5, reviewed at 27a75be

No findings. Envelope question, answered by the orchestrator: the unsubscribe
token reaches uvicorn's access log, because RFC 8058 puts it in the URL.
Accepted and recorded as the one exception in the plan's Conventions: the
token can only turn one account's email off, the account screen turns it back
on, and only the admin reads that log. Unlike a join token, it grants nothing.

## Round 6 — 2026-11-10, unit review of U7, reviewed at 3f9629f

### R6-1 — The sweep and a giver's release lock the same orphaned claims in different orders
- Trigger: an owner deletes two gifts an invitee holds → the sweep's unordered `DELETE FROM gift_claims` locks those rows in scan order while the invitee leaves, is removed or deletes their account → `release_activity` locks them in `gift_id` order → deadlock, and when the request is the victim, a 500
- Scores: trigger=plausible, impact=degraded-ux (triager: was wrong-visible), detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Defer (D10)
- Revisit when: a PostgreSQL deadlock involving `gift_claims` appears in the logs
- Override: orchestrator, under the standing instruction: Fix now — the fix is inside the sweep and touches no request path; a 500 on account deletion is what RESERVING R9-3 and hidden gifts R3-1 were fixed for
- Outcome: fixed (c9bf53a)

### R6-2 — A digest row deleted during a refused send aborts the rest of the run
- Trigger: an account or occasion is deleted while Brevo answers 429 or 5xx for that digest → `_requeue`'s `get_one` raises → the remaining digests of the run wait for the next one, 15 s later; nothing is sent twice
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: `notifications: run failed (NoResultFound)` recurs in the logs, or the run interval grows
- Override: —
- Outcome: open

### R6-3 — `claimed_at` is the run's start time
- Trigger: a run lasting over 10 minutes during a deploy's two-process overlap → the other process's `_fail_stale` marks in-flight digests `failed/unknown` → one email per affected digest is lost or mis-recorded; no duplicates
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a worker run lasts over 10 minutes, a digest ends `failed/unknown` while its process was alive, `SEND_BATCH` or the mailer timeouts increase, or several app processes run permanently
- Override: —
- Outcome: open

## Round 7 — 2026-11-10, integrated review, reviewed at f7b04fd

### R7-1 — Reservations and pledges made before this release never follow their gift
- Trigger: an invitee reserved or pledged before the deploy → after it another giver comments → the holder gets no email and sees "Follow" on a gift they hold
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=expensive (triager: was cheap; a later repair is a further data migration), fix=S/local, confidence=verified
- Decision: Fix now (D5, floor F4)
- Override: —
- Outcome: fixed (5d012e9)

### R7-2 — Seeding VAL from PROD carries PROD's pending notifications
- Trigger: PROD has a pending event or digest when the nightly dump runs, the admin later seeds VAL from it, and email is configured on VAL → VAL's worker sends the allow-listed owner a second copy of any digest addressed to them, with VAL links
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: VAL sends an email for activity that happened on PROD, the VAL allow-list grows beyond the owner, or dumps or seeds become frequent enough that pending rows are routinely carried over
- Override: —
- Outcome: open

## Delivery

Orchestrated under the owner's standing instruction of 2026-11-09, after the
hidden gifts plan on the same branch (`feat/hidden-gifts-comments`). Units of a
multi-unit wave ran in worktrees (W2). Server checks ran in a detached Linux
container on the dev Docker network, because Windows Application Control blocks
the host venv's compiled modules.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Comment threads and following | Opus | S4 | 1 | — | yes | — |
| U2 | Client: thread and follow toggle | Opus | S5 | 1 | X3 (bodyless `put` in `ApiClient`) | yes | — |
| U3 | Outbox, auto-follow, gift deletion without cascades | Opus | S4 | 1 | — | yes | R1-1 to R1-6, R2-1, R2-2, R4-1 |
| U4 | Client: email switch, language, unsubscribe page, deep links | Opus | S5 | 1 | — | yes | — |
| U5 | Preferences and the unsubscribe route | Opus | S5 | 1 | — | yes | — |
| U6 | The Brevo mailer and email content | Opus | S5 | 1 | — | yes | — |
| U7 | The notification worker | Opus | S5 | 1 | X3 (`mailer.py`, empty sender name) | yes | R6-1, R6-2, R6-3 |
| U8 | Environment variables and the owner's steps | Opus | S5 | 1 | — | yes | — |
| U9 | No notification reaches the recipient, end to end | Opus | S5 | 1 | — | yes | — |
| F2 | Claim holders follow their gifts on upgrade | Opus | S4 | 1 | — | yes | R7-1 |

Deferred: R6-2, R6-3, R7-2, with their revisit conditions above.
