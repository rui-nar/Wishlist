# Shush Gift: name and domain — Plan

## Problem

The app has no name of its own and no domain of its own:

- It is called "Wishlist", a generic word nobody can find, own or register as a
  store name, and in several places still Flutter's template `wishlist`.
- PROD and VAL run on two subdomains of TraxJourney's domain.

On 2026-11-11 the owner bought `shushgift.com` and decided (`docs/NEEDS.md`,
Name and domain):

- The app is called **Shush Gift**.
- PROD is at `shushgift.com`, VAL at `val.shushgift.com`, each serving the web
  client and its API under `/api` as today.
- The rename goes all the way, internal identifiers included.
- The iOS and Android ids are `com.shushgift.app` and `com.shushgift.app.val`.
- Shared links and emails open the installed app on phones.
- All of it happens as soon as the domain is live, **before the first store
  releases**, so no published build carries the old name, the old hosts or
  ids that can never change.

## Current state

- **Hosts are configuration.** No hostname is committed. The server builds
  every link from `PUBLIC_BASE_URL` (`server/app/settings.py:55`), and the
  apps get theirs from the `API_BASE_URL_VAL` / `API_BASE_URL_PROD` secrets in
  `ios-release.yml` and `android-release.yml`. Caddy's site blocks use
  placeholders (`deploy/caddy/Caddyfile.snippet`).
- **The brand is hard-coded in about a dozen user-facing places:**
  - `appTitle`, `whatIsWishlist`, `howItWorks` and
    `planPurchaseOtherAccount` in `client/lib/l10n/app_en.arb` and
    `app_fr.arb`.
  - The Android labels in `client/android/app/build.gradle.kts:74,78`.
  - `WISHLIST_DISPLAY_NAME` in `client/ios/Flutter/Identity.xcconfig` and
    `ios-release.yml:93,105`.
  - `CFBundleName` and the usage strings in `Info.plist`, and
    `InfoPlist.strings` (en, fr).
  - `client/web/index.html` and `manifest.json`, which still hold Flutter's
    template values.
  - The email subjects and bodies in
    `server/app/notifications/email_content.py`.
  - `EMAIL_SENDER_NAME` (`settings.py:67`, both deploy `.env.example`).
  - The FastAPI title and the outbound User-Agent.
- **The internal name is everywhere:**
  - The Dart package `wishlist`, imported by about 65 files.
  - `WishlistApp` and `WishlistColors`.
  - The client storage keys `wishlist.*`.
  - The Android namespace `app.wishlist`, and the Gradle properties
    `wishlistAppId` and `wishlistRequireUploadKey`.
  - The xcconfig `WISHLIST_*` variables.
  - `wishlist-server` in `pyproject.toml`.
  - The image `ghcr.io/rui-nar/wishlist` and the repository `rui-nar/Wishlist`.
  - On the VPS: `/opt/wishlist`, `/opt/wishlist-val`, `/opt/wishlist-media`,
    the compose projects `wishlist-prod` / `wishlist-val` (and their
    volumes), the database users and names `wishlist` / `wishlist_val`, the
    dumps `wishlist_<date>.dump`, and `wishlist-webhook.service`.
  - DEV and CI: the database names and `wishlist-dev`.
- **Two identifiers live outside our systems:**
  - The Stripe metadata marker `APP_MARKER = "wishlist"`
    (`server/app/billing/stripe_events.py:44`), stored on every subscription
    Checkout has created and read to recognise them.
  - The Stripe idempotency prefix `wishlist-customer-`.
- **App ids are still placeholders** (`com.example.wishlist`). Both release
  plans left the choice open (ANDROID_RELEASE_PLAN Open decisions,
  IOS_APP_PLAN).
- **No app links.** Links open in the browser (ANDROID_RELEASE_PLAN D10,
  IOS_APP_PLAN D8). On mobile, `pending_join.dart` keeps a join token in
  memory only, since no link reaches the app.
