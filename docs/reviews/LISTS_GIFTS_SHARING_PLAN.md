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

## Round 3 — 2026-11-08, reviewed at e59f327

Round 3 is the cap (§6). Its Fix now items are applied to the plan; they are
checked again in the review of the integrated diff, not in a fourth round of
the plan.

### R3-1 — The path URL strategy never hands the fragment to the router; the sign-in redirect erases it
- Trigger: a signed-out invitee opens `/join#<token>` → the router sees `/join`, redirects to sign-in, the hash is gone → back on `/join` nothing is pending → "link no longer valid" for every new invitee
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: token captured from `Uri.base` before the router is created; browser-level check in U4's acceptance)

### R3-2 — The pending join token is never cleared; back to `/join` replays it
- Trigger: an invitee joins, then presses back → `/join` finds the pending token and forwards again → back is a trap
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager)
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: cleared on every outcome; navigation by replace; test)

## Round 4 — 2026-11-08, U1 unit review (DELIVERY.md §5 point 3), reviewed at 9fc0080

### R4-2 — The role matrix cannot fail for an endpoint nobody added to it
- Trigger: a later unit adds an endpoint without a matrix row → every role test passes → a wrong access check ships with a green matrix
- Scores: trigger=plausible, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D9)
- Guard: `test_every_route_is_in_the_matrix` in `server/tests/lists/test_roles.py` fails when a route under the guarded prefixes is in neither `ENDPOINTS` nor `COVERED_ELSEWHERE`, or a row matches no route (0ad717d)
- Override: —
- Outcome: guard added

### R4-1 — An owner edit racing a delete of the same list answers 500, not 404
- Trigger: the same owner renames a list or adds a gift on one device while deleting the list on another → StaleDataError or FK IntegrityError → 500
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a StaleDataError or IntegrityError 500 from a `/api/lists` or `/api/gifts` endpoint appears in VAL or PROD logs, or a later plan adds co-owners or offline sync
- Override: —
- Outcome: open

## Round 5 — 2026-11-08, U2 unit review (DELIVERY.md §5 point 3), reviewed at 957ba23

Envelope question: is removing an invitee effective on its own, or must the
owner also regenerate the link? Answer (orchestrator, standing instruction):
effective on its own — a removed person cannot rejoin through any link until
the owner allows them again. Recorded in `docs/NEEDS.md` (Access) and the plan
(D4, D8, U2, U4); implemented in U2 before integration.

### R5-1 — Owner edits of an occasion racing its deletion answer 500, not 404
- Trigger: an owner renames an occasion or changes its link on one device while deleting it on another, or an invitee reads an occasion while the owner deletes the list → StaleDataError or NoResultFound → 500
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10) — cross-reference: R4-1 (same mechanism on `/api/lists` and `/api/gifts`)
- Revisit when: a StaleDataError, NoResultFound or IntegrityError 500 from `/api/occasions/*`, `/api/join/preview` or `/api/join` appears in VAL or PROD logs, or a later plan adds co-owners or offline sync; fix R4-1 and R5-1 together with one mapping of these errors to 404
- Override: —
- Outcome: open

## Round 6 — 2026-11-08, U4 unit review (DELIVERY.md §5 point 3), reviewed at 57adb31

Envelope question: when an owner removes an invitee who left a moment earlier,
is the removal recorded? Answer (orchestrator, standing instruction): yes, the
owner's explicit decision wins. Recorded in `docs/NEEDS.md` (Access).

### R6-1 — After joining from a signed-out start, Back shows "This link is no longer valid"
- Trigger: a signed-out invitee opens `/join#<token>`, signs in, joins, presses Back → `/sign-in?from=/join` forwards to `/join` with nothing pending → "no longer valid", repeatedly
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/shared, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: open (fix unit F3)

### R6-2 — Removing an invitee who just left is not recorded, and the owner is told the occasion is gone
- Trigger: an owner removes someone who left a moment earlier → the server answers 404 before recording the removal → the client says "This occasion no longer exists" → the person can rejoin with the current link
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=M/shared, confidence=verified
- Decision: Fix now (D3, floor F3)
- Override: —
- Outcome: open (fix unit F2; allow-again made idempotent in the same unit)
