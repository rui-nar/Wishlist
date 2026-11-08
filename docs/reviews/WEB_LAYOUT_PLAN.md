# Review ledger — Web layout and welcome page

Subject: docs/plans/WEB_LAYOUT_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 (web UI: "do
all this silently, push and merge the PR"), the orchestrator approved the
triaged table after enforcing the floors, and answered envelope questions with
its recommendation. No floor finding was rejected.

## Round 1 — 2026-11-08, reviewed at ce830a4 (plan uncommitted)

Envelope question: make `/about` a second public route, or drop the welcome
page's version link? Answer (orchestrator, standing instruction): public
`/about`; it shows versions only and `/api/version` is already public.
Written into D6 and the envelope.

### R1-1 — The welcome page's version link sends a signed-out visitor to the sign-in card, and the plan forbids the fix
- Trigger: a signed-out visitor on /welcome clicks the footer version link → the guard sends /about to /sign-in?from=/about
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/shared, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: D6 public /about, envelope, U2 Do 1, acceptance and escalation)

### R1-2 — Crossing the expanded breakpoint rebuilds the home destination, refetching the lists and losing scroll position
- Trigger: a tablet rotates or a window is resized across 840 px → HomeScreen's root widget type changes, the destination state is unmounted, GET /api/lists runs again and the scroll resets
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D3 same tree shape, U3 acceptance test)

### R1-3 — U1's proposed content-cap mechanism makes every U3 screen hit U3's own escalation condition
- Trigger: U3 wraps bodies in PageFrame; their ListViews keep a const s16 padding, so capping needs each scroll view's padding changed, which U3 lists as an escalation reason
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: U1 Do 3 fixes `paddingOf` / `centered`; U3 may change scroll view padding)

### R1-4 — D3 and D9 conflict: a rail beside the destination's scaffold leaves its app bar short of the window width
- Trigger: U3 builds Row(rail, scaffold) → the app bar starts right of the rail, against D9
- Scores: trigger=concrete, impact=cosmetic, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D9 amended to Material's adaptive layout)

## Round 2 — 2026-11-08, unit review of U2 (DELIVERY.md §5 point 3), reviewed at a9346dc

Envelope questions, answered by the orchestrator under the standing
instruction: (1) the welcome copy describes what the deployed build does; the
reserving plan updates it when reserving ships. (2) The welcome page is the
entry for any signed-out visit to bare home on every platform, but a user
whose session ended should land on the sign-in card (R2-3, deferred by rule).

### R2-1 — The welcome page promises invitee coordination that the shipped product does not have
- Trigger: a visitor reads "let them coordinate without spoiling the surprise", registers and shares → invitees can only read; no invitee action exists yet
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (faa9b71, fix unit F1)

### R2-2 — A home link with any query string skips the welcome page and hides the welcome link
- Trigger: a signed-out visitor opens `/?fbclid=…` → the guard compares the whole location to `/` and sends `/sign-in?from=/?fbclid=…`, hiding "What is Wishlist?"
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (faa9b71, fix unit F1)

### R2-3 — A returning user whose stored session is refused lands on the welcome page instead of the sign-in card
- Trigger: a returning user opens `/` with an expired or revoked token → restore gets 401 → signedOut → the guard sends them to `/welcome`
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=M/shared, confidence=verified
- Decision: Defer (D8)
- Revisit when: users report landing on the welcome page after their session expired, session lifetime is shortened or revocation becomes common, or AuthController's signed-out handling is next changed
- Override: —
- Outcome: open

## Round 3 — 2026-11-08, integrated diff ce830a4..faa9b71

No envelope questions.

### R3-1 — On Android, the welcome page's Log in and Register leave no page to go back to
- Trigger: a signed-out Android user on /welcome taps Log in, then system back → the app exits instead of returning to the welcome page (sibling routes, `context.go`)
- Scores: trigger=theoretical (triager: was concrete), impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Reject (D11)
- Revisit when: an Android or iOS build goes to testers (new evidence, so D2 does not block it then)
- Override: —
- Outcome: open

### R3-2 — Plan D8 still describes the welcome copy that R2-1 removed
- Trigger: the reserving plan's author reads D8 and plans copy changes against text that does not exist
- Scores: trigger=concrete, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D8 carries the shipped copy and says the reserving plan updates it)

## Delivery

Orchestrated under the owner's standing instruction of 2026-11-08 (web UI).
Each wave had one unit, run in the main tree (no worktree, W2 not needed).

| Unit | Wave | Route | Rule | Attempts | Verdict | Commit |
|---|---|---|---|---|---|---|
| U1 — Breakpoints, page frame and backdrop | 1 | Opus | S2 (no CustomPainter precedent) | 1 | pass | ca1bb06 |
| U2 — Welcome page, guard and sign-in screen | 2 | Opus | S5 (sign-in guard) | 1 | pass; unit review round 2 | a9346dc |
| U3 — Wide layout for home and the signed-in screens | 3 | Opus | S2 (no adaptive-navigation precedent) | 1 | pass | 8e2b299 |
| F1 — R2-1, R2-2 | 4 | Opus | S5 (sign-in guard) | 1 | pass | faa9b71 |

Escalations: none. Checks at the end: `flutter analyze` clean, `flutter test`
319 passed, `goldens.ps1 -Check` 66 passed. Open: R2-3 (deferred), R3-1
(rejected until a mobile build goes to testers).