- **Routes behind links:**
  - `/join#<token>` (occasion invitations).
  - `/shared/<occasion>?gift=…` and `/account` (notification emails).
  - `/create-account#…` and `/reset-password#…` (sign-in emails).
  - `/unsubscribe#…` and `/api/unsubscribe/<token>`.
  - `/account/plan` (Stripe's return).
- `docs/DEPLOYMENT.md` "Open items" already lists the own-domain move: DNS,
  Caddy, `PUBLIC_BASE_URL`, Google origins, and redirects from the old hosts.

## Decisions

- **D1 — One host per environment, the API under `/api`.** `shushgift.com`
  (PROD) and `val.shushgift.com` (VAL). `www.shushgift.com` redirects to the
  apex. No `api.` subdomain: it would add CORS, a web API base URL and
  cross-site cookie limits for nothing at this scale (E1). The owner chose
  this on 2026-11-11.

- **D2 — The brand.** "Shush Gift" in every language. "Shush Gift VAL" for
  the VAL apps.
  - The common noun stays: a list is still a "list" (or "wishlist" where the
    text uses the word). Only the product name changes.
  - The intro, the "What is …" entry and the email texts are reworded around
    the name, not just search-and-replaced: "What is Shush Gift?", "How Shush
    Gift works", and so on.

- **D3 — Internal identifiers renamed, by one rule.** `wishlist` becomes
  `shushgift` and `Wishlist` becomes `ShushGift`:
  - Dart package `shushgift`, with `ShushGiftApp` and `ShushGiftColors`
    (`context.shushGiftColors`).
  - Android namespace `app.shushgift`, Gradle properties `shushgiftAppId` and
    `shushgiftRequireUploadKey`, xcconfig `SHUSHGIFT_*`.
  - Python project `shushgift-server`.
  - Image `ghcr.io/rui-nar/shushgift`, repository `rui-nar/shushgift`.
  - VPS: `/opt/shushgift`, `/opt/shushgift-val` and `/opt/shushgift-media`;
    projects `shushgift-prod` and `shushgift-val`; database users and names
    `shushgift` and `shushgift_val`; dumps `shushgift_<date>.dump`; and
    `shushgift-webhook.service`.
  - DEV and CI follow the same rule.

  Rules out: user-visible only. The owner chose the full rename on 2026-11-11.

- **D3a — The repository is renamed and made private** (owner, 2026-11-11).
  Renaming keeps the history, issues, pull requests, Actions secrets and
  variables and the webhook, and GitHub redirects the old URLs. Rules out a
  new repository, which would lose all of that.
  - The new package `ghcr.io/rui-nar/shushgift` is private as well, since the
    image holds the source. The VPS pulls it with the existing `ghcr.io` login
    (DEPLOYMENT.md §3, "Keep it private").
  - The free plan's 2,000 Actions minutes count macOS ten times. So the macOS
    iOS build leaves `test.yml` (pull requests). `ios-release.yml` runs on
    release tags only: `v[0-9]*`, since `v*` also matches `validation` (owner,
    2026-11-11, review R1-6). A VAL iOS build is a manual run with `app: val`.
    `android-release.yml` runs on Linux and keeps its triggers.
  - **Deploy files reach the VPS by `scp` from the owner's checkout** (review
    R1-2). The runbook's unauthenticated fetch from
    `raw.githubusercontent.com` stops working once the repository is private.
    The owner exports the files at the wanted ref with `git archive <ref>
    deploy/` and copies them into the same temporary directory. The install
    steps after that are unchanged. Rules out a GitHub token or deploy key on
    the VPS: that is one more secret there, for files the owner already has.
  - The rule "no VPS hostname, IP, user or secret committed" stays: a private
    repository can still be shared, made public again or leak.

- **D4 — Identifiers stored outside our systems stay.** The Stripe marker
  `APP_MARKER` keeps the value `"wishlist"`, with a comment saying why.
  Changing it would make the server ignore every subscription Checkout has
  already created, and the fix would be a second, accepted marker forever.
  The Stripe idempotency prefix changes, since Stripe keeps keys for
  24 hours only.
  - Plan files and review ledgers in `docs/plans/` and `docs/reviews/` keep
    the old name: they are the record (plans README), cited by path from
    code.

- **D5 — Client storage keys are renamed without migration.**
  `wishlist.session_token` becomes `shushgift.session_token`, and the same for
  `intro_seen`, `pending_join` and `join_handover`.
  - On the web, the new origin starts with empty storage anyway, so everyone
    signs in again there.
  - On phones, only test builds exist (no store release yet), so testers sign
    in once more.
  - A migration from the old keys would be code kept for a handful of
    testers.

