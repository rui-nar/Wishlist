# Review ledger — Shush Gift: name and domain

Subject: docs/plans/SHUSH_GIFT_PLAN.md
Envelope: the plan's "Review envelope" section, over REVIEW.md defaults

## Round 1 — 2026-11-11, reviewed at 61de3ac (plan uncommitted, working tree)

### R1-1 — The new PROD app starts before the kept dumps are in its backups directory
- Trigger: owner follows D8 in order on PROD → the new backup service dumps once into an empty `/opt/shushgift/backups`, the purge's first run dates its horizon from that single dump → orphan images that the older dumps still reference are deleted
- Scores: trigger=concrete (triage, was plausible), impact=data-loss, detect=logged, later=expensive, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

### R1-2 — A private repository breaks the runbook's file fetch
- Trigger: owner renames and privatises the repository, then the VAL cut-over fetches deploy files by unauthenticated raw URL → 404, the move stops
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=M/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

### R1-3 — The webhook filter is spelled `rui-nar/ShushGift`, but the repository becomes `rui-nar/shushgift`
- Trigger: units set the filter as D8 step 7 says, and the owner renames as D3 says → every delivery fails the exact-match rule, so VAL never redeploys by itself
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

### R1-4 — D8's way back fails once the media are moved and the dumps renamed
- Trigger: owner starts the old project again after a failed PROD cut-over → its media mount is empty and the old rotation and seeding ignore `shushgift_*` dumps
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triage)
- Decision: Defer (D10)
- Revisit when: U6 writes D8's way back, or before PROD's cut-over. It must undo the media move and the dump rename.
- Guard: —
- Override: —
- Outcome: open

### R1-5 — D9 leaves out values tied to the app ids
- Trigger: owner repoints only what D9 lists → `GOOGLE_IOS_CLIENT_ID(_VAL)`, `GOOGLE_PLAY_PACKAGE_NAME`, `APPLE_APP_APPLE_ID`, the store subscription products and Play's notification setting keep old values → the Google button fails in the iOS app, or store purchases go unrecorded
- Scores: trigger=concrete (triage, was plausible), impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triage)
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

### R1-6 — The macOS iOS build on each `validation` tag can use up the private repository's minutes
- Trigger: owner pushes several `validation` tags in a month → the macOS minutes, counted ten times, use up the 2,000-minute quota → the image build is refused too
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a month's Actions usage passes 50% of the quota, or a run is refused for lack of minutes. Then run `ios-release.yml` by hand, or only when `client/` changed.
- Guard: —
- Override: user: Fix now — the iOS release runs on version tags only (v[0-9]*), never on validation; VAL iOS builds are manual runs
- Outcome: fixed (plan updated, D3a and U5)

### R1-7 — U2 and U3 share the three `.env.example` files in wave 1
- Trigger: the orchestrator runs U2 and U3 in parallel worktrees → both edit the same files, against DELIVERY.md W1
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

Envelope questions, answered by the owner on 2026-11-11:
- App links are a need: recorded in docs/NEEDS.md (Name and domain, Sign-in).
- No App Store Connect or Play Console record exists under any other id, so
  there is nothing to retire.
