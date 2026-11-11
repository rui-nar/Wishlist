# Android release — Plan

## Problem

The Android app runs from a developer machine, but it cannot be published.

- Its application id is the placeholder `com.example.wishlist`.
- Release builds are signed with the debug key.
- No CI job builds it.
- Premium cannot be bought on it: Google Play requires its own billing for a
  digital subscription sold in an app distributed through Play, and
  `docs/NEEDS.md` (Free and premium) already plans for Google in-app purchase.

On 2026-11-11 the owner asked for the Android app to be finished as well, after
iOS (`IOS_APP_PLAN.md`, `APPLE_IAP_PLAN.md`). This plan does for Android what
those two do for iOS, reusing their decisions wherever the platforms agree.

## Current state

- `client/android/app/build.gradle.kts`:
  - `applicationId` and `namespace` are `com.example.wishlist`.
  - Release is signed with the debug key.
  - Versions come from `pubspec.yaml`.
  - `minSdk` and `targetSdk` are Flutter's defaults.
- `AndroidManifest.xml`:
  - Its label is the lowercase `wishlist`, and its icons are Flutter's
    defaults.
  - It has the Sign in with Apple callback activity.
  - It declares no app links.
- No CI job builds an APK or an AAB.
- Purchases, Manage and the legal links are web-only in the client
  (`onTheWeb`).
- `entitlements.source` allows `google`; nothing writes it (premium plan D3).
- `docs/DEPLOYMENT.md`, "Android OAuth client", waits for the real id and
  release key. `APPLE_ANDROID_PACKAGE` needs the real id too.
- `APPLE_IAP_PLAN.md` builds the client's store purchase on iOS, and these
  signals: `apple_offer`, `apple_renewing`, and the admin's Apple block.

## Decisions

- **D1 — Two apps, as on iOS.** Product flavours `val` and `prod` in Gradle:
  - **`prod`:** `applicationId` from the Gradle property `wishlistAppId`.
    The committed default stays the placeholder.
  - **`val`:** `applicationIdSuffix ".val"`, labelled "Wishlist VAL".
  - Each is a separate app in the Play Console. Testers use the VAL app, and
    a VAL build never replaces a PROD install, so sessions never cross over
    (as IOS_APP_PLAN D1).
  - Both flavours share `namespace` `app.wishlist`, a code namespace only,
    which never changes and is not the store id.
  - The release workflow refuses the placeholder.
- **D2 — Which server.** `API_BASE_URL` from the same secrets as iOS,
  `API_BASE_URL_VAL` and `API_BASE_URL_PROD`. The `val` flavour is built from
  the `validation` tag, the `prod` flavour from a release tag.
- **D3 — Signing.** An upload key, kept as repository secrets:
  `ANDROID_UPLOAD_KEYSTORE_B64`, `ANDROID_UPLOAD_KEYSTORE_PASSWORD`,
  `ANDROID_UPLOAD_KEY_ALIAS` and `ANDROID_UPLOAD_KEY_PASSWORD`. Google Play
  App Signing holds the app signing key, so a lost upload key can be reset
  through Google, and the app is never stuck with one key. Gradle reads the
  key from environment variables. Without them a release build is signed with
  the debug key, so `flutter run --release` keeps working on a dev machine,
  and the release workflow refuses to upload such a build.
- **D4 — CI, in two jobs**, as IOS_APP_PLAN D7:
  - **`android` in `test.yml`**, for every pull request: `flutter build
    appbundle --flavor prod` with no secrets.
  - **`android-release.yml`**, started by hand or by the same tags as iOS:
    signs, builds the AAB with the build number from the run number, and
    uploads to the **internal testing** track as a completed release (a draft
    while the app has never been published), with a Google Play service
    account (`PLAY_SERVICE_ACCOUNT_JSON`) through the Play Developer API.
    Without the secrets it ends green with a notice. Secrets never reach a
    fork's pull request.
- **D5 — Name, icon, SDK levels.** "Wishlist" and "Wishlist VAL", with the
  launcher icon generated from the same source image as iOS (IOS_APP_PLAN U1),
  including an adaptive icon. `targetSdk` is whatever Play requires at upload,
  which is Flutter's current default; `minSdk` stays Flutter's default.
