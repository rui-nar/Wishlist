# iOS app — Plan

## Problem

Wishlist runs on the web and Android. `docs/NEEDS.md` Constraints lists iOS,
and the owner decided on 2026-11-11 how it ships:

- GitHub Actions builds and signs it on macOS, since the owner works on
  Windows;
- TestFlight delivers it;
- Premium can be bought in it through Apple's in-app purchase, which
  `APPLE_IAP_PLAN.md` covers;
- the bundle identifier is decided later, before the first upload.

The owner has no Apple Developer membership yet. Nothing reaches a phone until
they have one, but everything up to the signed upload can be built and checked
before then.

## Current state

- `client/ios/` is Flutter's generated project. Its bundle id is the
  placeholder `com.example.wishlist`, and its deployment target is iOS 15.0.
  There is no entitlements file, and the Info.plist has no usage descriptions
  or URL schemes.
- The client reads its server from `--dart-define=API_BASE_URL`
  (`client/lib/src/config.dart`). Its Google client ID comes from
  `/api/config`.
- `google_sign_in` 7, `sign_in_with_apple` 8, `image_picker`,
  `flutter_secure_storage`, `shared_preferences` and `url_launcher` all
  support iOS. The vendored `google_sign_in_web` is web-only.
- Sign in with Apple works on the web and Android
  (`APPLE_EMAIL_SIGNIN_PLAN.md`). D17 there left two things for the iOS
  release: the iOS bundle id joining `APPLE_CLIENT_IDS`, and revoking Apple's
  token at account deletion.
- CI (`.github/workflows/test.yml`) runs on Linux only.
- Purchases are offered on the web only (`PREMIUM_PLAN.md` D18).

## Decisions

- **D1 — One place for the bundle id, and two apps.**
  - `client/ios/Flutter/Identity.xcconfig` sets `WISHLIST_BUNDLE_ID`,
    `WISHLIST_DISPLAY_NAME` and `PRODUCT_BUNDLE_IDENTIFIER =
    $(WISHLIST_BUNDLE_ID)` for the app. The tests' target derives its id from
    it. The committed value stays the placeholder.
  - VAL and PROD are **two apps**, each with its own bundle id and App Store
    Connect record (review R1-2): `IOS_BUNDLE_ID` for PROD, and
    `IOS_BUNDLE_ID_VAL` for VAL, shown as "Wishlist VAL". A tester never has a
    VAL build replace a PROD one, and a Keychain session never crosses over.
  - The release workflow overrides the values per environment and refuses to
    upload with the placeholder.
  - Rules out editing `project.pbxproj` by hand per environment.
- **D2 — Which server a build talks to.** It is a build input, as on Android:
  `API_BASE_URL`. The values come from the repository **secrets**
  `API_BASE_URL_VAL` and `API_BASE_URL_PROD`, so the hostnames stay out of
  the public repository and are masked in the logs (review R1-3). The
  workflow refuses to build with an empty one.
  - A build made from the `validation` tag is the VAL app pointing at VAL.
    Testers use this app.
  - A build made from a release tag is the PROD app pointing at PROD. It goes
    to the owner and to Apple's review.
  - Each build's version says which (`APP_VERSION`, shown on the version
    screen). Rules out a server switch inside the app.
- **D3 — Google on iOS.** Google requires an **iOS** OAuth client and its
  reversed client ID as a URL scheme in the Info.plist, which is a build-time
  value. `GOOGLE_IOS_CLIENT_ID` (PROD) and `GOOGLE_IOS_CLIENT_ID_VAL` (VAL), one Google
  iOS client per bundle id, are repository variables read into the
  xcconfig. The app passes the web client ID from `/api/config` as the server
  client ID, so the ID token's audience is the web client and
  `GOOGLE_CLIENT_IDS` on the server needs no change. Without the variable the
  build still succeeds, and the iOS app offers Apple and email only.
- **D4 — Apple on iOS.** It uses the native sheet. The app gets the "Sign in
  with Apple" capability (`Runner.entitlements`). The token's audience is the
  bundle id, which the runbook adds to `APPLE_CLIENT_IDS` after the Services
  ID. The nonce is the same as on the web.