- **D6 — The old hosts are removed right after PROD moves** (owner,
  2026-11-11: PROD has no real users yet).
  - Until then their Caddy blocks are left untouched. They proxy the same
    local ports (8010, 8011) as the new stacks, so they reach the moved
    environment, which builds every new link on the new host
    (`PUBLIC_BASE_URL`).
  - Once PROD is moved and every console is repointed (D9), both old blocks
    are deleted and Caddy reloaded. From then on, links sent before the move
    stop working.
  - A notification sent to an old host while its console is being switched
    is not lost: Stripe, Apple's App Store Server Notifications and Pub/Sub
    retry failed deliveries for days.

  Rules out a lasting redirect and `/api` proxy on the old hosts: it would be
  kept for links nobody real holds, and it would tie the domain to
  TraxJourney's.

- **D7 — App links, verified, on both platforms.**
  - **Paths that open the app:** `/join`, `/shared/*`, `/create-account`,
    `/reset-password` and exactly `/account`.
  - **Paths that stay in the browser:** `/account/plan` (Stripe's return, sold
    on the web only), `/unsubscribe`, `/legal/*`, `/api/*` and `/welcome`.
  - **Server:** two routes ahead of the web catch-all serve
    `/.well-known/apple-app-site-association` and
    `/.well-known/assetlinks.json` as `application/json`, built from
    settings, with no redirect, as Apple and Google require:
    - `APP_LINKS_APPLE_APP_IDS`: `<team id>.<bundle id>`, comma-separated.
    - `APP_LINKS_ANDROID_PACKAGE`.
    - `APP_LINKS_ANDROID_SHA256`: the Play app-signing and upload
      fingerprints, comma-separated.

    A route whose settings are empty answers 404. Each environment lists its
    own app (VAL's `.val` ids on VAL).
  - **Android:** an `autoVerify` intent filter for those paths. The host comes
    from the Gradle property `shushgiftAppLinkHost`, which the release
    workflow sets from the host of the `API_BASE_URL_*` secret. Without it,
    the filter is left out.
  - **iOS:** the Associated Domains entitlement
    `applinks:$(SHUSHGIFT_APP_LINK_HOST)`, set the same way. Without it, the
    entitlement is left out of the build.
  - **In the app:** an incoming link goes through the same router as a web
    address. A `/join#token` link fills the pending join the way the web's
    address bar does, both at cold start and while the app is running.
  - No host is committed: it comes from the same secrets as the API base URL.

- **D8 — The VPS move is a runbook procedure, VAL first, then PROD.** For each
  environment:
  1. DNS, then Caddy (D6).
  2. Stop the stack, then take a final dump.
  3. Create the new directories and `.env`, with the new database user and
     name, `PUBLIC_BASE_URL` and the app-link settings.
  4. Move the media with `mv` on the same filesystem, which keeps the
     modification times the media purge relies on.
  5. Move the kept dumps, the final one included, into the new backups
     directory as `shushgift_<date>.dump`, so the rotation, the seeding and the
     purge's horizon all find them (review R1-1).
  6. Bring up **only the `db` service** of the new compose project, which
     starts on an empty volume, and restore the final dump into it. This is
     the "Restoring PROD from a dump" procedure, with `--no-owner` and the new
     role.
  7. Only then bring up the app and the backup service. The purge's first run
     dates its horizon from the moved dumps, and the backup service's first
     dump joins them.
  8. Rename the webhook unit, and update its repository filter to
     `rui-nar/shushgift`, the exact name the hook compares (review R1-3).

  The old volume and directories stay until the new stack has run a day with
  a nightly dump, so going back is starting the old project again. Rules out
  renaming the database in place (`ALTER DATABASE … RENAME`): the compose
  project name, and with it the volume name, change anyway.

- **D9 — Every external console is repointed in the runbook, in order.** The
  hosts appear only in consoles and `.env`, so the consoles and environment
  values below are the rest of the move.
  - **DNS:** the apex, `www` and `val` records, plus Brevo's DKIM, SPF and
    DMARC.
  - **Brevo**, set up by Claude through Brevo's API with the key in an
    environment variable, never in the chat:
    1. Add the domain `shushgift.com`.
    2. The owner publishes the DNS records it returns.
    3. Authenticate the domain.
    4. Create the sender "Shush Gift" `hello@shushgift.com`.

    Then `EMAIL_SENDER_ADDRESS` and `EMAIL_SENDER_NAME="Shush Gift"` in both
    `.env` files. Replies to `hello@` reach the owner through the registrar's
    email forwarding (MX records).
  - **Google Cloud:** branding (app name, authorised domain, home and legal
    links), the web client's JavaScript origins, the iOS and Android OAuth
    clients for the new ids, and the Pub/Sub push endpoint with
    `GOOGLE_PLAY_PUBSUB_AUDIENCE`.
  - **Apple:** the App IDs `com.shushgift.app(.val)` with Sign in with Apple
    and Associated Domains; the Services ID's domains and return URLs; App
    Store Server Notifications URLs; and the App Store Connect app records
    named "Shush Gift".
  - **Play Console:** the apps `com.shushgift.app(.val)` named "Shush Gift".
  - **Stripe:** the webhook endpoint, the public details (name and terms URL)
    and the product name.
  - **GitHub:** rename the repository and make it private (D3a). Then:
    - the `API_BASE_URL_*` secrets;
    - the `IOS_BUNDLE_ID*`, `ANDROID_APP_ID` and `GOOGLE_IOS_CLIENT_ID(_VAL)`
      variables, the last from the new iOS OAuth clients (review R1-5);
    - the GHCR package (private, D3a);
    - the VAL webhook's payload URL.
  - **Values tied to the app ids** (review R1-5), set per environment once its
    store records exist:
    - `APPLE_BUNDLE_ID`, `APPLE_APP_APPLE_ID` and `APPLE_CLIENT_IDS`;
    - `GOOGLE_PLAY_PACKAGE_NAME` and `APPLE_ANDROID_PACKAGE`;
    - the subscription product in each new App Store Connect and Play app,
      with `APPLE_*` and `GOOGLE_PLAY_PRODUCT_ID` naming it;
    - Play's real-time developer notifications topic on each new app;
    - the App Store Server Notifications URLs on each new app.

    No store record exists yet under any other id (owner, 2026-11-11), so
    there is nothing to retire.
  - **Environment values:** `DEPLOY_VAL_URL`, `DEPLOY_PROD_URL` and the
    `LEGAL_*` URLs.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **New unauthenticated routes:**
  - `/.well-known/apple-app-site-association` and
    `/.well-known/assetlinks.json`. They serve configuration only. Any
    account data, or anything that varies with who asks, in them is F1.
  - A response that redirects, or is not `application/json`, breaks
    verification and is a defect.
- **The `www` redirect:** its target is the fixed apex plus the request path.
  A redirect whose target a request can choose (an open redirect) is F1.
- **The VPS move handles PROD's data:**
  - Any step that can lose data is F2 if it runs before a verified dump and
    with no way back: the database, the media, or the dumps the media purge
    dates its horizon from.
  - So is a step that resets media modification times.
- **The surprise rule is untouched:** no route, payload or role changes. App
  links open the same screens with the same server checks. A link that let a
  recipient reach a screen the web would refuse them is F1.
- **Out of the envelope:** store review, the owner's purchases and
  registrations, DNS propagation times, and Google's brand verification.

## Boundaries crossed

- **API:** two new public routes (D7). No existing request or response shape
  changes.
- **Schema:** none. **Stored data:** none in the database. On the VPS, the
  database moves into a new project, user and name by dump and restore (D8),
  and the dumps are renamed.
- **Client storage:** the keys are renamed (D5). Web users sign in again,
  which the origin change forces anyway. Test-build users sign in again too.
- **Clients in the wild (E5):** only test builds exist. They keep working on
  the old hosts until those are removed (D6), and testers then install the
  new builds.
- **Links already sent:** they stop working when the old hosts are removed
  (D6). This is accepted because PROD has no real users yet.
- **External contracts:** the Stripe marker is kept (D4). Every webhook
  sender is repointed (D9). A delivery that fails meanwhile is retried by its
  sender.
- **Environment:** `APP_LINKS_APPLE_APP_IDS`, `APP_LINKS_ANDROID_PACKAGE` and
  `APP_LINKS_ANDROID_SHA256` are new. `PUBLIC_BASE_URL`,
  `GOOGLE_PLAY_PUBSUB_AUDIENCE`, `GOOGLE_PLAY_PACKAGE_NAME`,
  `GOOGLE_PLAY_PRODUCT_ID`, `EMAIL_SENDER_*`, `APPLE_*` and the database
  values change.
- **Repository settings:** the repository name and visibility, the image
  name, the `ANDROID_APP_ID`, `IOS_BUNDLE_ID*` and `GOOGLE_IOS_CLIENT_ID*`
  values, and the `API_BASE_URL_*` values.

## Conventions

- The rename rule is D3. A `wishlist` that names the product or the code
  becomes `shushgift` / `ShushGift` / "Shush Gift". A "wishlist" that means a
  list of wishes in user text stays. The only frozen identifiers are the
  Stripe marker and the files under `docs/plans/` and `docs/reviews/` (D4).
- No hostname, IP or user of the VPS is committed. The brand domain
  `shushgift.com` may appear in user-facing docs, but configuration still
  reads every host from the environment and secrets.
- After each unit, `git grep -i wishlist` within its Scope shows only the
  exceptions above and the common noun. The unit's report lists what is left
  and why.
- Goldens that change because of the name are regenerated with `goldens.ps1`,
  and the report says so.

## Open decisions

None left. Settled by the owner on 2026-11-11:

- "Shush Gift" is free as a store name.
- The sender is `hello@shushgift.com`.
- The old hosts go right after PROD moves (D6).
- The repository becomes the private `rui-nar/shushgift` (D3a).
- The macOS build leaves pull requests (D3a).

## Execution units

### Wave 1

#### U1 — Client: the rename

- **Goal:** The client calls itself Shush Gift everywhere a person can see,
  and `shushgift` everywhere in code (D2, D3, D5).
- **Scope:**
  - `client/lib/**`, `client/test/**` (goldens included), `client/web/**`.
  - `client/pubspec.yaml`, `client/l10n.yaml`, `client/README.md`.
  - `client/android/**`, including moving `MainActivity.kt` to the
    `app/shushgift` package.
  - `client/ios/**`, except `Runner.entitlements`.
  - `goldens.ps1`.
- **Context:**
  - D2, D3, D5, Conventions.
  - Example: `ANDROID_RELEASE_PLAN.md` U1, which set the labels, flavours and
    namespace the same way.
  - The web title and manifest take the name and a real description in place
    of Flutter's template.
- **Do:**
  - Rename the package, its imports and the classes.
  - Rename the storage keys, the ARB texts (en, fr) and the Android labels.
  - Rename the xcconfig variables and their defaults, with the display name
    "Shush Gift".
  - Rename `CFBundleName`, the usage strings, the web `index.html` and
    `manifest.json`, and the Gradle properties.
  - Update test fixtures (`wishlist.example`, `com.example.wishlist`).
- **Acceptance:**
  - `flutter analyze` and `flutter test -j 2` pass.
  - `flutter build web` succeeds.
  - `flutter build apk --flavor val --debug` succeeds.
  - The Convention's grep check is clean.
  - The tests asserting "How Wishlist works" and friends assert the new text.
- **Out of scope:** CI workflows (U5), app links (U4), the icon.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed. A golden changes for a
  reason other than the text.
- **Depends on:** none.

#### U2 — Server: the rename and the app-link files

- **Goal:** The server names itself Shush Gift and serves the two app-link
  files from settings (D2, D3, D4, D7).
- **Scope:**
  - `server/app/main.py`, `server/app/settings.py`, `server/app/safe_fetch.py`.
  - `server/app/notifications/email_content.py`.
  - `server/app/billing/stripe_events.py` (the D4 comment only) and
    `server/app/billing/stripe_gateway.py` (the idempotency prefix).
  - `server/app/media/purge.py` (comment).
  - `server/app/app_links.py` (new).
  - `server/pyproject.toml`, `server/uv.lock`, `server/tests/**`.
  - Not the `.env.example` files: U3 adds the `APP_LINKS_*` keys there
    (review R1-7).
- **Context:**
  - D7, the envelope.
  - Example: `/api/config` in `main.py`, a settings-built public answer; and
    how `_serve_web_client` is registered last.
- **Do:**
  - Rename as D3, with the email texts reworded (D2).
  - Add the two routes, registered before the web catch-all.
- **Acceptance:**
  - The AASA lists exactly D7's paths for the configured app ids.
  - `assetlinks.json` holds the package and every fingerprint.
  - Both are `application/json` and answer 200 without a redirect.
  - Each answers 404 when its settings are empty.
  - `HEAD` works.
  - The OpenAPI title is "Shush Gift".
  - Email subject tests for both languages pass.
  - `ruff check` passes, `pytest` passes, and `alembic check` is unchanged.
- **Out of scope:** Stripe's marker value (D4), Caddy.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed. A setting would need to
  vary per request.
- **Depends on:** none.

#### U3 — Infrastructure: the rename

- **Goal:** Images, stacks, scripts and CI use `shushgift`, Caddy has the
  `www` redirect, and pull requests no longer build on macOS (D1, D3, D3a).
- **Scope:**
  - `Dockerfile`, `entrypoint.sh`.
  - `deploy/**`, the two `.env.example` files in it included.
  - `deploy.ps1`, `deploy.env.example`, `dev.ps1`, `docker-compose.dev.yml`.
  - `.github/workflows/docker-build.yml`, `.github/workflows/test.yml`,
    `.github/workflows/deploy-smoke.yml`.
  - `.env.example` (the root one).
- **Context:**
  - D1, D3, D3a, D8.
  - Example: `deploy/caddy/Caddyfile.snippet` and `deploy/smoke/run.sh`,
    which already substitutes placeholder hosts.
- **Do:**
  - Rename as D3.
  - Add a `www.<prod-host>` block to the snippet that redirects to
    `https://<prod-host>{uri}`.
  - Remove the macOS iOS job from `test.yml`.
  - In the three `.env.example` files: the database names, `EMAIL_SENDER_NAME`
    "Shush Gift", and the `APP_LINKS_*` keys with D7's comments (empty means
    the file answers 404).
  - The smoke test checks the `www` redirect, and that a request cannot make
    it redirect elsewhere.
