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

## Round 3 — 2026-11-08, U1 unit review (DELIVERY.md §5 point 3), reviewed at 7375c18

### R3-1 — A request racing the sign-out or deletion of its own session answers 500
- Trigger: two tabs share the token; one signs out or deletes the account while the other's request touches the session → the touch UPDATE matches 0 rows (StaleDataError) or the user lookup misses (NoResultFound) → 500 instead of 401
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified (traced)
- Decision: Defer (D10)
- Revisit when: a 500 with StaleDataError or NoResultFound from the session touch appears in the logs, a user reports an error after signing out or deleting the account on another tab or device, or the client's auth handling needs a 401 on a revoked session
- Override: —
- Outcome: open

## Round 4 — 2026-11-08, U4 unit review (DELIVERY.md §5 point 3), reviewed at f39246b

No Fix now. (Recorded late: the first attempt to append this round was lost
in a failed command chain; the integrated review of round 5 noticed.)

### R4-1 — A deletion whose answer is lost is reported as failed although the account is gone
- Trigger: a user deletes their account on a flaky connection → the server deletes, the 204 is lost → "could not be deleted, try again" → the next action gets 401 and lands on sign-in with no message
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a user reports being told their account could not be deleted when it was, or being signed out right after a delete attempt; or the client gets a shared way to handle actions with an unknown outcome
- Override: —
- Outcome: open

### R4-2 — On the web, a blocked Google script leaves the sign-in screen spinning forever
- Trigger: a visitor's browser blocks `accounts.google.com/gsi/client` → the init future never completes → endless progress, no message, only a reload helps
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a report of a sign-in screen that never finishes loading on the web, or the web sign-in flow is reworked
- Override: —
- Outcome: open

## Round 5 — 2026-11-08, integrated diff (DELIVERY.md §5 point 2), reviewed at 9423e68

No Fix now: the review is complete.

Envelope questions, answered by the orchestrator (standing instruction):
1. The envelope promised a 503 when Google is unreachable, but R1-1 (deferred)
   keeps a 401. Answer: the envelope is amended to state the deferral; R1-1's
   revisit triggers stand (including "before PROD is opened to anyone other
   than the owner").
2. The U4 unit review was missing from this ledger. Answer: recorded above as
   Round 4.

### R5-1 — A deletion whose answer is lost is reported as failed
- Decision: Duplicate (D2) of R4-1 — same trigger, no new evidence beyond the server-side commit timing, which R4-1 already assumes
- Override: —
- Outcome: open (see R4-1)

## Delivery

Delivered on `feat/first-version`, 2026-11-08. Checks at integration: server
`ruff check`, `alembic upgrade head` + `alembic check`, `pytest`; client
`flutter analyze`, `flutter test`, `.\goldens.ps1 -Check`, `flutter build web
--release --no-web-resources-cdn`; `shellcheck entrypoint.sh`; `actionlint`.
CI (Tests, Deploy smoke) runs when the branch is pushed.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Server accounts | Opus | S4 | 1 | — | yes | R1-1, R1-2, R3-1 |
| U2 | Start against a newer database (R2-2) | Opus | S3 | 1 | — | yes | R1-5 |
| U3 | Configuration and runbook for Google sign-in | Opus | S3 | 1 | — | yes | — |
| U4 | Client sign-in, session and account screen | Opus | S5 | 1 | — | yes | R4-1, R4-2, R5-1 |
| U5 | CI for the vendored Google sign-in package | Sonnet | — | 1 | — | yes | — |

Notes:
- `flutter test --platform chrome` hangs on the Windows dev machine; the
  vendored package's test runs in CI (Linux) and was run once in a Linux
  Chromium container during U4.
- Sign-in with a real Google account is not yet verified: no OAuth client ID
  exists (owner step, `docs/DEVELOPMENT.md` and `docs/DEPLOYMENT.md` step 11).
- Integration fix F1 (Sonnet, 1 attempt): the Dockerfile copies
  `client/third_party/` before `flutter pub get`, which the vendored package
  needs; found by the Deploy smoke workflow on the branch, verified by it.
