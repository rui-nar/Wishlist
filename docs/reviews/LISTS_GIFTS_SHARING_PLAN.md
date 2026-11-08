# Review ledger — Lists, gifts and sharing

Subject: docs/plans/LISTS_GIFTS_SHARING_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 ("proceed
systematically with your recommendations"), the orchestrator approved the
triaged table after enforcing the floors, and answered the envelope questions
with its recommendation. No floor finding was rejected.

## Round 1 — 2026-11-08, reviewed at 1a6063a

Envelope questions, answered by the orchestrator (standing instruction):

1. Join tokens in URLs reach access logs. Answer: the API takes the token in
   the request body (`POST /api/join`, `POST /api/join/preview`); the
   client's `/join/<token>` route stays, and browser history is accepted.
2. Joining on a click with no confirmation. Answer: not accepted; the client
   shows a confirmation screen built from a preview before joining.

Both are written into the plan's envelope, D5 and D8.

### R1-1 — The invitee's occasion response is not specified to omit join tokens and other occasions
- Trigger: owner regenerates a link → an invitee calls `GET /api/occasions/{id}` → a shared response model hands them the new token or the tokens of the list's other occasions
- Scores: trigger=plausible (triager: was concrete), impact=security, detect=silent, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D3, floor F1)
- Override: —
- Outcome: fixed (in plan: a per-role invitee model; content checks in the role matrix)

### R1-3 — The 409 on join carries no list id
- Trigger: an owner opens their own link → 409 with a message only → the client cannot open the list
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: 409 `{"list_id"}`, preview `role` with `list_id`)

### R1-4 — The invitee's occasion response has no recipient or owner names
- Trigger: an invitee joins a "for me" list → `recipient_name` is null and no owner name is returned → the privacy banner has no name
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: the invitee model carries the recipient display name and the owners' names)

### R1-5 — Price validation not bounded to numeric(12,2)
- Trigger: an owner types 12345678901 → numeric overflow → 500; types 19.999 → stored as 20.00 silently
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: D3 digit and decimal bounds; U1 tests)

### R1-6 — List title and recipient name have no size cap
- Trigger: a modified client creates a list with a multi-megabyte title → every list and shared response carries it
- Scores: trigger=concrete (triager: was plausible; a modified client is in the envelope, E2), impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: 1–100 in D1; U1 test)

### R1-2 — Concurrent double join by the same user can 500; the race test cannot fail
- Trigger: a user double-taps "Join" → two inserts of the same membership → a check-then-insert implementation answers 500 to one
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a 500 or IntegrityError from the join endpoint appears in VAL or PROD logs, or a later plan adds another writer to `occasion_members`
- Override: —
- Outcome: open

### R1-7 — Share-link base URL has no mobile fallback; PUBLIC_BASE_URL is undocumented
- Trigger: an owner on the Android build shares a link while `PUBLIC_BASE_URL` is unset → a host-less link
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the VAL/PROD domain is decided, or a mobile build targeting VAL or PROD goes to testers: then set `PUBLIC_BASE_URL` in the deployment env and runbook, and hide share actions on mobile while it is empty
- Override: —
- Outcome: open

## Round 2 — 2026-11-08, reviewed at dcf2593

Envelope question: is the server access log an accepted sink for join tokens
(the first page load of `/join/<token>` is served and logged by uvicorn)?
Answer (orchestrator, standing instruction): no; the token moves into the URL
fragment (`/join#<token>`) before the link format ships.

### R2-1 — The join token still reaches the access log on every page load of the link
- Trigger: an invitee pastes `https://<host>/join/<token>` → the browser GETs it → uvicorn logs the path with the token
- Scores: trigger=concrete, impact=security, detect=logged, later=expensive, fix=S/local, confidence=verified
- Decision: Fix now (D3, floors F1 and F4)
- Override: —
- Outcome: fixed (in plan: `/join#<token>`, D5, envelope, boundary, U4; ACCOUNTS D10's mention updated to match)

### R2-2 — The confirmation screen has no test or golden in U4
- Trigger: U4 delivered as written → the confirmation screen ships without a golden; Cancel, member and owner paths untested
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U4 item 5)

### R2-3 — The join `token` body field has no size cap
- Trigger: a modified client posts a multi-megabyte token → read and looked up
- Scores: trigger=concrete, impact=maintainability (triager: was degraded-ux), detect=silent, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: at most 64 characters, 422 test)
