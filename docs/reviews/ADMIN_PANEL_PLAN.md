# Review ledger — Admin panel

Subject: docs/plans/ADMIN_PANEL_PLAN.md
Envelope: the plan's `## Review envelope`, with REVIEW.md defaults

Decisions approved as triaged, floors enforced, under the owner's standing
instruction of 2026-11-10.

## Round 1 — 2026-11-10, reviewed at the plan's first draft (uncommitted)

Envelope questions, answered with the recommendation: the NEEDS entry lands
with the plan; a pending upload and a hidden gift's photo are invitee
activity, so per-user photo figures count only images on gifts the recipient
can see, with no instance-wide total.

### R1-1 — Photo figures per uploader expose a giver's hidden-gift photo
- Trigger: a friend adds a hidden gift with a photo to the admin's list → the admin sees the friend's photo count and bytes rise.
- Scores: trigger=concrete, impact=security, detect=silent, later=cheap, fix=M/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D7, U2 Acceptance)

### R1-2 — The admin routes are discoverable through the schema and 405s
- Trigger: anyone reads `/openapi.json` or `/docs`, or sends another method to an admin path → they learn the panel exists.
- Scores: trigger=concrete, impact=security, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D2, U1 Scope)

### R1-3 — Hiding Manage for a manual grant strands a Stripe subscriber
- Trigger: the admin grants manual Premium to a Stripe subscriber → the plan screen would hide Manage, and Stripe keeps billing.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: —
- Guard: —
- Override: orchestrator: Fix now — the plan's own wording prescribed the bug, and the fix is one sentence of D8
- Outcome: fixed (plan D8)

### R1-4 — A backfill inside the purge never runs on VAL
- Trigger: the owner opens the panel on VAL, where `BACKUP_DIR` is unset → every older photo says "measuring" for ever.
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D7, U1 Scope)

### R1-5 — Deleting an account already gone signs the admin out
- Trigger: a user deletes their own account while the admin's page is open → the admin's deletion gets 401 and the client signs the admin out.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: an admin is signed out by a deletion other than through `reauth_required`, or a second admin is added
- Guard: —
- Override: —
- Outcome: open

### R1-6 — An expired manual grant logs the lost-events warning on every read
- Trigger: a manual grant passes its end with status active → every plan read logs "past its grace", whose runbook answer is to resend Stripe events.
- Scores: trigger=concrete, impact=maintainability, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D8, U1 Scope)

## Round 2 — 2026-11-11, unit review of U1, reviewed at 95f30e6

### R2-1 — The schema is hidden in production only, and VAL is public
- Trigger: anyone fetches `/openapi.json` or `/docs` on VAL once the routes exist → they learn the panel exists. New evidence for R1-2.
- Scores: trigger=concrete, impact=security, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (8c3f279)

### R2-2 — The backfill's lock comment claims attaches never wait
- Trigger: a maintainer relies on the comment; in fact an attach's `FOR UPDATE` waits for one batch.
- Scores: trigger=concrete (corrected from plausible: the false comment needs no race), impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (8c3f279)

### R2-3 — A malformed `ADMIN_USER_IDS` entry is dropped with no log
- Trigger: the owner mistypes the id, restarts, and sees no admin and no reason.
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (8c3f279)

## Round 3 — 2026-11-11, unit review of U2, reviewed at 60c4098

### R3-1 — `lock_for_deletion` left behind, unused, still named as the deletion's lock
- Trigger: a maintainer edits `lock_for_deletion` to change the deletion's locking → nothing changes, since both routes use `deletion._lock`.
- Scores: trigger=concrete, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (7ecb4e1)

### R3-2 — An admin deletion holds a session-row write across the Stripe calls
- Trigger: the admin, idle over an hour, deletes a Stripe subscriber while Stripe is slow, and sends another request with the same token → that request waits until the deletion commits.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=M/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: an admin request is seen waiting on a lock held by an admin deletion, a second admin is added, or the admin client sends requests in parallel during a deletion
- Guard: —
- Override: —
- Outcome: open