- **Acceptance:**
  - `shellcheck` on changed scripts and `actionlint` on changed workflows
    pass.
  - The `deploy-smoke` workflow is green.
  - The Convention's grep check is clean.
- **Out of scope:** the move on the VPS itself (U6), the release workflows
  (U5).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed. The smoke test cannot
  serve an extra host.
- **Depends on:** none.

### Wave 2

#### U4 — Client: app links

- **Goal:** On a phone with the app, a Shush Gift link opens the app on the
  right screen (D7).
- **Scope:**
  - `client/android/app/src/main/AndroidManifest.xml` and
    `client/android/app/build.gradle.kts`.
  - `client/ios/Runner/Runner.entitlements`, `client/ios/Flutter/*.xcconfig`
    and `client/ios/Runner.xcodeproj/project.pbxproj`.
  - `client/lib/src/shared/**`, `client/lib/src/app_router.dart`,
    `client/lib/main.dart`, `client/lib/src/auth/email_link*.dart`.
  - `client/test/**`.
- **Context:**
  - D7.
  - Example: the web path in `pending_join.dart` / `join_browser_web.dart`,
    which reads the address and hands the token to the join screen. Mobile
    does the same from the incoming link.
- **Do:**
  - The intent filter with `autoVerify`, conditional on
    `shushgiftAppLinkHost`.
  - The entitlement, conditional on `SHUSHGIFT_APP_LINK_HOST`.
  - The incoming-link handling, at cold start and while the app is running.
