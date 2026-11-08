# Review ledger — Gift images

Subject: docs/plans/GIFT_IMAGES_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 ("implement
this and the reserving roadmap all silently", given that day after PR #9), the
orchestrator approved the triaged table after enforcing the floors, and
answered envelope questions with its recommendation. Floor flag R1-2 (F1,
Guard) is reported to the owner.

## Round 1 — 2026-11-08, reviewed at 23fbf5e

Envelope questions, answered by the orchestrator: (1) Never-attached pending
images are not exempt from the horizon rule: their row is deleted at 48 h and
their files become orphans (`first_seen_at = now`) that wait for the horizon
like any other (D9, Review envelope "Retention"). Revised after the amendment
found the restore-then-rollback case: a row pending in an older dump and
attached in a newer one, restored from the older dump then rolled back, comes
back attached, so its files must survive. The cost (pending uploads kept on
disk until the horizon) is accepted; storage per account stays an open
decision. The first answer, files deleted with the row at 48 h, is withdrawn.
(2) lcms2, bundled with Pillow and kept current by Dependabot, is named in the
envelope as an accepted parser of untrusted ICC profiles; D4's sRGB conversion
stays.

### R1-1 — A restored row deleted again keeps an old orphan clock, so a file a kept dump references can be purged
- Trigger: an operator restores an older dump with image row A, a later dump keeps A, then rolls back with `before-restore.dump` → A's old `media_orphans.first_seen_at` comes back, the purge deletes A's row → A's files are purged while a kept dump still references them
- Scores: trigger=plausible, impact=data-loss, detect=silent, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Fix now (D3, floor F2)
- Override: —
- Outcome: fixed (in plan: D9, U5 Do 1, U8)

### R1-2 — A malformed ICC profile reaches lcms2 with no handled failure
- Trigger: a user uploads an image with a malformed ICC profile → the sRGB conversion raises → unhandled error, or a parser fault in lcms2 on untrusted input
- Scores: trigger=theoretical, impact=security, detect=silent, later=cheap, fix=S/local, confidence=verified (triager: was inferred)
- Decision: Guard (D4, floor F1, flagged to the owner)
- Guard: the sRGB conversion is wrapped; any `ImageCms`/`PyCMSError` logs a warning `image icc: failed size=<profile bytes>` (no image data) and answers 422 `image_unsupported`; tested with a malformed ICC profile asserting the 422 and the warning
- Override: —
- Outcome: guard added (in plan: D4, U1 Do 2 and Acceptance)

### R1-3 — Progressive JPEGs defeat `draft()`: libjpeg holds the full coefficient arrays
- Trigger: a user uploads a large progressive (SOF2) JPEG within the 100 MP cap → libjpeg allocates the whole image's coefficients despite `draft()` → memory far above D4's bound, OOM risk under the container limit
- Scores: trigger=concrete, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D4, U1)

### R1-4 — Transpose and ICC conversion run on the full-size decode
- Trigger: a user uploads a 4096 × 4096 PNG with an ICC profile → `exif_transpose` and the ICC conversion each copy the full-size image before it is reduced → peak memory several times the decode, OOM risk under the container limit
- Scores: trigger=concrete, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D4, U1)

### R1-5 — `POST /api/images/from-url` keeps the client's 10 s JSON timeout
- Trigger: an owner gives an image URL on a slow host or while another image is processing → the server needs up to 20 s fetch plus 30 s lock wait → the client times out at 10 s and shows an error while the server creates the image
- Scores: trigger=concrete, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Override: —
- Outcome: fixed (in plan: U4 Do 1 and Acceptance, U6 Do 1 and Acceptance)

### R1-6 — Pending and detached images are told apart by age only
- Trigger: an owner replaces a gift's image less than 24 h after uploading it → the detached image looks pending → its uploader can still read it and attach it again, and every later rule (reads, attach, purge) has to guess the state
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=expensive (triager: was cheap), fix=S/local, confidence=verified
- Decision: Fix now (D5, F4)
- Override: —
- Outcome: fixed (in plan: D2, D7, D9, D11, U1, U5, U8)

