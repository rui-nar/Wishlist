# Gift images

## Problem

A gift has no picture, so invitees browsing a list read titles only, and the
gift card's image slot always shows its placeholder. `docs/NEEDS.md` ("Gifts")
lists an image among the first release's gift properties, and the owner
specified how it is added (2026-11-08): the owner chooses **select an image**
from the device, gives an **image URL**, or **pastes an image** from the
clipboard. One image per gift, replaceable and removable. An image from a URL
is downloaded once by the server and kept as a copy, so the shop never learns
who looks at the list. Reading the image from a shop page link is later (a
spike is running separately).

Images are the first files the app writes, so this plan also settles what the
DevOps foundation left open for them: the purge rule against dump retention
(deferred review finding R2-5, `docs/reviews/DEVOPS_FOUNDATION_PLAN.md`).

The owner asked for this to be planned and built without being consulted;
every choice below is taken with its reason and the alternative it rules out.

## Current state

- `server/app/lists/`: `Gift` (`models.py`) has title, description, links and
  price; `GiftOut` and `SharedGiftOut` (`schemas.py`) are the owner's and the
  invitee's gift models; `access.py` resolves every object through
  `owned_list`, `owned_gift`, `visible_occasion` and `owned_occasion`, and
  answers 404 for anything hidden. Endpoints are sync `def` handlers, one
  transaction per request (`app/db.py`, `DbSession`).
- `server/app/settings.py`: `media_dir` (`MEDIA_DIR`, `/app/media` in the
  image, a bind mount on the VPS owned by uid 10001). `main.py` creates it at
  start and `/api/health` checks it is writable. Nothing writes to it yet.
- Account deletion: `DELETE /api/me` (`accounts/router.py`) calls
  `lists/deletion.py`, which deletes the lists the user owns alone; gifts,
  occasions and memberships go by foreign-key cascade.
- Third-party calls: only Google sign-in (`accounts/google.py`), built in
  `create_app` and held in `app.state`, replaced by a fake in tests. `requests`
  is a runtime dependency; `httpx` is a dev dependency (the test client).
  Pillow is not a dependency.
- Migrations: `server/alembic/versions/`, head `efc657e64bf8`
  (occasions and members). `tests/test_migrations.py` checks upgrade and
  downgrade on a scratch database.
- Role matrix: `server/tests/lists/test_roles.py` calls every route under
  `GUARDED_PREFIXES` for every actor (owners of a "for me" and a "for someone
  else" list, invitees of the first and the second occasion, a removed
  invitee, a stranger, signed out), scans every JSON body for ids the caller
  may not see, and fails when a route has no row (`ENDPOINTS` or
  `COVERED_ELSEWHERE`).
- Deployment (`deploy/prod/docker-compose.yml`, `docs/DEPLOYMENT.md`): the app
  is limited to 256 MB in PROD and 192 MB in VAL. The `backup` service dumps
  PROD nightly to `/opt/wishlist/backups/wishlist_<YYYY-MM-DD>.dump` (999:999,
  mode 700) and keeps the **30 newest dumps**, so after an outage they reach
  further back than 30 days. VAL has no backups and is seeded from PROD,
  media hard-linked. DevOps plan D18 set two binding rules for media: files
  are never modified ("named by their content hash"), and a file is purged
  only once unreferenced for longer than the dump retention.
- Client: `ApiClient` (`client/lib/src/api/api_client.dart`) sends JSON only,
  with a 10 s timeout. `GiftCard` (`design/widgets/gift_card.dart`) already
  takes an `ImageProvider` shown at 64 px, with a placeholder when null. The
  gift form (`lists/gift_form_screen.dart`) edits title, description, price
  and links; there is no gift details screen (owners tap a card to edit,
  invitees see the description). `shared/join_browser_web.dart` /
  `join_browser_stub.dart` are the conditional-import pattern for web-only
  code.

## Decisions

### Storage and processing