- **Acceptance:**
  - Widget tests feed links (cold and warm) for `/join#t`, `/shared/x?gift=y`
    and `/reset-password#t`, and land on the same screens as the web.
  - `/account/plan` is not claimed in the manifest.
  - `flutter build apk --flavor val --debug` passes, both with and without
    the property.
  - `flutter analyze` and `flutter test -j 2` pass.
- **Out of scope:** the server files (U2), CI (U5).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed. Flutter drops the fragment
  from the incoming link on either platform.
- **Depends on:** U1.

#### U5 — CI: the release workflows

- **Goal:** Release builds carry the new names and ids and the app-link host
  (D2, D3, D7).
- **Scope:** `.github/workflows/ios-release.yml` and
  `.github/workflows/android-release.yml`.
- **Context:**
  - D3, D7.
  - Example: how both workflows already derive values from
    `API_BASE_URL_*` and check them for https.
- **Do:**
  - `ios-release.yml` runs on `v[0-9]*` tags and by hand, no longer on
    `validation` (D3a), with its comments saying so.
  - Display names "Shush Gift" and "Shush Gift VAL".
  - `SHUSHGIFT_*` xcconfig keys and the `shushgift*` Gradle properties.
  - The app-link host is the host of the chosen `API_BASE_URL_*`, passed as
    `SHUSHGIFT_APP_LINK_HOST` and `-P shushgiftAppLinkHost`.
