# Review ledger — Accounts

Subject: docs/plans/ACCOUNTS_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 ("proceed
systematically with your recommendations"), the orchestrator approved the
triaged table after enforcing the floors. No floor finding was raised.

## Round 1 — 2026-11-08, reviewed at 1a6063a

### R1-2 — The session touch is rolled back on read-only requests
- Trigger: a user opens the app daily → `current_user` touches the session, `GET /api/me` commits nothing → the touch is rolled back → signed out 90 days after sign-in
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: `db_session` is one unit of work per request; request-path test)

### R1-3 — Wave 1 not disjoint: U2 and U3 both edit docs/DEPLOYMENT.md
- Trigger: orchestrator runs wave 1 in parallel → both units edit the runbook → conflict or lost text
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U3 moved to wave 2)

### R1-4 — U5 depends on U4 inside wave 2
- Trigger: orchestrator runs wave 2 in parallel → U5's CI step needs U4's vendored package → acceptance cannot be met
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U5 moved to wave 3)

### R1-1 — Google unreachable: 401 after up to 120 s instead of a 503; no certificate caching
- Trigger: a user signs in while googleapis.com is unreachable from the VPS → the certificate fetch blocks up to 120 s, then `TransportError` is mapped to "invalid token" → 401
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible (triager: was logged), later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a sign-in failure is logged with a `TransportError` or timeout rather than a bad token, someone reports slow or failing sign-in, or before PROD is opened to anyone other than the owner, whichever comes first
- Override: —
- Outcome: open

### R1-5 — The runbook rewrite drops the rollback restriction without its remaining bounds
- Trigger: the owner rolls PROD back to an image older than this plan (no `app.migrate`) → crash loop; or the `validation` tag moves back from a branch with a migration → VAL starts on an unknown revision and serves 500s
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: before the runbook's rollback is first used on PROD, before the `validation` tag is moved back from a branch that carries a migration, or when VAL logs the D13 "unknown revision" warning and then serves 500s
- Override: —
- Outcome: open

## Round 2 — 2026-11-08, reviewed at dcf2593

No findings. The R1-2 wording and tests are consistent with U1 step 8, and the
moved units satisfy DELIVERY.md W1–W4. Review of the plan complete (§6: no Fix
now).