- **D5 — Revoking Apple's token at account deletion**, which Apple requires
  of apps offering Sign in with Apple.
  - **At sign-in:** the client also sends Apple's one-time
    `authorization_code`. The server exchanges it at
    `https://appleid.apple.com/auth/token` for a refresh token, using a client
    secret that is an ES256 JWT signed with the owner's key. New variables:
    `APPLE_TEAM_ID`, `APPLE_KEY_ID` and `APPLE_PRIVATE_KEY` (secret). The
    server stores the token in a new table, `apple_tokens` (`user_id` FK
    cascade, `client_id`, `refresh_token`, `updated_at`), one row per
    `(user_id, client_id)`, replaced at each sign-in.
  - **At deletion:** the server calls `/auth/revoke` for each row **after
    `stop_billing` has succeeded and before any lock** (review R1-5), so a
    refused deletion has changed nothing. A failure is logged and does not
    stop the deletion: the person asked to be deleted, Apple cannot be retried
    later without the token, and Apple's rule asks for an attempt.
  - **The bar:** revoke whenever a token exists (owner, 2026-11-11). An
    account that signed in with Apple before this release gets a token at its
    next sign-in.
  - **VAL never keeps real tokens** (review R1-1): `seed-from-prod.sh` empties
    `apple_tokens`, as it already empties purchases. A deletion on VAL then
    has nothing of PROD's to revoke.
  - **Without the three variables**, nothing is exchanged and the app logs at
    start that revocation is off.
  - **Rules out:** keeping no token and asking the person to re-authorise
    with Apple at deletion, which fails for a person who no longer has the
    device.
- **D6 — The rest of what the App Store requires:**
  - usage descriptions for the photo library and camera, in English and
    French (`InfoPlist.strings`);
  - `ITSAppUsesNonExemptEncryption` = false (HTTPS only);
  - the app icon and launch screen from the design system's assets;
  - iPhone and iPad, both orientations, since the layouts already adapt;
  - account deletion in the app, which exists;
  - the privacy policy link in the app, from `LEGAL_PRIVACY_URL` (the
    existing legal links, shown on iOS too).
- **D7 — CI, in two jobs:**
  - **`ios` in `test.yml`**, on `macos-15`, for every pull request: `flutter
    build ios --release --no-codesign` with the placeholder id. It proves the
    project builds, with no secrets. Tests stay on Linux.
  - **`ios-release.yml`**, started by hand or by a `validation` or release
    tag. It runs only when the App Store Connect API key secrets exist
    (`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`, plus the variable
    `APPLE_TEAM_ID`), and otherwise ends with a notice. It signs automatically
    with the API key (`xcodebuild -allowProvisioningUpdates`), builds an IPA,
    and uploads it to TestFlight. The build number is the run number. No
    certificates or profiles are committed or kept as files.
  - **Rules out** fastlane match, which needs a second private repository
    for certificates.
- **D8 — No universal links yet.** Share and email links open in Safari,
  where the web app works. Opening them in the app needs the team id in a
  file the site serves (`/.well-known/apple-app-site-association`). That is
  an Open decision.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **A new kind of client: iOS builds**, which cannot be forced to update (E5),
  like Android.
