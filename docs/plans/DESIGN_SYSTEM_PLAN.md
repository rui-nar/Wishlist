# Design system — Lagoon

## Problem

Every feature from accounts onwards builds screens. Without a design system
each screen would choose its own colours, fonts, spacing and status styling,
and the look the owner chose ("Lagoon", recorded in `docs/NEEDS.md`
Constraints) would drift from the first feature on. Two first-release
constraints also have to be in place before the first real screen:

- **English and French from the first release** (`docs/NEEDS.md`): every
  string a screen shows must come from translation files from the start;
  retrofitting them later means touching every screen.
- **Invitee activity has its own colour**, which carries the product's main
  invariant into the UI: what invitees did (reserved, bought, pledged) is shown
  in rose, and nothing rose ever appears on a recipient's own list.

The mock-ups the owner chose from are at
https://claude.ai/artifact/PSc8n5pwZLeVxvLCPHNVmi (artboard "C · Lagoon";
private to the owner).

## Current state

- `client/` is the walking skeleton from the DevOps foundation: one screen,
  `client/lib/src/version_screen.dart`, inside a bare `MaterialApp` in
  `client/lib/main.dart` (default Material 3 theme, no fonts, no
  localisation, English strings inline).
- Tests: `client/test/version_screen_test.dart`, widget tests with a mocked
  HTTP client. No golden tests.
- CI: `.github/workflows/test.yml`, job `client`, runs `flutter analyze` and
  `flutter test` on `ubuntu-latest` with Flutter 3.47.1. The dev machine is
  Windows, with Docker.
- The Docker image builds the web client from a Flutter SDK cloned at
  `FLUTTER_TAG=3.47.1` (`Dockerfile`), not from a prebuilt Flutter image.
- The look builds on TraxJourney's design foundations (the "TraxJourney
  Design System" artifact): Inter, an 8-point spacing grid, radii 6/8/12/16,
  flat cards with a 1 px border and no shadow, slate greys, sentence case, no
  emoji, Material outlined icons.

## Decisions

- **D1 — Tokens in Dart, one source.** Colours, spacing, radii and type sizes
  are `const` values in `client/lib/src/design/tokens.dart`. The themes and
  every widget read them from there or from `Theme.of(context)`; no hex value
  or pixel spacing literal appears in a screen. Rules out a JSON token file
  generating Dart (a build step for about forty values) and literals in
  screens (drift).

- **D2 — The colour scheme is written out, not seeded.** `ColorScheme` is
  built field by field for light and dark. `ColorScheme.fromSeed` would derive
  a tonal palette and shift the chosen `#0F766E` and slate greys to its own
  tones. Every role Flutter's widgets read is set explicitly so no default
  purple leaks in.

  | Role | Light | Dark |
  |---|---|---|
  | `primary` / `onPrimary` | `#0F766E` / `#FFFFFF` | `#2DD4BF` / `#042F2E` |
  | `primaryContainer` / `onPrimaryContainer` | `#CCFBF1` / `#134E4A` | `#134E4A` / `#CCFBF1` |
  | `surface` (cards, sheets, app bar) / `onSurface` (headings) | `#FFFFFF` / `#1E293B` | `#1E293B` / `#F1F5F9` |
  | Page background (`scaffoldBackgroundColor`) | `#F1F5F9` | `#0F172A` |
  | Body text | `#334155` | `#CBD5E1` |
  | `onSurfaceVariant` (hints, metadata) | `#475569` | `#94A3B8` |
  | `outline` (borders, dividers) | `#CBD5E1` | `#334155` |
  | `outlineVariant` (subtle dividers) | `#E2E8F0` | `#273449` |
  | `secondary` / `onSecondary` | `#334155` / `#FFFFFF` | `#CBD5E1` / `#0F172A` |
  | `secondaryContainer` / `onSecondaryContainer` (navigation indicator, selected chips) | `#E2E8F0` / `#1E293B` | `#334155` / `#F1F5F9` |
  | `tertiary` / `onTertiary`, `tertiaryContainer` / `onTertiaryContainer` | same as `secondary` | same as `secondary` |
  | `surfaceContainerLowest` / `Low` / (default) / `High` / `Highest` | `#FFFFFF` / `#F8FAFC` / `#F1F5F9` / `#E2E8F0` / `#E2E8F0` | `#0F172A` / `#1E293B` / `#1E293B` / `#273449` / `#334155` |
  | `inverseSurface` / `onInverseSurface` / `inversePrimary` (snack bars) | `#1E293B` / `#F1F5F9` / `#5EEAD4` | `#F1F5F9` / `#1E293B` / `#0F766E` |
  | `errorContainer` / `onErrorContainer` | `#FEE2E2` / `#7F1D1D` | `#7F1D1D` / `#FEE2E2` |
  | `error` / `onError` | `#B91C1C` / `#FFFFFF` | `#F87171` / `#450A0A` |

  Metadata grey is slate-600 in light, not TraxJourney's slate-500: `#64748B`
  on the page background is 4.34:1, below the 4.5:1 the contrast test
  requires (review R1-4). `tertiary` repeats `secondary` so no Material
  widget paints a colour that could be mistaken for invitee activity (D3).

  The dark values are new: the mock-ups showed light only. The owner checks
  them on VAL (Open decisions).