### R1-7 — The role matrix misses hidden ids inside string values
- Trigger: a route returns a hidden image id inside a `url` or `thumb_url` path → `assert_reveals_nothing` compares whole values only → the leak passes the role matrix
- Scores: trigger=plausible, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Guard (D9)
- Guard: `assert_reveals_nothing` in `server/tests/lists/test_roles.py` also fails when any hidden id appears as a substring of a string value (`assert not any(h in value for h in hidden)`)
- Override: —
- Outcome: guard added (in plan: U5 Scope, Do 5 and Acceptance)

### R1-8 — D6 refuses images served with a mislabelled `Content-Type`
- Trigger: an owner gives the URL of an image served as `application/octet-stream` or `image/jpg` → the fetcher refuses the type → `url_fetch_failed` for a usable image
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the fetcher's host/outcome log or a user report shows image URLs refused for a mislabelled `Content-Type`
- Override: —
- Outcome: open

### R1-9 — D6 pins a single vetted address with no fallback
- Trigger: an owner gives an image URL whose host's first address is unreachable from the container (e.g. IPv6) → the pinned connection fails with no other address tried → `url_fetch_failed`
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the fetch log shows connect failures on hosts that also have a working address of the other family, or the container network gains IPv6
- Override: —
- Outcome: open

### R1-10 — The daily purge can race `seed-from-prod.sh`'s hard-link copy
- Trigger: an operator seeds VAL while PROD's daily purge deletes a file → `cp -R -l` fails on the vanished file → the seed aborts with VAL stopped
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a seed fails on a vanished media file, or seeding becomes scheduled or unattended
- Override: —
- Outcome: open (runbook line added in plan: U3 Do 3, rerun the seed if it fails on a vanished file)

## Round 2 — 2026-11-08, unit review of U1 (DELIVERY.md §5 point 3), reviewed at 97e09a7

Envelope answers (orchestrator, standing instruction): (a) upload abuse by a
signed-in user is out of scope on the same terms as fetch abuse ("revisit
with abuse"), but in-flight uploads and in-flight URL fetches are each bounded
by a small counting semaphore answering 503 `image_busy` when full (the fetch
bound lives in U5's from-url route); (b) the Definition of done's VAL
measurement records the API's idle RSS in docs/DEPLOYMENT.md.

### R2-1 — A 4096 × 4096 WebP is held about four times over while it decodes
- Trigger: a signed-in user uploads a large-canvas WebP (a few KB lossless) → libwebp canvases, a bytes copy and the image buffer coexist (≈256 MB) → the API container is OOM-killed
- Scores: trigger=concrete, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (5ecd446)

### R2-2 — Transparency promotion runs on the full-size decode before the reduction
- Trigger: an RGB PNG with a tRNS chunk at the 4096² cap → full-size RGBA copy → about 112 MB peak
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: VAL's recorded idle RSS plus 112 MB exceeds 192 MB, or an OOM-kill of the API container is logged during an upload
- Override: —
- Outcome: open

### R2-3 — An upload holds its database connection for the whole body read and lock wait
- Trigger: many slow uploads in flight → the pool (5 + 10) is exhausted → other endpoints fail after 30 s
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=M/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a QueuePool timeout is logged while uploads or URL fetches are in flight, or the upload and from-url semaphores together approach the pool size
- Override: —
- Outcome: open

### R2-4 — Concurrent upload bodies are bounded only by the connection pool
- Trigger: several 10 MB uploads in flight beside a decode → resident bodies plus the decode peak exceed the container limit
- Scores: trigger=concrete (triager: was plausible), impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (5ecd446)

## Round 3 — 2026-11-08, unit review of U2 (DELIVERY.md §5 point 3), reviewed at 383d3b1

Envelope question (bound concurrent fetches) answered by (a) above.

### R3-1 — A TLS error after the headers escapes fetch() as a 500
- Trigger: an https image server sends a bad TLS record mid-body → raw ssl.SSLError passes the fetcher → 500 instead of url_fetch_failed
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: an unhandled ssl.SSLError (or any non-FetchError exception) from the fetcher appears in the error log for POST /api/images/from-url
- Override: —
- Outcome: open

### R3-2 — The 4-thread DNS pool is a shared choke point; cancelled lookups keep their thread
- Trigger: several fetches to hosts with stalling DNS → threads stay busy → healthy fetches time out
- Scores: trigger=plausible, impact=degraded-ux, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: the fetch log shows timeouts on normally healthy hosts clustered around a slow-resolving host, or U5's from-url semaphore is sized above the 4 DNS threads
- Override: —
- Outcome: open