- **A new external service call: Apple's token endpoints**, with a signing key
  held by the server. The key and the refresh tokens are secrets. A token or
  key in a log, an exception, a response or the repository is F1, and so is a
  real refresh token at rest outside PROD (VAL's seeded database).
- **A new unauthenticated input:** `authorization_code` on
  `POST /api/auth/apple`, which is untrusted, can be replayed, and can belong
  to another client id.
- **CI holds signing secrets.** A workflow that exposes them to a pull request
  from a fork is F1.
- **Out of the envelope:** the content of the App Store listing, Apple's
  review, and the owner's enrolment.

## Boundaries crossed

- **Schema (F4):** one migration adding `apple_tokens`. The previous release
  ignores it.
- **API:** `POST /api/auth/apple` accepts an optional `authorization_code`.
  Old clients send none and nothing changes for them.
- **Stored data:** Apple refresh tokens, deleted with the account.
- **Environment:** `APPLE_TEAM_ID`, `APPLE_KEY_ID` and `APPLE_PRIVATE_KEY`,
  all optional.
- **Repository settings:** the variables `IOS_BUNDLE_ID`,
  `IOS_BUNDLE_ID_VAL`, `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID_VAL` and
  `APPLE_TEAM_ID`, and the
  secrets `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`, `API_BASE_URL_VAL` and
  `API_BASE_URL_PROD`.

## Conventions

- `import jwt` stays in `accounts/apple.py`, which grows the client-secret
  signing. Calls to Apple's token endpoints go through one module, with
  timeouts and fixed failure labels.
- No secret in a log, an exception or a committed file. The private key is
  read from the environment only.
- Every string in both ARB and `InfoPlist.strings` files.
- U3 gets a unit review (DELIVERY §5, point 3).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| The bundle identifier, shared with Android | D1, every Apple registration | Before the first TestFlight upload |
| Apple Developer enrolment (owner) | D5, D7 | Before the first signed build |
| Universal links for share and email links (D8) | Client, a served file | Revisit after the first TestFlight round |
| Push notifications | Notifications | Revisit on user feedback; email covers it now |

## Execution units

### Wave 1

#### U1 — Client: the iOS project

- **Goal:** The iOS project builds with every capability and string the App
  Store needs.
- **Scope:** `client/ios/**`, `client/lib/src/auth/**` (iOS branches only:
  Google's iOS client id from the build, the native Apple sheet),
  `client/lib/src/config.dart`, `client/test/**`, `client/pubspec.yaml`.
- **Context:** D1, D3, D4, D6. Example: the Android set-up in
  `client/android/app/src/main/AndroidManifest.xml` and
  `google_sign_in_init.dart`.
- **Do:** the xcconfig and the bundle id plumbing; Info.plist keys and
  `InfoPlist.strings` in English and French; `Runner.entitlements` with Sign in
  with Apple; the Google URL scheme from the xcconfig; the icon and launch
  screen; the platform branches in the sign-in code.
- **Acceptance:** `flutter analyze` and `flutter test -j 2`. The `ios` CI job
  of U2 builds the project with `--no-codesign`; until U2 runs, the unit
  reports it unbuilt. The implementer is on Windows and cannot build iOS.
- **Out of scope:** CI, the server, purchases.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

#### U2 — CI: the iOS build and the TestFlight release

- **Goal:** Every pull request builds iOS, and a release workflow can sign
  and upload to TestFlight once the secrets exist.
- **Scope:** `.github/workflows/test.yml` (one new job),
  `.github/workflows/ios-release.yml` (new), `client/ios/ExportOptions.plist`
  (new).
- **Context:** D1, D2, D7. Example: the existing jobs in `test.yml` and the
  tag triggers in `docker-build.yml`.
- **Do:** as D7. The release job fails before signing with the placeholder
  id. Secrets reach only jobs that do not run for forks.
- **Acceptance:** `actionlint` on both files; the `ios` job green on the PR;
  the release workflow ends with a notice when the secrets are absent.
- **Out of scope:** the App Store listing.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

#### U3 — Server: revoking Apple's token

- **Goal:** An account signed in with Apple has its Apple token revoked when
  it is deleted.
- **Scope:** `server/app/accounts/apple.py`, `server/app/accounts/apple_router.py`,
  `server/app/accounts/apple_tokens.py` (new), `server/app/accounts/models.py`,
  `server/app/accounts/deletion.py`, `server/app/settings.py`,
  `server/app/main.py` (the start-up log), `server/alembic/**` (one revision),
  `deploy/val/seed-from-prod.sh` (empty `apple_tokens`, review R1-1),
  `server/tests/accounts/**`, `server/tests/test_migrations.py`, the three
  `.env.example` files.
- **Context:** D5, the envelope. Example: `billing/stripe_gateway.py` for an
  outbound service behind one module, and `closing.stop_billing` for work done
  before deletion's locks.
- **Do:** as D5, with a fake for Apple's endpoints in tests.
- **Acceptance:** tests for the exchange (success, a code from another client,
  an Apple failure that still signs in), a token replaced at the next sign-in,
  revocation at deletion (success, an Apple failure that still deletes), the
  variables off, and the migration up and down; `ruff check`.
- **Out of scope:** the client.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** none.

### Wave 2

#### U4 — Client: send Apple's authorization code; runbook

- **Goal:** Every platform sends the code, and the owner has the steps from
  enrolment to TestFlight.
- **Scope:** `client/lib/src/auth/**`, `client/test/**`, `docs/DEPLOYMENT.md`,
  `docs/DEVELOPMENT.md`.
- **Context:** D3–D7. Example: `DEPLOYMENT.md` steps 11 and 12.
- **Do:**
  - The code in the Apple sign-in body.
  - An "iOS app" runbook section:
    - enrolment;
    - choosing the bundle id;
    - the App ID with Sign in with Apple and In-App Purchase;
    - adding the bundle id to `APPLE_CLIENT_IDS`;
    - the Sign in with Apple key, giving the three variables;
    - the App Store Connect app and API key, and the GitHub secrets and
      variables;
    - Google's iOS OAuth client;
    - TestFlight testers;
    - the privacy labels;
    - a first build from the `validation` tag.
- **Acceptance:** widget and controller tests; `flutter analyze`; no real
  identifier committed.
- **Out of scope:** purchases.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed.
- **Depends on:** U1, U3.

## Definition of done

- Every pull request builds the iOS app on CI.
- With the owner's secrets set, the release workflow puts a signed build on
  TestFlight.
- On an iPhone, Google, Apple and email sign-in work, and photos can be
  picked.
- Deleting an account revokes its Apple token when the keys are set.
- The runbook takes the owner from enrolment to a TestFlight build.
- The checks in `docs/DELIVERY.md` §2 pass, and the integrated review is done.
