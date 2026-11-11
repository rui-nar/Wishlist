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

## Round 4 — 2026-11-11, integrated review, reviewed at 48f631a

### R4-1 — The branch predates the introduction screens on master
- Trigger: merging the branch as cut would drop or conflict with the introduction screens, untested together with the admin panel.
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=M/shared, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (1f1491f: master merged, both kept; client analyze, 862 tests and 154 goldens pass on the result)

### R4-2 — A manual grant outlasting a Stripe subscription hides its renewal and failed-payment lines
- Trigger: the admin grants Premium to a Stripe payer → their plan page shows only the grant, while Stripe keeps charging or dunning.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a manual grant is in force alongside an active or past_due Stripe subscription, a user asks about a charge while their plan says "granted", or grants to paying users become routine
- Guard: —
- Override: —
- Outcome: open

### R4-3 — A failed `/api/me` read after sign-in silently hides the admin entry
- Trigger: the owner signs in and the one `/api/me` read fails → no admin entry, nothing logged, and the runbook points at the configuration.
- Scores: trigger=plausible, impact=degraded-ux, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D9)
- Revisit when: —
- Guard: a console log of the failed read, and a runbook line to reload and check `/api/me` first
- Override: —
- Outcome: guard added (12b79ff)

## Delivery

Delivered under the owner's standing instruction of 2026-11-10, with no stop
after the split.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Admin identity, schema, photo sizes | Opus | S4 | 1 (+ review fixes) | X3: one test file outside Scope | yes | R1-2, R1-4, R1-6, R2-1, R2-2, R2-3 |
| U2 | Admin routes and shared deletion | Opus | S5 | 1 (+ review fix) | X3: deps.py for R3-1 | yes | R1-1, R1-3, R1-5, R3-1, R3-2 |
| U3 | Client panel and the manual plan | Opus | S5 | 1 (+ a layout fix) | X3: api_client.dart (a body on delete, reauth) | yes | R4-2, R4-3 |
| U4 | Runbook | Sonnet | — | 1 | — | yes | — |

The branch was cut before the introduction screens reached master; master
was merged in at integration (R4-1), with both sides kept.

## Round 5 — 2026-11-11, review of the subscription follow-up, reviewed at fb12657

Decisions approved by the owner ("as recommended", 2026-11-11).

### R5-1 — An ended subscription shows the end of its paid period as its end date
- Trigger: Stripe cancels a subscription past its last retry, or the owner cancels it at once → the admin reads "Ended on" a date up to a year ahead; an unpaid first invoice reads "Ends on" its period end.
- Scores: trigger=concrete, impact=silent-wrong, detect=silent, later=cheap, fix=M/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open

### R5-2 — A subscription whose events were lost reads "Ended"
- Trigger: the webhook is unreachable across a renewal → past the grace the panel says "Ended" while Stripe probably still charges.
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: —
- Guard: —
- Override: owner: Fix now — seeing what Stripe really does is the point of the request; "No news from Stripe since <date>" instead of "Ended"
- Outcome: open

### R5-3 — The users list drops the effective plan beside a subscription or grant line
- Trigger: a grant's date passes → the row reads only "Granted here until <past date>", never "Free".
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open