- **Acceptance:**
  - `actionlint` passes.
  - Both workflows still end green with a notice when there are no secrets.
  - The host extraction is tested in a workflow step against a sample URL.
- **Out of scope:** secrets values, which are the owner's (U6).
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1. The property and variable names are fixed by D7, so U4
  can run alongside.

### Wave 3

#### U6 — Runbook and docs

- **Goal:** The owner can move VAL, then PROD, to `shushgift.com` with a way
  back at every step, and every doc names the app Shush Gift (D8, D9).
- **Scope:**
  - `docs/DEPLOYMENT.md`, `docs/BILLING.md`, `docs/DEVELOPMENT.md`,
    `docs/DESIGN.md`, `docs/README.md`.
  - `docs/plans/README.md` (this plan's row).
  - `README.md`, `client/README.md`.
- **Context:**
  - D6, D8, D9, Open decisions.
  - Example: DEPLOYMENT.md "Restoring PROD from a dump" and "Postgres major
    upgrade", which already move PROD's data with a kept way back.
- **Do:**
  - A new section, "Moving to shushgift.com", in the order of D9's
    dependencies:
    1. DNS and Brevo's domain records.
    2. The GitHub repository rename and the GHCR package.
    3. VAL's cut-over (D8) with checks: `/api/version`, `/api/health`, both
       `.well-known` files, and a sign-in.
    4. The consoles for VAL.
    5. A test email, an occasion link opened on each phone, and a Stripe test
       purchase.
    6. Then PROD the same way.
    7. Right after PROD and its consoles: removing both old hosts' Caddy
       blocks (D6).
    8. A day later, after a nightly dump: removing the old volumes and
       directories.
  - Rename the existing sections (paths, units, names), and replace the
    `com.example` placeholders with D3's ids.
  - Rewrite "Getting the files onto the host" and "Updating the files on the
    host" to use `git archive` plus `scp` (D3a), and GHCR's "Private or public"
    for the private package.
  - List D9's values tied to the app ids in the Apple, Google and Play steps.
  - Make the iOS steps say that a VAL build is a manual run.
  - Close the "own domain" Open item.
  - Local DEV: the new compose project starts empty. Say how to carry a dev
    database over or start fresh.
- **Acceptance:**
  - No VPS hostname, IP or user is committed.
  - Every step names its check and its way back.
  - The Convention's grep check is clean outside `docs/plans/` and
    `docs/reviews/`.
- **Out of scope:** code.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed. A step has no way back.
- **Depends on:** U2, U3, U4, U5.

## Definition of done

- `val.shushgift.com` and `shushgift.com` serve the web client and the API
  over TLS. `www` redirects to the apex.
- The old TraxJourney hosts no longer serve Shush Gift. TraxJourney's own
  hosts answer as before.
- The repository is the private `rui-nar/shushgift`, and the VPS pulls the
  private image.
- Both `.well-known` files are served on each host for its own apps. An
  occasion link and a reset-password email open the installed VAL app on
  Android and iOS.
- Sign-in with Google, Apple and email works on VAL's new host, on the web and
  in both apps.
- A Stripe test purchase on VAL grants Premium. A subscription created before
  the move is still recognised.
- Emails come from "Shush Gift" at a `shushgift.com` address, with DKIM
  passing.
- The VPS holds `/opt/shushgift*`, `shushgift-*` projects and
  `shushgift_<date>.dump`. A nightly dump and a VAL seed from it succeeded
  after the move.
- `git grep -i wishlist` shows only D4's exceptions and the common noun.
- The checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