- **D3 — Invitee activity is a theme extension, not a Material role.**
  `WishlistColors extends ThemeExtension` carries `inviteeActivity`
  (light `#E11D48`, dark `#FB7185`), `inviteeActivityContainer` (`#FFE4E6` /
  `#4C0519`) and `onInviteeActivityContainer` (`#9F1239` / `#FFE4E6`), plus the
  page background and body-text colours above, which `ColorScheme` has no slot
  for. Rules out reusing `tertiary` or `secondary`: Material widgets paint
  those on their own (switches, FABs, chips), so rose would appear where it
  means nothing, and a recipient's screen could show rose without any invitee
  data behind it.

- **D4 — Fonts are bundled, never fetched.** Inter (400, 500, 600, 700) and
  Space Grotesk (600, 700) are static TTF files in `client/assets/fonts/`,
  declared in `pubspec.yaml`, with their SIL Open Font License texts
  registered in `LicenseRegistry`. Rules out the `google_fonts` package, which
  downloads fonts at runtime:
  - mobile owners edit offline (`docs/NEEDS.md`);
  - each download sends the user's IP address to Google, a GDPR issue for an
    EU product;
  - golden images would depend on the network.

  The web engine downloads Roboto from `fonts.gstatic.com` at start unless a
  family named `Roboto` is in the font manifest, so `pubspec.yaml` also
  declares a `Roboto` family pointing at the Inter files (review R1-1). The
  engine still fetches Noto fallback fonts from Google for characters Inter
  lacks (emoji, non-Latin scripts) when user-entered text contains them; that
  is accepted for now (Review envelope) and goes into the privacy policy.

  Static files rather than variable fonts, because Flutter does not map
  `fontWeight` onto a variable font's weight axis by itself. The sources and
  sha256 of the files are recorded in `client/assets/fonts/README.md`.

- **D5 — Type scale.** Space Grotesk for display, headline and title styles,
  Inter for body and label styles, using the TraxJourney sizes:

  | Text style | Size / weight / family |
  |---|---|
  | `headlineMedium` | 22 / 700 / Space Grotesk |
  | `titleLarge` (app bar) | 19 / 700 / Space Grotesk |
  | `titleMedium` (card titles) | 16 / 600 / Space Grotesk |
  | `bodyLarge` | 15 / 400 / Inter |
  | `bodyMedium` | 14 / 400 / Inter |
  | `bodySmall` (metadata) | 13 / 400 / Inter |
  | `labelLarge` (buttons) | 15 / 600 / Inter |
  | `labelMedium` (chips) | 12 / 600 / Inter |
  | `labelSmall` (eyebrows) | 12 / 500 / Inter |

  Styles not listed keep Material's sizes, in these two families.

- **D6 — Material widgets themed, custom widgets only where Material has
  none.**
  - **Themed Material widgets**, using the radii and borders below:
    - `FilledButton`, `OutlinedButton`, `TextButton`: 8 px radius, 44 px
      minimum height.
    - `Card`: 12 px radius, 1 px `outline` border, elevation 0.
    - `AppBar`: surface colour, a 1 px bottom border, no elevation and no
      scroll tint.
    - `InputDecoration`, `NavigationBar`, `SnackBar`, `Dialog`.
  - **Custom widgets**, each under `client/lib/src/design/widgets/`:
    - `StatusChip`: a pill. Its variants are `inviteeActivity` (rose
      container), `hidden` (teal container) and `neutral`.
    - `PrivacyBanner`: a teal container holding an eye-off icon and a message.
    - `GiftCard`: the card from the mock-up. It has an image slot (a
      placeholder icon when there is no image), a title, a metadata line, a
      row of chips and an optional action.

  Rules out wrapping every button in a custom widget, which would duplicate
  what the theme already does.

