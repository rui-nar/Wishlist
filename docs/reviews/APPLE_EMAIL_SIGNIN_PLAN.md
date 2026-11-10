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
