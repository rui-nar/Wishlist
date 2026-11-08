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