- **D7 — Components take display values, never data.** `GiftCard` takes
  strings and widgets (title, metadata, chips, action), not a gift model. The
  gift model does not exist yet; the lists-and-gifts plan defines it. Deciding
  what a role may see stays with the server and the screen. A component never
  decides whether invitee activity is shown: it shows what it is given. The
  surprise rule is enforced on the server (REVIEW.md E2: a client can be
  modified). The design system only gives that activity its own colour and
  documents where the colour may appear.

- **D8 — Localisation with `gen-l10n`.** Flutter's own tool
  (`flutter_localizations`, `l10n.yaml`, ARB files in `client/lib/l10n/`,
  English as the template, French as the second). The generated class is
  `AppLocalizations`, read through `AppLocalizations.of(context)`. The
  generated code is not committed: `flutter pub get` generates it, in CI and
  in the Docker build alike. Locale: the device's, when it is French or
  English; English otherwise. A test fails when the two ARB files do not have
  the same keys, or when a placeholder differs between them. Rules out
  third-party packages (`easy_localization`, `slang`), which add a dependency
  for features the first release does not need.

- **D9 — Theme mode follows the system.** `ThemeMode.system`. An in-app
  switch is an Open decision for the settings screen.

- **D10 — Golden images are rendered on Linux only.** Golden tests compare
  pixels, and the same Flutter version renders text slightly differently on
  Windows and Linux. The goldens are therefore generated and compared on
  Linux, with Flutter 3.47.1:
  - **CI:** the `client` job compares them as part of `flutter test`.
  - **The owner's Windows machine:** `.\goldens.ps1` regenerates them in a
    Linux container. The container clones the same `FLUTTER_TAG` the
    `Dockerfile` uses. Move the two together.
  - **Other platforms:** golden tests are skipped with a reason
    (`skip: 'goldens render on Linux only: run .\goldens.ps1'`), so the skip
    is visible in the output, not silent.
  - **Fonts in tests:** `client/test/flutter_test_config.dart` loads the
    bundled fonts and the Material icon font before any test runs, so goldens
    show real text and real icons, not the test font's boxes.
  - **Failures:** a failed golden comparison uploads its diff images as a CI
    artifact.

  Rules out comparing goldens with a tolerance on every platform: it hides
  real one-pixel border regressions. It also rules out `alchemist`'s blocked
  text, which cannot check the fonts.

- **D11 — The skeleton screen is the first consumer.** `VersionScreen` is
  restyled with the theme and its strings move to the ARB files, so the
  design system is used, deployed to VAL and visible there, not just written.

## Review envelope

REVIEW.md defaults apply. The change is client-only and presentational:

- No new trust boundary, no new endpoint, no stored data, no new external
  service.
- The app's own UI text never causes a request to Google (D4: bundled fonts
  and a `Roboto` alias). Google-hosted fallback fonts for emoji and non-Latin
  characters in user-entered text are accepted for now (orchestrator's answer
  to the round-1 envelope question, under the owner's standing instruction of
  2026-11-08); self-hosting them is a later decision.
- Nothing in this plan reads invitee activity. D3 and D7 are a convention for
  later plans, not an enforcement point: the server stays the only place the
  surprise rule is enforced.

## Boundaries crossed

None of REVIEW.md F4's: no API, schema, stored-data or export change.

- **App size:** the bundled fonts add about 1–1.5 MB to the web and mobile
  builds.
- **Older clients:** installed builds keep their old look until updated. The
  server is not involved.

## Conventions

- **No hex colour or spacing literal in a screen.** Use the tokens or the
  theme (D1). `tokens.dart` and the theme files are the only places colours
  are written.
- **Only invitee activity is rose.** `WishlistColors.inviteeActivity` and its
  container colours are used only for invitee activity: reservations,
  purchases, pledges, comments and their counts. Nothing else is rose, so that
  a rose element on a recipient's screen would be a visible bug.
- **Every string a user sees comes from the ARB files**, in both languages,
  with sentence case and no emoji. Proper names and user data are the
  exceptions.
- **Every custom widget has goldens.** Each one has golden tests in light and
  dark, and widget tests for its behaviour (tap targets of at least 44 px,
  semantics labels on icon-only controls).