- **D1 — Upload first, attach on save.** An image is sent on its own
  (`POST /api/images` with the bytes, or `POST /api/images/from-url`) and
  becomes a **pending image** belonging to its uploader. The gift form shows
  the server's processed version as the preview, and saving the gift attaches
  it (`image_id` in the gift's create or update body). Reasons: adding a gift
  and its image is one atomic save; the preview is the server's re-encoded
  WebP, so every source (a HEIC refused, a URL, a paste) previews the same way
  on every platform; and a future "image from a shop link" can propose a
  pending image while the form is open. Rules out image endpoints on the gift
  (`PUT /api/gifts/{id}/image`), which need the gift to exist first: adding a
  gift with an image would be two requests that can half-fail, and a URL
  image could not be previewed before saving.
- **D2 — Tables.** One migration:
  - `images`: `id` (UUID, random; also the file name), `uploaded_by` (FK
    `users`, `ON DELETE SET NULL`, nullable, indexed), `width`, `height` (of
    the full version), `created_at`.
  - `gifts.image_id`: nullable FK `images.id` with the default `NO ACTION`
    (the database refuses to delete an image row a gift still points at),
    unique (one gift per image, one image per gift).
  - `media_orphans`: `name` (the file stem, primary key), `first_seen_at`.
    The purge's memory (D9).

  `uploaded_by` is `SET NULL`, not `CASCADE`: with co-owners, an image one
  co-owner uploaded stays on the gift when that co-owner deletes their
  account. Rules out image columns on `gifts` (a pending image has no gift)
  and storing bytes in PostgreSQL (DevOps D18: every dump would carry them).
- **D3 — Files.** `<media_dir>/gifts/<id hex>.webp` (full) and
  `<id hex>.thumb.webp`, written to a temporary name in the same directory and
  renamed into place, never modified afterwards, never served from disk by
  name (D7). The name is random, not the content hash D18 asked for: what D18
  needs is that a file never changes (seeding hard-links PROD's files into
  VAL), which a random name gives as well; a random name also makes each file
  belong to exactly one image row, so its lifecycle is one owner's and never
  shared across users, and an id in a URL says nothing about the content.
  Rules out content hashes (deduplication saves nothing measurable at this
  scale and would make one file referenced from several users' gifts).
  `docs/DEPLOYMENT.md` "Media" is updated to say so.
- **D4 — Processing (Pillow, a new dependency).**
  - Input: at most **10 MB** of bytes (413 beyond). Formats allowed: JPEG,
    PNG, WebP, GIF (first frame), passed to `Image.open(formats=...)` so no
    other decoder ever runs. Everything else, SVG and HEIC included, is
    refused (422 `image_unsupported`).
  - Pixel caps, checked from the header before decoding (Pillow's own bomb
    check replaced by ours): JPEG up to 100 MP, decoded through `draft()` at
    the smallest scale still at least 1600 px on the longest side; other
    formats up to 4096 × 4096 (16.8 MP). Above: 422
    `image_too_many_pixels`, without decoding.
  - Orientation from EXIF applied (`ImageOps.exif_transpose`); an embedded ICC
    profile converted to sRGB (`ImageCms`); then nothing of the original's
    metadata is written: no EXIF (GPS included), XMP, ICC or comments.
  - Output: **WebP**, quality 80: the full version with its longest side at
    most 1600 px (never upscaled), alpha kept; a **thumbnail** cropped to the
    centre square, 256 × 256 (the gift card shows 64 px squares, up to 4×
    device pixels). Rules out JPEG output (no alpha for transparent product
    pictures, larger files); browsers and Flutter decode WebP on all three
    platforms.
  - Memory: the app is limited to 256 MB (PROD) and 192 MB (VAL). The caps
    above bound one decode to about 64 MB; a process-wide lock lets **one
    image** be decoded at a time, and a request that waits more than 30 s gets
    503 `image_busy`. The decode runs off the event loop. Rules out raising
    the container limits blind; Definition of done measures it on VAL.
- **D5 — HEIC is converted by the client, not accepted by the server.**
  Phones produce HEIC. `pillow-heif`'s wheels bundle x265 and are GPLv2 as a
  whole, and the image is published on GHCR; its decode-only sibling
  `pi-heif` is discontinued; libheif has a history of memory-safety CVEs on
  untrusted input. So the server refuses HEIC with `image_unsupported`, and
  the client picks photos with `image_picker`'s `maxWidth`/`maxHeight` 2048
  and `imageQuality` 90, which re-encode the pick before upload. iOS Safari
  already converts HEIC to JPEG for file inputs. If a device check shows a
  HEIC upload still arriving, client-side conversion is an open decision, not
  `pillow-heif`.

### Fetching a URL

- **D6 — A safe fetcher, generic, in its own module.** `app/safe_fetch.py`,
  built in `create_app` into `app.state.url_fetcher` and replaced by a fake
  in endpoint tests (as `google_verifier` is), with `httpx` moved to the
  runtime dependencies. One call, `fetch(url, accept, max_bytes)`, returning
  bytes and content type, or raising `FetchRefused` (`url_not_allowed`) or
  `FetchFailed` (`url_fetch_failed`):
  - URL: at most 2048 characters, `http` or `https`, no user info, port 80 or
    443 (explicit or default).
  - The host is resolved once per hop (`getaddrinfo`); **every** address it
    resolves to must be allowed, else refused. Allowed means a global unicast
    address: not private, loopback, link-local, multicast, reserved,
    unspecified, shared (100.64/10), nor IPv6 site-local or unique-local; for
    an IPv4-mapped, 6to4, Teredo or NAT64 (`64:ff9b::/96`, `64:ff9b:1::/48`)
    address, the embedded IPv4 address must be allowed too.
  - **Pinning:** the connection goes to the vetted address itself (the IP in
    the request URL, the original `Host` header, and for https the
    `sni_hostname` request extension, which httpx also uses to verify the
    certificate's hostname). A second DNS answer can never change where the
    connection goes.
  - **Redirects:** not followed by httpx; up to 3 handled by the fetcher,
    each `Location` resolved against the current URL and vetted from scratch
    (scheme, port, resolution, addresses).
  - Timeouts: 5 s to connect, 10 s between reads, 20 s for the whole fetch
    across hops.
  - Response: status 200 only; `Content-Type` must be in `accept`; a
    `Content-Length` above `max_bytes` is refused before reading; the body is
    streamed and cut at `max_bytes` (counted after any content decoding).
  - No proxy from the environment (`trust_env=False`), no cookies, no
    credentials, `Accept` set to the accepted types, a fixed `User-Agent`
    (`Wishlist/<version>`). The log line names the host and the outcome,
    never the full URL (it may carry tokens).

  For images: `accept` = JPEG, PNG, WebP, GIF; `max_bytes` = 10 MB; the bytes
  then go through D4 exactly as an upload. Rules out `requests` (no supported
  way to pin the connection to a vetted address while verifying TLS for the
  hostname) and following redirects automatically.

### Serving and access

- **D7 — Images go through the API with the gift's access check.** Two read
  routes, each with a `{variant}` of `full` or `thumb`:
  - `GET /api/images/{image_id}/{variant}`: the uploader, for a pending
    image; an owner of the list, for an image attached to its gift.
  - `GET /api/occasions/{occasion_id}/images/{image_id}/{variant}`: an owner
    or an invitee of the occasion (`visible_occasion`), for an image attached
    to a gift shown in that occasion (today, a gift of the occasion's list).

  Anything else is 404 with the API's usual body, the same as a random id.
  An image no longer attached (replaced, removed) is 404 on both routes.
  Invitees go through the occasion, as every invitee read does today, so
  hidden gifts (scoped to an occasion) will reuse the occasion view's rule
  instead of a second, list-wide definition of what an invitee sees. Rules
  out one route with a new `visible_gift` rule ("member of any occasion of the
  list"), which would have to be kept in step with the occasion view.

  The server, not the client, writes the paths: the owner's models carry
  `/api/images/...`, the invitee's `/api/occasions/{id}/images/...`. A later
  change of routes needs no client change (REVIEW.md E5).
- **D8 — Caching.** The path contains the image id, which changes with every
  new image, so a response never changes: `Cache-Control: private,
  max-age=31536000, immutable`, an `ETag`, `Content-Type: image/webp`,
  `X-Content-Type-Options: nosniff`. `private` keeps shared caches out
  (authenticated content). The client loads bytes through `ApiClient` with
  the bearer token (an `ImageProvider`, D12), which works the same on web and
  mobile; Flutter's image cache keeps decoded images by path, and on the web
  the browser's HTTP cache also applies. A removed invitee keeps what their
  browser already cached; they had seen it.

### Lifecycle and purge

- **D9 — References go with the database; files go late.** Replacing or
  removing a gift's image changes `gifts.image_id`; deleting a gift, a list or
  an account deletes the gift row by cascade. None of these touches a file or
  an `images` row. A periodic job then:
  1. deletes `images` rows no gift points at and created more than **48 h**
     ago (a pending image can be attached for **24 h**, `image_expired`
     after, so the job never races an attach);
  2. for each file stem under `gifts/`: if an `images` row has that id, the
     file is live and any `media_orphans` row for it is deleted (a restored
     dump can bring a row back); otherwise it is an orphan, recorded with
     `first_seen_at = now` if not yet recorded;
  3. deletes an orphan's two files, then its record, when
     **`first_seen_at` is earlier than the horizon**;
  4. deletes orphan records whose files are gone, and temporary files older
     than a day; any other name is left alone.

  **The horizon** is the snapshot time of the oldest kept dump, bounded from
  below: the earliest, over every `*.dump` file in the backup directory, of
  its modification time and (when the name has one) the date in its name at
  00:00 UTC, minus one day for the dump's own duration. With no backup
  directory configured, an unreadable one, or no dump in it, there is no
  horizon and **nothing is purged** (DEV, VAL; a misconfigured PROD only
  grows).

  Why it is safe: a dump can point at a file only through an `images` row.
  A file is purged only if no row has existed for it since `first_seen_at`,
  and that is earlier than the snapshot of every kept dump, so no kept dump
  has the row. The rule counts dumps, not days: after a backup outage, the
  30 kept dumps reach back further and the horizon moves back with them. This
  closes R2-5. Manual copies with another name in the directory
  (`kept_<date>.dump`, `before-restore.dump`) count too, while they are
  there; copies taken off the host do not. Rules out a fixed age in days
  (R2-5's failure) and deleting files in the request path.
- **D10 — The job runs in the app process.** A daemon thread started by the
  lifespan only when `BACKUP_DIR` is set: first run 10 minutes after start,
  then every 24 h, stopped at shutdown. It is the one process holding the
  database, the media directory and the code that knows the schema (REVIEW.md
  E1: one API process, so one job). PROD's compose file mounts
  `/opt/wishlist/backups` read-only at `/app/backups` and sets
  `BACKUP_DIR=/app/backups`; the directory becomes `999:10001` mode 750, so
  the app can list dumps and read their dates but not their content (each
  stays 600). Each run logs one line: `media purge: horizon=<iso|none>
  orphans=<n> purged=<n> rows_released=<n>`, or `media purge: skipped
  (<reason>)`. The logic is a function of the database, the two directories
  and a clock, tested directly with pytest. Rules out a compose service of
  its own (another container to deploy and watch for one daily call) and the
  backup service (shell only, no access to the schema, another uid on the
  media).

### API

- **D11 — Endpoints.** All require a session.

  | Method and path | Who | What |
  |---|---|---|
  | `POST /api/images` (body: the image bytes, any `Content-Type`) | anyone signed in | 201 pending image |
  | `POST /api/images/from-url` `{"url"}` | anyone signed in | 201 pending image, fetched by D6 |
  | `GET /api/images/{image_id}/{variant}` | uploader (pending), owners (attached) | WebP bytes |
  | `GET /api/occasions/{occasion_id}/images/{image_id}/{variant}` | owners and invitees of the occasion | WebP bytes |
  | `POST /api/lists/{id}/gifts`, `PATCH /api/gifts/{id}` | owner | gain `image_id`: absent unchanged, `null` removes, an id attaches |

  A pending image is `{"id", "width", "height", "url", "thumb_url"}`.
  `GiftOut` and `SharedGiftOut` gain `image`: the same object, or `null`.
  Attaching requires an image the caller uploaded, not attached to any gift,
  and less than 24 h old; anything else is 422 `image_not_attachable`, the
  same answer whatever the reason, so another user's image id cannot be
  probed.

  Errors carry a stable code for the client's messages: `{"detail": "<code>"}`
  with 413 `image_too_large`; 422 `image_unsupported`,
  `image_too_many_pixels`, `url_not_allowed`, `url_fetch_failed`,
  `image_not_attachable`, `image_expired`; 503 `image_busy`. A 404 keeps the
  API's `"Not found"`.

  An upload is read as a stream and cut at 10 MB + 1 byte; a
  `Content-Length` above 10 MB is refused before reading.
- **D12 — Hook for "image from a shop link".** Not designed here. What keeps
  it open: the fetcher is generic (any `accept`, any cap), the pipeline is a
  function from bytes to a pending image (`app/media/images.py`), and a pending
  image is what the form attaches. A later `POST /api/images/from-shop-link`
  can fetch the page with the same fetcher, find an image URL, and end in the
  same pipeline. Nothing in the schema records where an image came from.

### Client

- **D13 — Loading.** `ApiImage`, an `ImageProvider` keyed by path, fetches
  through `ApiClient.getBytes` (bearer token, 30 s timeout); a failure shows
  the card's placeholder. Rules out `Image.network` (headers are not sent on
  every web renderer) and `cached_network_image` (header support differs per
  platform; disk caching belongs to the offline plan).
- **D14 — The gift form's image section.** Above the title: the preview (the
  pending or current image, full version, at most 200 px tall, else the
  placeholder), and the actions **Choose image**, **Image URL**, **Paste
  image**, and **Remove** when there is one. Choosing, a URL or a paste
  uploads at once and shows the server's preview with a progress indicator;
  Save sends `image_id` (or `null` after Remove). Files over 10 MB are refused
  by the client before upload, with the server's message.
  - Choose: `image_picker` (`pickImage(source: gallery)`, D5's options) on
    web, Android and iOS. Rules out `file_picker` (no resizing, so 12 MP
    photos would upload whole).
  - Image URL: a dialog with one field (`http`/`https` checked as for links),
    then `POST /api/images/from-url`.
  - Paste: `pasteboard` (`Pasteboard.image`) for the button on all three
    platforms (Android needs a `FileProvider` declared). On the web the form
    also listens to the browser's `paste` event (Ctrl/Cmd+V), which reads
    clipboard images without a permission prompt in every browser; the button
    uses the async clipboard API, which may prompt and is limited in Firefox,
    so when it finds nothing the message suggests Ctrl/Cmd+V. Rules out
    `super_clipboard` (native Rust binaries and the Android NDK in every
    build for one button).
- **D15 — Showing images.** `GiftCard` shows the thumbnail; tapping the image
  opens a full-screen viewer (`showImageViewer`, a design widget: the full
  version in an `InteractiveViewer`, a close button) for owners in the list
  and invitees in the occasion view; the rest of the card keeps its tap. No
  separate gift details screen is added. Strings in English and French.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **New outbound trust boundary: the server fetches URLs a user typed.**
  Every URL, every DNS answer (including one that changes between two
  lookups) and every redirect is hostile (E2). The server must never connect
  to a non-global address (private, loopback, link-local including
  169.254.169.254, multicast, reserved, unspecified, shared, IPv6 ULA and
  site-local, or IPv4 embedded in mapped, 6to4, Teredo or NAT64 forms), never
  on a port other than 80 and 443, and never send credentials, cookies or a
  proxy's. Rules in D6. In: DNS rebinding between vetting and connecting,
  redirect chains, slow or endless bodies, lying `Content-Length`,
  compressed bodies. Out: a public host serving hostile content (handled as
  an untrusted image, below), and using the fetcher to send requests to
  public hosts (any signed-in user can; no rate limit at a few hundred users,
  each fetch capped by D6; revisit with abuse).
- **Untrusted image bytes reach a decoder.** Uploads and fetched bodies are
  hostile: polyglots, decompression bombs, malformed headers, huge
  dimensions, animated files, metadata with personal data. Only Pillow's
  JPEG, PNG, WebP and GIF decoders may run; dimensions are checked before
  decoding; output is re-encoded from pixels only.
- **Memory.** One API process within 256 MB (PROD) / 192 MB (VAL): concurrent
  uploads are a normal case (E1) and must not get the container OOM-killed;
  they queue on D4's lock or get 503.
- **Files on disk** are written only by the app, under `gifts/` with names it
  chose; no path from a request ever reaches the filesystem.
- **Access.** Image routes follow REVIEW.md F1 like any read: 404 for anything
  hidden, identical to a random id. Images are owner content: the surprise
  rule is not touched, and nothing here records or shows invitee activity.
- **Retention.** An image leaves the disk only after the oldest kept dump no
  longer references it (D9): for a deleted account, as long as its rows stay
  in the dumps. This matches the dumps themselves.
- **Concurrency.** The purge runs concurrently with requests: an attach, a
  replace or a restore at the same moment must never get a live file deleted
  (D9's 24 h / 48 h split and its "row exists" check).

## Boundaries crossed

- **Schema (F4):** `images`, `media_orphans`, nullable `gifts.image_id`, in
  one migration that leaves the previous release working (new tables, a
  nullable column it ignores). Downgrade drops them.
- **API contract (F4):** the routes of D11; `image` added to `GiftOut` and
  `SharedGiftOut`; `image_id` accepted by gift create and update. Additive:
  shipped clients ignore `image` and never send `image_id`, so an old client
  editing a gift leaves its image as it is. The paths in `url`/`thumb_url` are
  server-chosen (D7) and may change without a client release.
- **Stored data:** image files under `MEDIA_DIR/gifts/`, kept per D9.
- **Deployment:** `/opt/wishlist/backups` becomes `999:10001` mode 750 and is
  mounted read-only into PROD's app. An existing host must change the
  directory before this release; without it the purge logs `skipped` and
  purges nothing (safe). `docs/DEPLOYMENT.md` gains the step.
- **DevOps D18 amended:** file names are random, not content hashes (D3); the
  purge is relative to the oldest kept dump, not 30 days (D9).

## Conventions

- Every new route has a row in `test_roles.py` (`ENDPOINTS` or
  `COVERED_ELSEWHERE` with its own by-role test); `/api/images` joins
  `GUARDED_PREFIXES`.
- Image errors are `{"detail": "<code>"}` with D11's codes; the client maps
  each code to an ARB string and never shows server text.
- Limits are named constants in one place on each side (10 MB, 1600 px, 256 px,
  caps, 24 h / 48 h).
- Test images are generated in the tests with Pillow (server) or as byte
  literals (client); no binary fixtures committed except goldens.
- Goldens are regenerated with `.\goldens.ps1` only (Linux, Docker).
- The merge commit carries a `Release-Note:` trailer ("Gifts can have a
  picture: choose one, paste one or give its web address.").
- U1, U2, U5 and U8 touch migrations, security or deletion of stored files:
  each gets a single-unit review before integration (DELIVERY.md §5.3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Storage per account (NEEDS.md "Image limits"; size and count are decided here: 10 MB in, one per gift) | Disk on the shared VPS, premium | The premium plan |
| HEIC if a device still uploads one after `image_picker`'s re-encoding (D5): add client conversion | iOS and Android picking | Before the first store release (device check) |
| Raising the app's memory limit if VAL's measurement (Definition of done) leaves under 32 MB headroom | `deploy/*/docker-compose.yml` | Before releasing to PROD |
| Off-site backups: their retention must join the horizon (D9) when they exist | Media purge | The off-site backups item of DEPLOYMENT.md |
| Image from a shop link (D12) | A new route reusing D6 and D4 | After the Amazon spike |
| Images on disk for offline reading on mobile | Client cache | The offline plan |
| VAL's media are never purged (no backups) | VAL disk | If VAL's media directory grows beyond 1 GB |

## Execution units

### Wave 1

#### U1 — Server: image pipeline, tables and pending images

- **Goal:** a signed-in user uploads image bytes and gets a pending image,
  processed per D4 and stored per D3, readable by them only.
- **Scope:** `server/app/media/__init__.py`, `server/app/media/images.py`
  (new), `server/app/media/models.py` (new), `server/app/media/router.py`
  (new), `server/app/media/schemas.py` (new), `server/app/lists/models.py`
  (`Gift.image_id` only), `server/app/main.py` (include the router),
  `server/alembic/env.py`, `server/alembic/versions/**` (one new revision),
  `server/pyproject.toml`, `server/uv.lock` (Pillow), `server/tests/media/**`
  (new).
- **Context:** D1–D4, D7 (first route only), D8, D11; `docs/REVIEW.md` §2.
  Example to follow: `server/app/lists/` (models, schemas, router) and
  `server/tests/lists/test_gifts.py`; for the migration,
  `server/alembic/versions/efc657e64bf8_occasions_and_members.py`.
- **Do:**
  1. Add `pillow` (a floor, like the others). Models `Image`, `MediaOrphan`
     and `Gift.image_id` (D2); one revision; read it.
  2. `images.py`: constants (D4), `process(data) -> (full_webp, thumb_webp,
     width, height)` raising typed errors for each D11 code; the one-at-a-time
     lock with its 30 s wait; `store(media_dir, image_id, full, thumb)` with
     temporary names and rename; `ingest(db, media_dir, user, data) -> Image`.
  3. `POST /api/images`: an async handler that reads the stream up to 10 MB
     + 1 (413 before reading when `Content-Length` says more), then runs
     `ingest` off the event loop; 201 with the pending image of D11 (`url`
     and `thumb_url` under `/api/images/`).
  4. `GET /api/images/{image_id}/{variant}`: the uploader of a pending image,
     or an owner of the list of the gift it is attached to (`owns_list`);
     otherwise 404 with `not_found()`. Headers of D8. A row whose file is
     missing: 404 and a warning log (guard).
  5. Error bodies `{"detail": "<code>"}`.
- **Acceptance:** `uv run --directory server ruff check`; `alembic upgrade
  head` then `alembic check`; `pytest` passes, including new
  `tests/media/test_images.py` and `tests/media/test_upload.py`:
  JPEG, PNG, WebP, GIF accepted and stored as two WebP files of D4's sizes;
  orientation 6 applied (width and height swapped); a JPEG with EXIF GPS and
  a PNG with an ICC profile give outputs with no `exif`, `xmp` or
  `icc_profile` in `Image.open(...).info`; a transparent PNG keeps alpha;
  a 300 × 200 image is not upscaled; text, SVG and a HEIC header → 422
  `image_unsupported`; a hand-built PNG whose header declares 20000 × 20000
  → 422 `image_too_many_pixels` without decoding; a 10 MB + 1 body → 413,
  with and without `Content-Length`; the lock held by another thread → 503
  `image_busy` after the wait (wait shortened in the test); another user and
  a random id → the same 404; signed out → 401; response headers of D8;
  `test_migrations.py` still passes (upgrade, downgrade).
- **Out of scope:** attaching to gifts, invitee routes, URL fetching, the
  purge, client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); Pillow's `draft()` or
  format restriction does not behave as D4 assumes; peak memory of one
  4096 × 4096 PNG decode clearly exceeds 100 MB.
- **Depends on:** —

#### U2 — Server: safe URL fetcher

- **Goal:** `app/safe_fetch.py` fetches a URL per D6 and refuses every
  address, redirect and response the envelope excludes.
- **Scope:** `server/app/safe_fetch.py` (new),
  `server/tests/test_safe_fetch.py` (new).
- **Context:** D6 and the Review envelope; httpx's `sni_hostname` request
  extension. Example to follow: `server/app/accounts/google.py` (a
  third-party call behind a small class, constructed once) and
  `server/tests/accounts/test_google_verifier.py`.
- **Do:**
  1. `address_allowed(ip) -> bool` (D6's list, embedded IPv4 checked).
  2. `SafeFetcher(resolve=..., address_allowed=..., ports=(80, 443),
     timeouts...)`: the defaults are production's; tests inject a resolver,
     ports and, for local servers, a predicate.
  3. `fetch(url, accept, max_bytes) -> (bytes, content_type)`, raising
     `FetchRefused` / `FetchFailed`, per D6: URL checks, resolve and vet,
     pinned connection, manual redirects (3), deadline, status, type, size.
  4. Log host and outcome only.
- **Acceptance:** `ruff check`; `pytest` passes, including
  `test_safe_fetch.py`: a table for `address_allowed` (10.0.0.1, 172.16.0.1,
  192.168.1.1, 127.0.0.1, 169.254.169.254, 0.0.0.0, 100.64.0.1, 224.0.0.1,
  255.255.255.255, ::1, fe80::1, fc00::1, fec0::1, ::ffff:127.0.0.1,
  ::ffff:10.0.0.1, 2002:7f00:1::1, 2001:0:4136:e378:8000:63bf:80ff:fffe
  (Teredo of 127.0.0.1), 64:ff9b::7f00:1 refused; 8.8.8.8 and 2606:4700::1111
  allowed); `ftp:`, user info, port 8080, a 2049-character URL refused;
  with local HTTP servers on 127.0.0.1 and 127.0.0.2 and an injected
  resolver and predicate allowing only 127.0.0.1: a redirect to the other
  server (by name and by literal) refused and that server receives nothing; a
  resolver answering the allowed address first and the refused one second
  (rebinding) → the request reaches the allowed server only; a host resolving
  to one allowed and one refused address → refused; 4 redirects → failed;
  404, `text/html`, a `Content-Length` over the cap, a body over the cap
  without `Content-Length`, a server that stalls past the deadline → failed
  within the deadline; for https, a recording transport shows the request
  sent to the IP with `Host` and `sni_hostname` set to the name; no
  `Cookie` or `Authorization` header sent; `HTTP_PROXY` in the environment
  ignored.
- **Out of scope:** the endpoint, image processing, shop pages.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); httpx cannot pin the
  connection while verifying the certificate for the hostname; 127.0.0.2 is
  not usable on the test platform (say which alternative you used).
- **Depends on:** —

#### U3 — Infrastructure: backups readable by the purge, runbook

- **Goal:** PROD's app can list (not read) the dumps, and the runbook
  describes images, the purge and the upgrade step.
- **Scope:** `deploy/prod/docker-compose.yml`, `deploy/smoke/run.sh`,
  `docs/DEPLOYMENT.md`.
- **Context:** D3, D9, D10, Boundaries crossed. Example to follow: the
  existing media mount and the backups directory lines in the same files.
- **Do:**
  1. Compose (PROD only): app mounts `/opt/wishlist/backups:/app/backups:ro`
     and sets `BACKUP_DIR: /app/backups` under `environment:` (never in
     `.env`, like `MEDIA_DIR`), with a comment citing this plan.
  2. `run.sh`: create the backups directory `999:10001` mode 750; after the
     first dump, check the app container can list `/app/backups` and cannot
     read a dump (`python -c` in `docker compose exec app`).
  3. `DEPLOYMENT.md`: the table in "What Wishlist adds", step 4's
     `install -d`, Backups "Access" (the app lists dates, cannot read), Media
     (random names per D3, the purge rule of D9 stated against the oldest kept
     dump, manual copies count, off-host copies do not, the log line of D10,
     VAL never purged), the daily check (grep the purge line), "Later
     releases" (on an existing host, `sudo chgrp 10001 /opt/wishlist/backups
     && sudo chmod 750 /opt/wishlist/backups` before deploying this release),
     Open items (R2-5 checked, pointing at D9).
- **Acceptance:** `shellcheck deploy/smoke/run.sh`; the `deploy-smoke`
  workflow passes on the branch; `docker compose -f
  deploy/prod/docker-compose.yml config` is valid.
- **Out of scope:** VAL's compose file (no backups), `backup.sh`, the purge
  code.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the app cannot list
  the directory without changing the dumps' own mode.
- **Depends on:** —

#### U4 — Client: bytes over the API, `ApiImage`, card and viewer

- **Goal:** the client can send and fetch bytes with the session, show an
  API image in `GiftCard`, and open it full screen.
- **Scope:** `client/lib/src/api/api_client.dart`,
  `client/lib/src/api/api_image.dart` (new),
  `client/lib/src/design/widgets/gift_card.dart`,
  `client/lib/src/design/widgets/image_viewer.dart` (new),
  `client/lib/l10n/*.arb`, `client/test/api/**`, `client/test/design/**`,
  `docs/DESIGN.md`.
- **Context:** D8, D13, D15; `docs/DESIGN.md` Components. Example to follow:
  `api_client.dart` and its tests; `privacy_banner.dart` with its widget
  test and goldens in `client/test/design/widgets/`.
- **Do:**
  1. `ApiClient`: `postBytes(path, bytes, {contentType})` → JSON object, and
     `getBytes(path)` → `Uint8List`, through `_send` with a per-call timeout
     (60 s upload, 30 s download); same error types.
  2. `ApiImage(api, path)`: `ImageProvider` keyed by path, decoding the
     bytes of `getBytes`.
  3. `GiftCard`: an `onImageTap` callback (44 px hit area kept), and the
     placeholder when the image fails to load.
  4. `showImageViewer(context, image, {semanticLabel})`: full-screen dialog,
     `InteractiveViewer`, a close button with a tooltip; strings EN/FR.
  5. `DESIGN.md`: the viewer in the custom widgets table; the card's image
     tap and fallback.
- **Acceptance:** `flutter analyze`; `flutter test`; tests: `postBytes` sends
  the bytes, content type and bearer token; error codes surface as
  `ApiException` with the body; `getBytes` returns the bytes; `ApiImage` with
  equal paths are equal and a 404 resolves to an error; `GiftCard` with a
  failing provider shows the placeholder, `onImageTap` fires; the viewer
  closes; ARB parity test passes; goldens (card with an image, viewer) light
  and dark, generated with `.\goldens.ps1` and passing `.\goldens.ps1
  -Check`; `flutter build web --release`.
- **Out of scope:** repositories, screens, picking or pasting.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); an `ImageProvider`
  over `ApiClient` cannot be made to work under `flutter test`.
- **Depends on:** —

### Wave 2

#### U5 — Server: images on gifts, invitee route, fetch endpoint, role matrix

- **Goal:** owners attach, replace and remove a gift's image; owners and
  invitees read it; images can come from a URL; every route is in the role
  matrix.
- **Scope:** `server/app/lists/**`, `server/app/media/**` (not
  `purge.py`), `server/app/main.py` (`app.state.url_fetcher`),
  `server/pyproject.toml`, `server/uv.lock` (httpx to runtime),
  `server/tests/lists/**`, `server/tests/media/**`, `server/tests/conftest.py`
  (the fake fetcher, if shared).
- **Context:** D1, D6, D7, D11, D12; Conventions. Example to follow:
  `server/app/lists/router.py` (`_gift_out`, `_shared_gift_out`,
  `get_occasion`) and `server/tests/lists/test_roles.py`.
- **Do:**
  1. `GiftCreate`/`GiftUpdate.image_id` and the attach rule of D11 (lock the
     image row; `image_not_attachable`, `image_expired`).
  2. `image` on `GiftOut` (owner paths) and `SharedGiftOut` (the occasion's
     paths), wherever those models are built.
  3. `GET /api/occasions/{occasion_id}/images/{image_id}/{variant}` per D7,
     through `visible_occasion`.
  4. `POST /api/images/from-url`: `app.state.url_fetcher` (a `SafeFetcher`
     built in `create_app`) then `ingest`; refused → 422 `url_not_allowed`,
     failed → 422 `url_fetch_failed`.
  5. `test_roles.py`: `/api/images` in `GUARDED_PREFIXES`; the scenario's
     gifts get an image; rows for both image GET routes (owner 200;
     occasion route also invitee 200; everyone else 404, identical to random
     ids); `POST /api/images` and `/from-url` in `COVERED_ELSEWHERE` with
     by-role tests; the JSON scan skipped for non-JSON bodies only; the
     other list's image ids in `hidden_from`.
- **Acceptance:** `ruff check`; `alembic upgrade head` then `alembic check`
  (no new revision); `pytest` passes, including: add a gift with an image;
  replace (the old image's routes → 404); remove with `null`; omit
  `image_id` → unchanged; attach another user's pending image, an attached
  one, a random id → the same 422 `image_not_attachable`; a pending image
  older than 24 h → 422 `image_expired`; the invitee model's paths are the
  occasion's and work for its invitee, not for an invitee of another
  occasion of the list, a removed invitee or a stranger; deleting the gift,
  the list or the account makes both routes 404; `from-url` with a fake
  fetcher returning a PNG → 201, raising each error → its code; the route
  coverage guard passes.
- **Out of scope:** the purge, shop links, client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a role case cannot be
  expressed with the scenario.
- **Depends on:** U1, U2.

#### U6 — Client: image models and display

- **Goal:** owners see gift thumbnails in their list and invitees in the
  occasion view, and tapping one opens the full image.
- **Scope:** `client/lib/src/lists/lists_repository.dart`,
  `client/lib/src/lists/list_detail_screen.dart`,
  `client/lib/src/shared/shared_repository.dart`,
  `client/lib/src/shared/occasion_screen.dart`, `client/test/lists/**`,
  `client/test/shared/**`.
- **Context:** D7, D11, D13, D15. Example to follow:
  `list_detail_screen.dart` and `client/test/lists/list_detail_screen_test.dart`
  with `client/test/lists/support/fake_lists_server.dart`.
- **Do:**
  1. `GiftImage` (`id`, `width`, `height`, `url`, `thumbUrl`) on `Gift` and
     `SharedGift`, null when absent; `PendingImage`; `uploadImage(bytes)`,
     `imageFromUrl(url)` on `ListsRepository`; `GiftDraft` gains the image
     change (unchanged, attach id, remove), serialised per D11.
  2. List detail and occasion view: `ApiImage(thumbUrl)` on each card,
     `onImageTap` → viewer with the full `url`.
  3. The fake server serves images and the new endpoints.
- **Acceptance:** `flutter analyze`; `flutter test`; tests: parsing with and
  without `image`; the draft sends no `image_id` when unchanged, `null` on
  remove, the id on attach; the image paths used are the ones from the
  response; tapping a thumbnail opens the viewer, tapping the card elsewhere
  keeps its old behaviour; goldens of list detail and occasion view with an
  image, light and dark, via `.\goldens.ps1` and `.\goldens.ps1 -Check`;
  `flutter build web --release`.
- **Out of scope:** the gift form, picking, pasting.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U4 (API shapes from D11; U5 not needed to start).

### Wave 3

#### U7 — Client: the gift form's image section

- **Goal:** in the gift form the owner chooses, gives the URL of, or pastes
  an image, sees the preview, replaces or removes it, and saving keeps it.
- **Scope:** `client/lib/src/lists/gift_form_screen.dart`,
  `client/lib/src/lists/gift_image_section.dart` (new),
  `client/lib/src/lists/paste_web.dart`, `client/lib/src/lists/paste_stub.dart`
  (new), `client/lib/l10n/*.arb`, `client/pubspec.yaml`,
  `client/pubspec.lock`, `client/android/app/src/main/AndroidManifest.xml`,
  `client/android/app/src/main/res/xml/**`, `client/ios/Runner/Info.plist`,
  `client/test/lists/**`.
- **Context:** D5, D11, D14. Example to follow: `gift_form_screen.dart` and
  its tests; `client/lib/src/shared/join_browser_web.dart` /
  `join_browser_stub.dart` for web-only code; the url_launcher platform fake
  in the tests for faking a plugin.
- **Do:**
  1. Add `image_picker` and `pasteboard`; Android `FileProvider` for
     pasteboard; `NSPhotoLibraryUsageDescription` in `Info.plist`.
  2. `GiftImageSection`: preview, Choose / Image URL / Paste / Remove, busy
     state, the error message for each D11 code, the 10 MB client check.
     Picker and clipboard reader are injected (defaults: `ImagePicker`,
     `Pasteboard.image`).
  3. Web: a `paste` listener on the document while the form is open,
     forwarding the first `image/*` file to the section.
  4. Save sends the image change with the gift (one request).
  5. Strings EN/FR: the actions, the URL dialog, "No image in the
     clipboard" (with the Ctrl/Cmd+V hint on the web), each error.
- **Acceptance:** `flutter analyze`; `flutter test`; tests: each action
  uploads and shows the preview from the response; Remove then Save sends
  `null`; editing without touching the image sends no `image_id`; adding a
  gift with an image is one create request with `image_id`; each error code
  shows its message; an 11 MB pick is refused without a request; an empty
  clipboard shows the message; the paste listener's handler turns a file into
  an upload (unit test of the handler); French run of the section; goldens of
  the form with and without an image and with an error, light and dark, via
  `.\goldens.ps1` and `.\goldens.ps1 -Check`; `flutter build web --release`;
  `flutter build apk --debug` (manifest valid).
- **Out of scope:** shop-link images, cropping or editing, camera capture.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); `pasteboard` does not
  build for web or Android; `image_picker` on the web ignores the resize
  options (report it; the server still bounds the size).
- **Depends on:** U6.

#### U8 — Server: media purge

- **Goal:** unreferenced image rows and files are removed per D9, never
  before the oldest kept dump stops referencing them.
- **Scope:** `server/app/media/purge.py` (new), `server/app/settings.py`
  (`backup_dir`), `server/app/main.py` (lifespan thread),
  `server/tests/media/test_purge.py` (new), `docs/NEEDS.md` (the "Image
  limits" open question narrowed to storage per account),
  `docs/reviews/DEVOPS_FOUNDATION_PLAN.md` (R2-5 `Outcome: fixed`, pointing
  at this plan's D9).
- **Context:** D9, D10, Review envelope (Retention, Concurrency). Example to
  follow: `app.state.clock` in `server/app/main.py` (an injected clock), the
  lifespan there, and `tmp_path`-based tests such as
  `server/tests/test_health.py`.
- **Do:**
  1. `horizon(backup_dir) -> datetime | None` per D9.
  2. `purge(db, media_dir, backup_dir, now) -> counts`, steps 1–4 of D9, each
     file deleted only after re-checking in the same transaction that no row
     exists.
  3. The thread of D10, started only when `backup_dir` is set, stopped by an
     event at shutdown; the log line.
- **Acceptance:** `ruff check`; `pytest` passes, including `test_purge.py`
  with dump files dated by `os.utime`: a referenced file is never deleted; a
  new orphan is recorded, not deleted; it is deleted once every kept dump is
  more than a day newer than `first_seen_at`; R2-5: 30 dumps spanning 60 days
  and an orphan first seen 45 days ago → kept; `kept_<date>.dump` copied
  without `-p` (new mtime, old date in the name) protects by its name's
  date; no backup directory, an unreadable one, an empty one → nothing
  deleted and a `skipped` line; a row brought back (restore) clears the orphan
  record and keeps the file; unreferenced rows older than 48 h released,
  younger kept, referenced kept; temporary files older than a day removed,
  unknown names untouched; orphan records of missing files dropped; the
  thread starts only with `backup_dir` and stops within 2 s of the client's
  exit.
- **Out of scope:** off-site backups, per-account limits, VAL purging.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a case where D9's
  rule would delete a file a kept dump references.
- **Depends on:** U1, U5 (main.py), U3 (`BACKUP_DIR` contract).

## Definition of done

- On VAL, an owner adds a gift with an image chosen from the device, another
  from an image URL and a third pasted, on the web and on an Android phone;
  replaces one and removes one. An invitee of the occasion sees the
  thumbnails and opens the full image; a stranger and a removed invitee get
  404 for the same image paths.
- A URL to `http://127.0.0.1/`, to `169.254.169.254`, or to a public host
  redirecting to a private address is refused with "This address can't be
  used" (or its French text); nothing reaches the internal address.
- Stored files are WebP, at most 1600 px and 256 × 256, with no EXIF, XMP or
  ICC data; a photo with GPS data comes out without it.
- On VAL, uploading a 4096 × 4096 PNG and a 48 MP JPEG, three times each
  in parallel, leaves the app running: `docker inspect` shows
  `OOMKilled=false` and an unchanged restart count, and `docker stats` peak
  is recorded in the ledger's delivery notes.
- On PROD after release, the app's log shows a daily `media purge:` line with
  a horizon, and `docs/DEPLOYMENT.md` states the purge rule relative to the
  oldest kept dump; R2-5 is closed.
- `test_roles.py` covers every new route for every actor; all §2 checks
  pass, goldens included.
