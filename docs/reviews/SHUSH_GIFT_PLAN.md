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

## Round 2 — 2026-11-11, reviewed at 77a67d0

Decided under the owner's standing instruction of 2026-11-11 ("proceed as
recommended silently"): table self-approved, floors enforced. Envelope
question answered with the recommendation: VAL keeps its data across the
move, dumped and restored through its own `db` container.

### R2-1 — The backup service's first dump overwrites the final dump
- Trigger: owner moves the final dump in as `shushgift_<today>.dump`, then starts the backup service → its first dump replaces that file through `mv -f`
- Scores: trigger=concrete, impact=degraded-ux (triage, was data-loss: the replacing dump is of a database restored from that same dump, and the old volume stays), detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated: `before-move.dump`)

### R2-2 — D9 leaves out Apple's private relay sender registration
- Trigger: owner repoints only what D9 lists → Apple stops relaying mail from `hello@shushgift.com`, and people who hid their address silently get no emails
- Scores: trigger=concrete, impact=degraded-ux, detect=silent, later=cheap, fix=S/local, confidence=verified (triage)
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

### R2-3 — D8 assumes VAL has a backup service
- Trigger: owner runs D8 on VAL first → the dump, move and restore steps fail, because VAL has no backup service
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated: VAL variant of D8)

### R2-4 — NEEDS.md does not record the app ids or the full rename
- Trigger: a planner reads NEEDS.md → finds "the bundle identifier is decided later"
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (NEEDS.md updated)

## Round 3 — 2026-11-11, reviewed at 349d04c

Standing instruction of 2026-11-11, as in round 2. Envelope question answered
with the recommendation: VAL's move dump is `chmod 600` and deleted once VAL
is confirmed. This is the last round (§6): the plan goes to delivery after
these fixes.

### R3-1 — `before-move.dump` is never deleted, so it freezes the purge's horizon
- Trigger: owner follows D8 and U6 on PROD → `before-move.dump` stays, and after 30 days it is the oldest dump → images released after the move are never purged
- Scores: trigger=concrete, impact=degraded-ux, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated: deleted with the old volume)

### R3-2 — The VAL variant's commands and step order do not run as written
- Trigger: owner runs D8's VAL commands → the dump targets a directory not yet created, `pg_dump` lacks a role, `pg_restore` lacks `-d` → the cut-over stops, with nothing lost
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified (triage)
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan updated)

## Round 4 — 2026-11-12, integrated review (DELIVERY.md §5 point 2), reviewed at a4b6709

Standing instruction of 2026-11-11, as in round 2: table self-approved, floors
enforced. No envelope question.

### R4-1 — Part 8's deletion block removes all of /opt when OLD is not set in the shell
- Trigger: owner comes back a day later in a new SSH session and pastes part 8's block → `sudo rm -r /opt/$OLD /opt/$OLD-val` runs as `sudo rm -r /opt/ /opt/-val` → the new PROD's `.env`, every dump and all media are deleted
- Scores: trigger=concrete (triage, was plausible), impact=data-loss, detect=user-visible, later=expensive, fix=S/local, confidence=verified
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open

### R4-2 — The PROD release tag is pushed before API_BASE_URL_PROD names the new host
- Trigger: owner follows part 6 in order and pushes the release tag → both release workflows build the PROD apps for the old host, which part 7 removes
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open

### R4-3 — Cut-over step 7's horizon check prints nothing for ten minutes
- Trigger: owner runs the purge-log check right after `up -d --wait` → empty output, none of the documented cases
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open

### R4-4 — Part 3 reuses step 6's Caddy guard, which expects 0 but prints 2 or more during the move
- Trigger: owner appends the snippet "as in step 6" → the guard counts the old hosts' blocks → reads as already appended, the append is skipped
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: open