- **Changing a golden is a review item.** A golden PNG changes only in a
  commit that says why the pixels changed.

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| The owner checks the dark palette (D2, D3) on VAL | Dark colours | Before the accounts plan's screens are reviewed; a change here only edits `tokens.dart` and regenerates the goldens |
| In-app language and theme switches (vs. device settings only) | A settings screen, where the preference is stored | The accounts plan (where the user's settings will live) |
| App icon and splash screen | Store listings, web favicon | Before the first store build |
| A design-system reference on the canvas (a "Wishlist Design System" artifact mirroring `tokens.dart`) | Future mock-ups matching the code | Optional; whenever new screens are mocked up |

## Execution units

### Wave 1

#### U1 — Tokens, themes and fonts

- **Goal:** Light and dark `ThemeData` built from Lagoon tokens with
  bundled fonts, applied to the app.
- **Scope:** `client/lib/src/design/tokens.dart`,
  `client/lib/src/design/theme.dart`,
  `client/lib/src/design/wishlist_colors.dart`, `client/assets/fonts/**`,
  `client/pubspec.yaml`, `client/pubspec.lock`, `client/lib/main.dart`,
  `client/test/design/theme_test.dart`,
  `client/test/design/contrast_test.dart`.
- **Context:**
  - D1–D5 and D9 of this plan.
  - Example: TraxJourney's `flutter_client/lib/src/core/theme.dart`
    (`E:\Dev\TraxJourney\flutter_client\lib\src\core\theme.dart`), for the
    shape of a light and dark theme in one file. Do not copy its colours or its
    `fromSeed` use (D2).
  - The mock-up's Lagoon artboard for how cards, buttons and chips look.
- **Do:**
  1. Download static TTFs from upstream:
     - **Inter** 400/500/600/700, from the `rsms/inter` GitHub release
       (v4.x, the `extras/ttf` files);
     - **Space Grotesk** 600/700, from `floriankarsten/space-grotesk`
       (`fonts/ttf/static`).

     Put them in `client/assets/fonts/` with each family's `OFL.txt`.
     `client/assets/fonts/README.md` records, for each file, its source URL,
     its version and its sha256.
  2. Declare both families in `pubspec.yaml` (`fonts:` with weights, and the
     licence files as assets). In `main.dart`, register the two OFL texts with
     `LicenseRegistry.addLicense`.
  3. `tokens.dart`: the colours of D2 and D3, spacing (4, 8, 12, 16, 20, 24,
     32, 40, 48, 64), radii (6, 8, 12, 16, 999) and the type sizes of D5, as
     `const` values with doc comments.
  4. `wishlist_colors.dart`: `WishlistColors extends
     ThemeExtension<WishlistColors>` with the fields of D3, plus `copyWith`,
     `lerp`, a `light` and a `dark` constant, and an extension
     `context.wishlistColors`.
  5. `theme.dart`: `buildLightTheme()` and `buildDarkTheme()`. They return
     `ThemeData` with the hand-written `ColorScheme` (D2), the text theme
     (D5), the component themes of D6, `useMaterial3: true`, and the
     extension.
  6. In `main.dart`, pass `theme`, `darkTheme` and
     `themeMode: ThemeMode.system` to `MaterialApp`.
  7. `contrast_test.dart`: compute the WCAG contrast ratio of each pair below
     in both themes, and assert at least 4.5:1:

     | Foreground | On |
     |---|---|
     | Body text, headings, metadata | Surface and page background |
     | `onPrimary` | `primary` |
     | `onPrimaryContainer` | `primaryContainer` |
     | `onInviteeActivityContainer` | `inviteeActivityContainer` |
     | `primary`, used as link and outlined-button text | Surface |
     | `error` | Surface |
     | `onError` | `error` |

     When a pair fails, adjust that colour within its hue until it passes,
     and report the change.
  8. `theme_test.dart`:
     - each `ColorScheme` role of D2, including the secondary, tertiary,
       surface-container, inverse and error-container rows, has its exact
       value;
     - the extension is present in both themes;
     - `titleMedium` uses Space Grotesk and `bodyMedium` uses Inter;
     - `FilledButton`'s minimum height is 44.
- **Acceptance:**
  - `flutter analyze` reports no issues.
  - `flutter test` passes, including `test/design/theme_test.dart`,
    `test/design/contrast_test.dart` and the existing
    `test/version_screen_test.dart`.
  - `flutter build web --release` succeeds, and the build contains the font
    files under `assets/fonts/`.
  - The built `build/web/assets/FontManifest.json` declares `Inter`,
    `Space Grotesk` and `Roboto` (the alias of D4).
  - Served with `.\dev.ps1`, the skeleton screen's first load shows no
    request to `fonts.gstatic.com` or `fonts.googleapis.com` in Chrome's
    network panel (the verifier checks it with a headless Chrome and the
    DevTools protocol, or reports that it could not).
- **Out of scope:** custom widgets (U3), strings and localisation (U2),
  restyling `VersionScreen` beyond what the theme does by itself (U5), an
  in-app theme switch.
- **Latitude:** decided at routing.
- **Escalate if:**
  - a file outside Scope is needed (X3);
  - static TTFs of either family are not published upstream;
  - a contrast pair cannot reach 4.5:1 without visibly changing its hue.
- **Depends on:** —

#### U4 — Golden tooling

- **Goal:** Goldens can be regenerated from the Windows machine in a Linux
  container that matches CI, and CI keeps the diff images of a failed
  comparison.
- **Scope:** `goldens.ps1`, `.github/workflows/test.yml`,
  `docs/DEVELOPMENT.md`.
- **Context:**
  - D10 of this plan.
  - Examples: `dev.ps1` for the PowerShell style (`Invoke-Native`, errors in
    red, `$ErrorActionPreference = 'Stop'`); the `Dockerfile` lines that
    clone Flutter at `FLUTTER_TAG`.
- **Do:**
  1. `goldens.ps1` at the root. It runs
     `flutter test --update-goldens --tags golden` in `client/`, inside a
     `debian:bookworm-slim` container that clones Flutter at the same tag as
     the `Dockerfile` (3.47.1). The repository is mounted, and the Flutter SDK
     and the pub cache are cached in named volumes so later runs skip the
     clone and the downloads. `client/.dart_tool` and `client/build` are
     covered by container-only volumes, so the container never writes Linux
     package paths into the Windows tree (review R1-2). An optional
     `-Check` switch runs the same tests without `--update-goldens`.
     - A comment names the `Dockerfile`'s `FLUTTER_TAG` and the CI's
       `flutter-version` as the values to move together.
     - Files written into the mounted repository must end up owned by the
       invoking user, not root.
  2. In `test.yml`'s `client` job, add a step after `Run tests` that runs
     only on failure and uploads `client/test/**/failures/` with
     `actions/upload-artifact` (pinned the way the workflow pins its other
     actions).
  3. `docs/DEVELOPMENT.md`: a "Golden tests" section. It covers what goldens
     are, why they render on Linux only, how to regenerate them
     (`.\goldens.ps1`), how to read a CI failure (the artifact), and the rule
     that a golden changes only with a stated reason.
- **Acceptance:**
  - `actionlint` passes on `test.yml`.
  - With a throw-away golden test tagged `golden` (there are none yet, and
    `flutter test --tags golden` with no matching test exits non-zero, review
    R1-3): `.\goldens.ps1` writes its PNG, owned by the owner's user and not
    root; `.\goldens.ps1 -Check` then exits 0; the test and PNG are deleted
    afterwards.
  - A second run reuses the cached SDK; the log shows no clone.
  - Right after a goldens run, `flutter test` on Windows in `client/` still
    passes without running `flutter pub get` by hand.
- **Out of scope:** writing golden tests (U3, U5), changing how the server job
  runs, Linux or macOS dev machines.
- **Latitude:** decided at routing.
- **Escalate if:**
  - a file outside Scope is needed (X3);
  - Docker Desktop's file sharing makes the bind mount unusable or too slow
    (more than 10 minutes for an empty run after the first).
- **Depends on:** —

### Wave 2

#### U2 — Localisation scaffolding

- **Goal:** All user-visible strings come from English and French ARB files
  through `gen-l10n`, and the app follows the device language.
- **Scope:** `client/l10n.yaml`, `client/lib/l10n/app_en.arb`,
  `client/lib/l10n/app_fr.arb`, `client/pubspec.yaml`,
  `client/pubspec.lock`, `client/lib/main.dart`,
  `client/lib/src/version_screen.dart`,
  `client/lib/src/server_version.dart`,
  `client/test/l10n/arb_parity_test.dart`,
  `client/test/version_screen_test.dart`, `.gitignore`.
- **Context:**
  - D8 of this plan.
  - The Flutter internationalisation guide (gen-l10n, with
    `flutter: generate: true`).
  - Example: `version_screen.dart`'s current strings are the full list to
    move.
- **Do:**
  1. Add `flutter_localizations` (from the SDK) and `intl` (the version
     `flutter_localizations` pins), and set `generate: true`. In `l10n.yaml`:
     the ARB directory, `app_en.arb` as the template, the output class
     `AppLocalizations`, and `nullable-getter: false`.
  2. Move every string `VersionScreen` shows into `app_en.arb`, each with a
     `@` description, and translate them into `app_fr.arb`:
     - "App {version}";
     - "Server {version} ({env})";
     - the four error messages of `server_version.dart`.

     `ServerVersionException` then carries a reason enum, not a message, and
     the screen maps each reason to its localised string. The HTTP status
     stays a placeholder.
  3. In `main.dart`, set `localizationsDelegates`, `supportedLocales`
     (en, fr) and `onGenerateTitle` from the ARB. Fallback: English.
  4. `arb_parity_test.dart` reads both ARB files and fails when:
     - their message keys differ;
     - a message's placeholders differ between them;
     - a key lacks its `@` description in the template.
  5. Update `version_screen_test.dart` for the reason enum. Add one test that
     pumps the app in French and finds the French text.
  6. Make sure the generated output is not committed. It goes to
     `.dart_tool/`, the default with `generate: true`. Add a `.gitignore`
     entry only if a generated file appears elsewhere.
- **Acceptance:**
  - `flutter analyze` reports no issues.
  - `flutter test` passes, including `test/l10n/arb_parity_test.dart` and
    the new French test in `test/version_screen_test.dart`.
  - `flutter build web --release` succeeds from a clean clone, where
    `flutter pub get` generates the localisation code.
  - `grep -rn "Text('" client/lib` finds no literal user-facing string.
- **Out of scope:** an in-app language switch, languages other than en and
  fr, localising server error bodies (the server sends none yet).
- **Latitude:** decided at routing.
- **Escalate if:**
  - a file outside Scope is needed (X3);
  - the Dockerfile's web build does not run `gen-l10n` by itself.
- **Depends on:** U1 (both change `pubspec.yaml` and `main.dart`).

#### U3 — Shared widgets and goldens

- **Goal:** `StatusChip`, `PrivacyBanner` and `GiftCard` exist, styled from
  the theme, with widget tests and Linux goldens in light and dark.
- **Scope:** `client/lib/src/design/widgets/**`,
  `client/test/design/widgets/**`, `client/test/flutter_test_config.dart`,
  `client/dart_test.yaml`.
- **Context:**
  - D3, D6, D7 and D10 of this plan.
  - The mock-up's Lagoon phone screen, which is the target for `GiftCard` and
    the chips.
  - Example: `client/lib/src/version_screen.dart` for widget file style, and
    `client/test/version_screen_test.dart` for test style.
- **Do:**
  1. `dart_test.yaml` declares the `golden` tag.
  2. `flutter_test_config.dart` loads the bundled Inter and Space Grotesk
     fonts and the Material icon font, using `FontLoader` with the assets
     declared in `pubspec.yaml` and the SDK's `MaterialIcons-Regular.otf`,
     before running the tests.
  3. `StatusChip`: variants `inviteeActivity`, `hidden` and `neutral`; a
     label; an optional leading icon. Colours come from `WishlistColors` and
     the `ColorScheme`; text style `labelMedium`.
  4. `PrivacyBanner`: a message (a `String` given by the caller) on
     `primaryContainer`, with an eye-off icon marked as decorative for
     semantics.
  5. `GiftCard`:
     - title, an optional metadata line, an optional `ImageProvider` image
       (when there is none, a gift-icon placeholder on `primaryContainer`),
       a list of chip widgets and an optional action widget;
     - an optional `onTap` for the whole card;
     - layout as in the mock-up: a 64 px image with an 8 px radius, a 12 px
       gap, and a card with 14 px padding and a 12 px radius;
     - long titles wrap to two lines and then end with an ellipsis.
  6. Widget tests:
     - each `StatusChip` variant uses its colours;
     - a `GiftCard` with no chips renders none;
     - `onTap` fires;
     - the action keeps a hit area of at least 44 px;
     - the banner's icon is excluded from semantics.
  7. Golden tests, tagged `golden`, on a 390-px-wide surface, in light and
     dark:
     - every chip variant;
     - the banner;
     - `GiftCard` with no chips, with chips, with an action, with a long
       title, and with no image.

     On platforms other than Linux they are skipped with the D10 reason.
     Generate the PNGs with `.\goldens.ps1` (U4).
- **Acceptance:**
  - `flutter analyze` reports no issues.
  - `flutter test` passes on Windows, with the golden tests reported as
    skipped together with their reason.
  - `.\goldens.ps1 -Check` passes, which means the goldens match on Linux.
  - The golden PNGs are committed under `client/test/design/widgets/goldens/`.
- **Out of scope:** a gift model, screens, navigation, image fetching or
  caching (the lists-and-gifts plan), animations.
- **Latitude:** decided at routing.
- **Escalate if:**
  - a file outside Scope is needed (X3), including `pubspec.yaml`;
  - the SDK's Material icon font is not where `flutter_test_config.dart` can
    load it in both the container and CI.
- **Depends on:** U1 (theme and fonts), U4 (`goldens.ps1`).

### Wave 3

#### U5 — Skeleton screen restyled, and the design reference

- **Goal:** `VersionScreen` uses the design system end to end, and
  `docs/DESIGN.md` is the living reference later plans follow.
- **Scope:** `client/lib/src/version_screen.dart`,
  `client/test/version_screen_test.dart`,
  `client/test/version_screen_golden_test.dart`,
  `client/test/goldens/**`, `docs/DESIGN.md`, `docs/README.md`.
- **Context:**
  - D11 and the Conventions of this plan.
  - The Lagoon artboard for the app bar and the page background.
  - Example for the reference doc: `docs/DEVELOPMENT.md`, for tone and
    structure.
- **Do:**
  1. Restyle `VersionScreen`:
     - the themed app bar, with the title from the ARB;
     - the app version and the server's version in a card, laid out with
       spacing tokens;
     - errors in the `error` colour, with an error icon.

     No literals except tokens.
  2. Goldens, tagged `golden`, at 390×844: light and dark, in English and in
     French, for both the success state and the unreachable state. That is 8
     images.
  3. Write `docs/DESIGN.md`:
     - **Foundations:** the TraxJourney foundations and the Lagoon choice,
       with a link to the mock-ups.
     - **Tokens:** a table of the tokens and where they live.
     - **Typography:** the type scale.
     - **Components:** when to use a themed Material widget and when a custom
       one.
     - **Invitee colour:** the rule from Conventions, quoted.
     - **Localisation:** how to add a string in both languages.
     - **Goldens:** a link to `docs/DEVELOPMENT.md`.

     Link `docs/DESIGN.md` from `docs/README.md`.
- **Acceptance:**
  - `flutter analyze` reports no issues.
  - `flutter test` passes; on Windows the goldens are skipped and the reason
    is shown.
  - `.\goldens.ps1 -Check` passes.
  - The existing widget tests still pass, unchanged apart from what U2
    changed.
  - `docs/DESIGN.md` exists and is linked from `docs/README.md`.
- **Out of scope:** new screens, navigation, a bottom navigation bar (there is
  one screen), an in-app theme or language switch.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U2, U3.

## Definition of done

- The app opens in the Lagoon theme, light or dark following the device, with
  Inter and Space Grotesk, on web (`.\dev.ps1`), on VAL after the `validation`
  tag, and in an Android emulator build.
- With the device in French, every string on the skeleton screen is in French.
  `arb_parity_test.dart` fails if a key is missing from either language.
- Loading the app shows no request to `fonts.googleapis.com` or
  `fonts.gstatic.com` for its own UI text (checked in the browser's network
  panel on VAL); fallback fonts for emoji or non-Latin user text are the
  accepted exception (Review envelope).
- `StatusChip`, `PrivacyBanner` and `GiftCard` exist, and each has widget
  tests and light and dark goldens.
- `contrast_test.dart` proves every listed text pair reaches 4.5:1 in both
  themes.
- CI's `client` job compares the goldens on Linux, and uploads the diff images
  when one fails. `.\goldens.ps1` regenerates them identically on the Windows
  machine.
- `docs/DESIGN.md` documents the tokens, the components, the invitee-colour
  rule and the localisation workflow.
- No hex colour or spacing literal outside `client/lib/src/design/`
  (`grep -rnE "Color\(0x|EdgeInsets\.all\([0-9]" client/lib --exclude-dir=design`
  finds nothing).
