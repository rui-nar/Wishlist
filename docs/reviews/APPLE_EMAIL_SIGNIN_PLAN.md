# Review ledger — Apple and email sign-in

Subject: docs/plans/APPLE_EMAIL_SIGNIN_PLAN.md
Envelope: the plan's `## Review envelope`, with REVIEW.md defaults

Decisions approved as triaged, floors enforced, under the owner's standing
instruction of 2026-11-10.

## Round 1 — 2026-11-10, reviewed at dfa2437

### R1-1 — Per-address `start` limit can silently swallow a person's link
- Trigger: someone uses up an address's quota → the person's own request answers 202 and adds no row. As reported, no email ever arrives; the triager found the attacker's accepted requests each mail a working link, so this needs an IP refusal counted after the address.
- Scores: trigger=plausible (corrected from concrete), impact=degraded-ux, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D9)
- Revisit when: —
- Guard: the fixed log label `email_start_address_limited` (plan D12)
- Override: —
- Outcome: open

### R1-2 — A link completed during the account's deletion can answer 500
- Trigger: the holder deletes the account while submitting a reset link → FK violation, 500. The request rolls back, so the link is not spent and no orphan row remains.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a 500 or deadlock is logged on `POST /api/auth/email/complete` or `DELETE /api/me` involving users, password_credentials or email_links, or the link can no longer be retried after such a failure
- Guard: —
- Override: —
- Outcome: open

### R1-3 — U3's routes need `test_surprise.py`, outside its Scope
- Trigger: the U3 implementer adds the Apple routes → `test_every_route_is_called` fails, and the file is only in U2's Scope, in the same wave.
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (U3 moved to Wave 3, with the file in its Scope)

### R1-4 — A second pending link can reset a password just chosen
- Trigger: a person requests twice, uses the first email, then opens the second → the server replaces the new password and ends their session.
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D9, U2 Acceptance)

### R1-5 — With the worker off, links expire unsent
- Trigger: the operator sets `NOTIFICATIONS_WORKER=false` → requesters are told to check their inbox and the link expires unsent after an hour.
- Scores: trigger=plausible, impact=degraded-ux, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D9)
- Revisit when: —
- Guard: a warning at start (plan D18, U1)
- Override: —
- Outcome: open

### R1-6 — Apple's one-time name is lost if the first sign-in fails
- Trigger: a first-time Apple user authorises, the server answers 502 → on retry Apple sends no name, and the account gets a fallback name nothing can change.
- Scores: trigger=plausible, impact=cosmetic, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a person reports a wrong name such as "Apple user" after a failed first sign-in, Apple 502s are seen on first sign-ins, or a plan adds editing the account name
- Guard: —
- Override: —
- Outcome: open

## Round 2 — 2026-11-10, unit review of U1, reviewed at 55c058e

No findings.

## Round 3 — 2026-11-10, unit review of U2, reviewed at 092eb2c

### R3-1 — A correct password refused when two sign-ins race through a rehash
- Trigger: after a change of Argon2 parameters, two sign-ins with the right password within ~100 ms → the second verified the old hash and answers 401.
- Scores: trigger=theoretical (corrected from plausible: one parameter set, and a new table), impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Reject (D11)
- Revisit when: — (a change of the Argon2 parameters would be new evidence)
- Guard: —
- Override: —
- Outcome: open

### R3-2 — Completing a link while deleting the account can deadlock with two links
- Trigger: a person with two pending links submits one while deleting the account on another device → a deadlock, 500 on one route, which can be retried.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible (corrected from logged), later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a deadlock or 500 is logged on `POST /api/auth/email/complete` or `DELETE /api/me` involving email_links, or a change makes either route hold email_links row locks for longer
- Guard: —
- Override: —
- Outcome: open

### R3-3 — The worker's run aborts when a link is deleted mid-send
- Trigger: a person requests a reset, then deletes the account while the worker's Brevo call is in flight → `_record` raises and that run stops, the rest running 15 s later.
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: `notifications: run failed (NoResultFound)` or `(StaleDataError)` appears in the logs, or anything other than delete_me and the expiry sweep starts deleting email_links rows that can be sending
- Guard: —
- Override: —
- Outcome: open

## Round 4 — 2026-11-10, unit review of U3, reviewed at 376fdad

No findings.

## Round 5 — 2026-11-10, integrated review, reviewed at 01120d6

Decisions approved as triaged, floors enforced, under the owner's standing
instruction of 2026-11-10.

### R5-1 — A Google failure masks the outcome of a later email sign-in
- Trigger: Google's flow fails with a non-cancel error → the person submits a wrong password in the email form → the error line keeps reading the Google message.
- Scores: trigger=plausible (corrected from concrete: a blocked script hangs and never sets the failure), impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a person reports the Google message after an email sign-in attempt, non-cancel Google failures are seen on Android or the web, or a change makes Google's script load able to report failure
- Guard: —
- Override: —
- Outcome: open

### R5-2 — Android offers Apple when `APPLE_ANDROID_PACKAGE` is empty
- Trigger: the operator sets `APPLE_CLIENT_IDS` and leaves the package empty → an Android user authorises → the callback answers a JSON 503 in the custom tab, and the app's attempt stays pending.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: an environment that Android builds point at is deliberately run with Apple on the web only, the runbook stops setting both together, or a 503 on `POST /api/auth/apple/callback` is logged or reported
- Guard: —
- Override: —
- Outcome: open

## Delivery

Delivered under the owner's standing instruction of 2026-11-10, with no stop
after the split.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Schema, settings, identities, throttle, passwords | Opus | S4 | 1 | — | yes | R1-1, R1-5 |
| U2 | The email routes and the worker's step | Opus | S5 | 1 | — | yes | R1-2, R1-4, R3-1, R3-2, R3-3 |
| U3 | Server: Apple | Opus | S5 | 1 | — | yes | R1-3, R1-6 |
| U4 | Client: email sign-in | Opus | S5 | 1 | — (goldens run by the orchestrator: the worktree refuses pwsh) | yes | R5-1 |
| U6 | Docs and deployment | Sonnet | — | 1 | — | yes | — |
| U5 | Client: the Apple button | Opus | S5 | 1 | — (goldens run by the orchestrator) | yes | R5-2 |
| F1 | A flaky test of U2 | Opus | S5 | 1 | — | yes (20 runs; full suite) | — |
