# Review ledger — DevOps foundation

Subject: docs/plans/DEVOPS_FOUNDATION_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

## Round 1 — 2026-11-07, reviewed at ee8523e + uncommitted plan

Envelope question to the user: RAM budget for Wishlist's containers on the
shared 4 GB VPS, and whether a TraxJourney peak may OOM-kill a Wishlist
container (and vice versa).
Answer (user): about 1 GB in total; written into the plan's Review envelope.

### R1-3 — Flutter dev client is cross-origin and no unit adds CORS
- Trigger: owner runs `.\dev.ps1` → client on its own port calls `localhost:8000` → browser blocks the response → screen shows "server unreachable"
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan)

### R1-8 — U5 acceptance needs a CI run its triggers never create
- Trigger: implementer pushes U5's branch → `test.yml` runs only on push to master and pull requests → no run, acceptance cannot be checked
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

### R1-9 — U7 depends on U6 inside wave 3 (DELIVERY.md W1)
- Trigger: orchestrator runs wave 3 in parallel → U7's dependency on U6 cannot be met
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan)

### R1-1 — Backup failures have no observer
- Trigger: password rotation, OOM kill or full disk → backup sidecar stops dumping → nobody notices until a restore is needed
- Scores: trigger=plausible, impact=maintainability (triager: was data-loss; no data stored yet and loss needs a second failure), detect=silent (was logged), later=cheap, fix=S/local, confidence=inferred
- Decision: Guard (D9) — floor re-score flagged to the user
- Guard: (to add) healthcheck on the `backup` service failing when no dump is newer than 26 h, `restart: unless-stopped`; the runbook's backup check reads it
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-2 — Seeding VAL from a prod dump fails when VAL is ahead or uses another role
- Trigger: VAL migrated ahead of PROD, owner runs `seed-from-prod.yml` → leftover tables or ALTER OWNER errors → VAL crash-loops
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the first table-changing migration reaches VAL before PROD, VAL's DB role differs from PROD's, or a seed fails with "already exists"/ALTER OWNER errors
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-4 — `pg_isready` healthy during first-boot init
- Trigger: first `up` on a fresh volume → healthcheck passes on the init server's socket → `alembic upgrade head` refused over TCP
- Scores: trigger=plausible (triager: was concrete; needs a timing window), impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a fresh `.\dev.ps1` or first VAL/PROD `up` fails at `alembic upgrade head` with connection refused, or an app container stays stopped after a crash
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-5 — Bind-mount ownership on Linux never exercised
- Trigger: owner creates `/opt/wishlist/{db,backups}` as deploy user → a non-root sidecar or db gets "Permission denied"
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the first-night dump check finds no dump, or a container logs "Permission denied" on those directories
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-6 — Rollback to an older image ignores migrations
- Trigger: release with a schema change rolled back to the previous image → old code fails against the newer schema; host compose left on the old tag blocks the next deploy
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the first release after v0.1.0 with a migration changing existing tables, or before the runbook's rollback is first used on PROD
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-7 — No procedure for a Postgres major-version bump
- Trigger: Dependabot or the owner moves the pinned Postgres image across a major → data directory incompatible → db will not start
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: Dependabot proposes a Postgres major bump, or a major upgrade is planned
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

### R1-10 — `.gitignore` owned by a later wave than the units producing caches
- Trigger: U1 runs pytest → `__pycache__` untracked → committed by hand
- Scores: trigger=plausible (triager: was concrete; U1 can add `server/.gitignore`, tools ship their own ignores), impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a unit's diff or the integrated diff contains `__pycache__` or other cache/build artefacts
- Override: user: Fix now — every finding is small and local; fix them all in the plan now
- Outcome: fixed (in plan)

## Round 2 — 2026-11-07, reviewed at 04085b9

Subject: the round 1 fixes and the media storage decision (D18).

### R2-1 — Nothing pins `MEDIA_DIR` to the bind-mounted `/app/media`
- Trigger: image built with a WORKDIR other than `/app` and the default `MEDIA_DIR=./media` → health check and smoke test pass → uploads land in the container layer and vanish on the next `up -d`
- Scores: trigger=plausible, impact=data-loss, detect=silent, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D3, floor F2)
- Override: —
- Outcome: fixed (in plan)

### R2-3 — Hard-linking PROD media into VAL fails under `fs.protected_hardlinks=1`
- Trigger: owner runs `seed-from-prod.sh` as the deploy user once uid-10001 files exist → `Operation not permitted` → script stops after VAL's database was replaced, VAL left down
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan)

### R2-4 — DEV media directory created by no unit and not ignored
- Trigger: owner runs `.\dev.ps1` from a fresh clone → `/api/health` 503 `media: not writable`; a hand-made `media/` shows as untracked
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan)

### R2-2 — Rolled-back image stops on a migration revision it does not know
- Trigger: rollback to an image older than the database's Alembic revision (or VAL seeded while its image is behind PROD's) → `alembic upgrade head` fails "Can't locate revision" → app restarts in a loop
- Scores: trigger=plausible (triager: was concrete; a rollback follows a bad release, as scored in R1-6), impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the first migration after the baseline is written (before it reaches PROD), before the runbook's rollback is first used on PROD, or VAL is seeded while its image is behind PROD's
- Override: —
- Outcome: open

### R2-5 — Media purge counted in days, dump retention in number of dumps
- Trigger: backup outage of several nights → 30 kept dumps span more than 30 days → restoring the oldest finds a purged image missing
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the gifts feature plan implements the purge (state the rule relative to the oldest kept dump), or the backup healthcheck stays unhealthy for more than one night
- Override: —
- Outcome: open