- **D6 — Premium through Google Play Billing**, as APPLE_IAP_PLAN for Apple,
  with Google's terms:
  - **Product:** one auto-renewing yearly subscription per app,
    `GOOGLE_PLAY_PRODUCT_ID`. The price is set in the Play Console, and the
    app shows Play's localised price.
  - **Linking:** the account id goes in `obfuscatedExternalAccountId`. The
    server refuses a purchase whose id is not the signed-in account (409
    `other_account`).
  - **Checking:** the client posts the purchase token to `POST
    /api/billing/google/purchases`. The server reads the subscription from
    the Play Developer API (`purchases.subscriptionsv2`) with a service
    account (`GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`, secret, plus
    `GOOGLE_PLAY_PACKAGE_NAME`). It records one entitlement, `source =
    google`, `external_id` the purchase token's linked root (the first token
    of the subscription), then **acknowledges** the purchase. Google refunds
    a purchase left unacknowledged for 3 days.
  - **Notifications:** Real-time developer notifications through Cloud
    Pub/Sub push to `POST /api/billing/google/notifications`. The push's OIDC
    token is verified (Google's signature, the audience set to that URL, the
    configured service account's email). Then the notification is trusted only
    as a pointer, and the subscription is re-read from the API (as Stripe
    and Apple). A voided-purchase notification is a pointer too: the
    subscription is re-read, and Play's state decides (review R1-4). A refund
    with revocation reads as expired.
  - **Selling on Android** needs `GOOGLE_PLAY_PRODUCT_ID`,
    `GOOGLE_PLAY_PACKAGE_NAME`, `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`,
    `GOOGLE_PLAY_PUBSUB_AUDIENCE` and `GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT`.
    Without the last two, notifications could not be verified, and renewals,
    grace and refunds would go unrecorded (review R1-2). The app logs at start
    which are missing, as it does for Stripe. A refused push is logged with
    fixed words.
  - **Status mapping:**

    | Play's state | Entitlement status | `period_end` |
    |---|---|---|
    | Active | `active` | `expiryTime` |
    | Cancelled, still in its paid period | `active` with `cancel_at_period_end` | `expiryTime` |
    | In grace period | `past_due` | the grace period's end |
    | On hold, paused or expired | `ended` | `expiryTime` |
    | Voided (refund) | `ended` | `expiryTime` |

    Premium lasts through Play's grace period and no longer, as decided for
    Apple.
  - **Account:** in this order (review R1-1):
    1. the purchase's `obfuscatedExternalAccountId`, when it names an
       existing account;
    2. the stored row's;
    3. for a resubscription made in the Play Store after expiry, which
       carries no account id, the stored row of
       `outOfAppPurchaseContext.expiredPurchaseToken`.

    Otherwise the purchase is logged with ids only and answered 200 (as
    APPLE_IAP_PLAN D4).
  - **Test purchases** (license testers, flagged `testPurchase`). VAL accepts
    **only** them: a real purchase on VAL is refused and left unacknowledged,
    so Google refunds it, since VAL's data is wiped at each seed (owner's
    instruction, 2026-11-11). PROD accepts them only from accounts in
    `GOOGLE_PLAY_TEST_ACCOUNT_IDS`, otherwise 409 `test_refused` (as
    APPLE_IAP_PLAN D6).
  - **Deletion:** unlike Apple, Google lets the server cancel. An account's
    renewing Google subscription is **cancelled before deletion**, like
    Stripe's (premium plan D15), with the same refusal when Google cannot be
    reached (owner's instruction, 2026-11-11). The deletion warning stays for
    the case where cancelling is not possible.
  - **Storage:** a purchase token can be longer than `external_id`'s 255
    characters (Google documents no maximum below that). A migration widens
    `entitlements.external_id` to text (review R1-5).
- **D7 — The offer and the limits.** `GET /api/billing` gains
  `google_offer` (`{"product_id": …}`) and `google_renewing` (bool), beside
  Apple's fields. Limits apply only while Stripe sells, unchanged.
- **D8 — The Android screens**, as iOS:
  - the plan screen with Play's price, the renewal and cancellation text, and
    the terms and privacy links;
  - Restore;
  - Manage opening Play's subscription page for the `google` source;
  - no purchase while Premium is already in force;
  - the account screen's plan section and legal links shown on Android;
  - the deletion warning when `google_renewing`.

  The admin panel gets a Google block like Apple's. The client's purchase
  code from APPLE_IAP_PLAN U2 is shared: one store interface, with Apple and
  Google behind it.
- **D9 — Sign-in on the real ids.** The runbook registers an Android OAuth
  client for each app id with its **Play App Signing** SHA-1 and upload SHA-1,
  and sets `APPLE_ANDROID_PACKAGE` per environment (VAL's id on VAL).
- **D10 — No app links yet.** Share and email links open in the browser, where
  the web app works. Verified app links need `assetlinks.json` with the
  signing certificate. That is an Open decision, as for iOS universal links.

## Review envelope

REVIEW.md defaults apply, with APPLE_IAP_PLAN's and IOS_APP_PLAN's envelopes
read for Google in place of Apple, and these additions:

- **A new external service: the Play Developer API**, with a service-account
  key. A key or a purchase token in a log is F1.
- **A new unauthenticated route:** `POST /api/billing/google/notifications`. A
  request without a valid Pub/Sub OIDC token for the configured audience and
  service account changing any state is F1.
- **Signing secrets in CI:** the upload key and the Play service account.
  Exposing them to a fork's pull request is F1.
- **Out of the envelope:** the Play Console listing, Google's review, pricing,
  the owner's Play developer registration.

## Boundaries crossed

- **Schema (F4):** one migration widening `entitlements.external_id` to text.
  The previous release reads it unchanged. Rollback stays image-only.
- **API:** two new routes. `GET /api/billing` gains `google_offer` and
  `google_renewing`, and `source` may be `google`. The admin row gains
  `google_subscription`.
- **Stored data:** Google entitlements, deleted with the account.
- **A contract with the past:** `obfuscatedExternalAccountId` = account id,
  and the root purchase token as `external_id`.
- **Environment:** `GOOGLE_PLAY_PACKAGE_NAME`, `GOOGLE_PLAY_PRODUCT_ID`,
  `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`, `GOOGLE_PLAY_PUBSUB_AUDIENCE`,
  `GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT` and `GOOGLE_PLAY_TEST_ACCOUNT_IDS`.
- **Repository settings:** the variable `ANDROID_APP_ID`; the secrets
  `ANDROID_UPLOAD_KEYSTORE_B64`, `ANDROID_UPLOAD_KEYSTORE_PASSWORD`,
  `ANDROID_UPLOAD_KEY_ALIAS`, `ANDROID_UPLOAD_KEY_PASSWORD` and
  `PLAY_SERVICE_ACCOUNT_JSON`.

## Conventions

- Google's API client is imported in `billing/google_gateway.py` only. Tests
  use a fake and never reach Google.
- No key, token or purchase token in a log; only order ids and fixed words.
- The new routes are in the role and surprise matrices.
- U3 gets a unit review (DELIVERY §5, point 3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| The application id, shared with the iOS bundle id choice | D1, every registration | Before the first Play upload |
| Google Play developer registration, merchant account, price (owner) | D4, D6 | Before the first upload and before selling |
| Verified app links (D10) | Client, a served file | Revisit after the first internal test |

## Execution units

### Wave 1

#### U1 — Client: the Android project

- **Goal:** Two flavours, real signing from the environment, the name and
  icon, and the SDK levels.
- **Scope:** `client/android/**`, `client/pubspec.yaml`, `client/README.md`.
- **Context:** D1, D3, D5. Example: IOS_APP_PLAN U1's xcconfig approach.
- **Do:** as the decisions say.
- **Acceptance:** `flutter build apk --flavor val --debug` and `flutter build
  appbundle --flavor prod` succeed on Windows; `flutter analyze`; `flutter
  test -j 2`.
- **Out of scope:** CI, purchases.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

#### U2 — CI: the Android build and the internal-track release

- **Goal:** Every pull request builds the bundle, and a release workflow
  signs and uploads to Play's internal track once the secrets exist.
- **Scope:** `.github/workflows/test.yml` (one new job),
  `.github/workflows/android-release.yml` (new).
- **Context:** D1–D4. Example: IOS_APP_PLAN U2's `ios-release.yml`.
- **Do:** as D4.
- **Acceptance:** `actionlint`; the `android` job green on the PR; the release
  workflow ending with a notice without secrets.
- **Out of scope:** the Play listing.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1.

#### U3 — Server: the Google translator and its routes

- **Goal:** A purchase made on Android grants Premium, stays in step through
  Play's notifications, and ends when Play says so.
- **Scope:** `server/app/billing/google_gateway.py`,
  `server/app/billing/google_events.py` (new), `server/app/billing/router.py`,
  `server/app/billing/schemas.py`, `server/app/settings.py`,
  `server/app/billing/closing.py` and `server/app/accounts/deletion.py`
  (cancelling at deletion), `server/app/billing/models.py`, `server/alembic/**`
  (one revision), `server/tests/test_migrations.py`,
  `server/app/admin/schemas.py` and `queries.py` (the Google subscription on
  the admin row), `server/app/main.py`, `server/pyproject.toml`,
  `server/uv.lock`, `server/tests/billing/**`, `server/tests/admin/**`,
  `server/tests/lists/test_roles.py` and `test_surprise.py` (rows and calls),
  the three `.env.example` files.
- **Context:** D6, D7, the envelope. Example: APPLE_IAP_PLAN U1's Apple
  translator.
- **Do:** as the decisions say.
- **Acceptance:** tests for each status of the mapping; acknowledgement; the
  account rule; test purchases on VAL and PROD; a forged or tampered push
  refused with nothing written; a notification and a report racing; repeats;
  the selling state; the admin's Google block; `ruff check`; the role and
  surprise matrices.
- **Out of scope:** the client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** APPLE_IAP_PLAN U1 (the same files).

### Wave 2

#### U4 — Client: buying on Android

- **Goal:** An Android user can buy, restore and manage Premium.
- **Scope:** `client/lib/src/billing/**`, `client/lib/src/admin/**`,
  `client/lib/src/auth/account_screen.dart`, `client/lib/l10n/*.arb`,
  `client/test/**`.
- **Context:** D6–D8. Example: APPLE_IAP_PLAN U2's store interface.
- **Do:** Google behind the store interface; the plan screen and account
  screen on Android; the admin's Google block; the deletion warning.
- **Acceptance:** widget tests through a fake store: buy, cancel, pending,
  refused by the server, restore, already Premium, not offered; goldens;
  `flutter analyze`, `flutter test -j 2`.
- **Out of scope:** iOS.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U3, APPLE_IAP_PLAN U2.

#### U5 — Runbook

- **Goal:** The owner can take Android from registration to a tested
  internal-track purchase, VAL first.
- **Scope:** `docs/DEPLOYMENT.md`, `docs/BILLING.md`, `docs/DEVELOPMENT.md`.
- **Context:** D1–D9. Example: the iOS sections from IOS_APP_PLAN U4 and
  APPLE_IAP_PLAN U3.
- **Do:**
  - Play developer registration.
  - Two apps.
  - The upload key and Play App Signing.
  - The service account and its Play Console permissions.
  - The GitHub secrets.
  - **A first manual upload of a signed bundle in each app's Play Console**
    (the release workflow keeps the signed AAB as an artefact for it): the
    Play Developer API and subscription products need one (review R1-6).
  - The subscription product and grace period, after that upload.
  - Pub/Sub topic and push subscription with authentication.
  - License testers.
  - The Android OAuth clients with both SHA-1s.
  - `APPLE_ANDROID_PACKAGE`.
  - A first internal build from the `validation` tag, and a test purchase,
    renewal, cancellation and refund on VAL.
- **Acceptance:** no real identifier committed.
- **Out of scope:** code.
- **Latitude:** none.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U3.

## Definition of done

- Every pull request builds the Android bundle on CI.
- With the owner's secrets set, a signed build reaches Play's internal track.
- On an Android phone, a test purchase on VAL grants Premium. Renewal,
  cancellation, grace and refund move it as D6 says.
- The checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
