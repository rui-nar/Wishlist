# Review ledger — iOS app

Subject: docs/plans/IOS_APP_PLAN.md
Envelope: the plan's `## Review envelope`, with REVIEW.md defaults

Decisions approved by the owner ("as recommended", 2026-11-11), with the
envelope questions answered as recommended: revoke whenever a token exists;
real refresh tokens at rest outside PROD are F1.

## Round 1 — 2026-11-11, reviewed at the plan's first draft (uncommitted)

### R1-1 — Seeding VAL copies real Apple tokens, and a deletion on VAL revokes them
- Trigger: the owner seeds VAL and deletes a seeded account there → VAL revokes a real PROD user's Apple grant.
- Scores: trigger=plausible, impact=security, detect=silent, later=cheap, fix=S/shared, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D5, U3 Scope)

### R1-2 — VAL and PROD builds share one app, so a tester can work on VAL unknowingly
- Trigger: a VAL build replaces a tester's PROD build → the Keychain session works on seeded VAL → their changes vanish at the next seed.
- Scores: trigger=concrete (corrected from plausible), impact=silent-wrong, detect=silent, later=cheap (corrected from expensive), fix=M/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D1, D2: two apps)

### R1-3 — No source for the server address, which cannot be committed
- Trigger: the release workflow is built with an empty `API_BASE_URL` or with hostnames in the public repository.
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D2: two secrets)

### R1-4 — Nothing shows whether Apple's code exchange works
- Trigger: a wrong key, redirect or partial configuration leaves revocation off while sign-in succeeds.
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the code-exchange warning appears in a log, or an Apple sign-in on VAL with the variables set leaves no `apple_tokens` row (check at the first VAL build)
- Guard: —
- Override: —
- Outcome: open

### R1-5 — Revoking before `stop_billing` can refuse
- Trigger: an Apple-signed Stripe subscriber deletes during a Stripe outage → token revoked, deletion refused.
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: —
- Guard: —
- Override: owner: Fix now — one sentence fixes the order
- Outcome: fixed (plan D5)

### R1-6 — Automatic signing may create a certificate per run
- Trigger: each tag run on a fresh runner requests a certificate → Apple's limit is reached.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=M/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a release run fails on the certificate limit, or the account shows a new certificate per run
- Guard: —
- Override: —
- Outcome: open
