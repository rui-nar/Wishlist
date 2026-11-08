# Web layout and welcome page

## Problem

On a computer the web client looks like a phone app stretched to the window
(owner's review of VAL, 2026-11-08):

- every screen's content runs the full window width: list cards, gift cards
  and form fields 1,900 px wide on a desktop monitor;
- home's two destinations are switched by a phone navigation bar at the
  bottom of the window;
- the page background is a flat light slate (`#F1F5F9`) that reads as white;
- a signed-out visitor lands straight on a sign-in card that does not say what
  the site is for, and there is no way to register as such.

The owner asked for a web layout that looks like a web app, a welcome page
explaining the site's purpose with "Log in" and "Register" buttons, and a
non-white background with a modern abstract motif.

## Current state

- `client/lib/src/app_router.dart`: `authRedirect` sends every signed-out
  location but `/sign-in` to `/sign-in?from=<location>` (`/` without `from`).
  `safeFrom` validates the return. Share links (`/join#<token>`) rely on that
  return, with their token held by `PendingJoin`.
- `client/lib/src/auth/sign_in_screen.dart`: one card with the app name, a
  prompt and Google's button (web) or a themed button (mobile). Signing in
  with Google for the first time creates the account (ACCOUNTS_PLAN D3); there
  is no separate registration.
- `client/lib/src/home/home_screen.dart`: `HomeScreen` hands a
  `NavigationBar` to `MyListsScreen` / `SharedWithMeScreen`, which put it in
  their scaffold's `bottomNavigationBar`.
- Every screen is a `Scaffold` with an `AppBar` and a body padded with
  `Spacing.s16`, with no maximum width.
- `client/lib/src/design/`: tokens (`tokens.dart`), themes (`theme.dart`,
  `scaffoldBackgroundColor` = `pageBackground`), `WishlistColors` theme
  extension, widgets (gift card, status chip, privacy banner), documented in
  `docs/DESIGN.md`. Goldens render on Linux only through `goldens.ps1`.
- Rose is reserved for invitee activity (DESIGN_SYSTEM_PLAN D3).

## Decisions

- **D1 — Window classes.** Material 3's widths: compact below 600 px, medium
  600–839, expanded from 840. Written once in `tokens.dart` as
  `Breakpoints.medium = 600` and `Breakpoints.expanded = 840`. The layout
  reads the width of the window (`MediaQuery.sizeOf`), not the platform: a
  narrow browser window gets the phone layout, a tablet the wide one. Rules
  out a web-only layout chosen by `kIsWeb`, which would give a phone browser
  the desktop layout.
- **D2 — Content width.** Page content is centred and capped:
  `ContentWidths.reading = 760` for lists, details and the account screen,
  `ContentWidths.form = 560` for forms, `ContentWidths.welcome = 1120` for the
  welcome page. Below the cap it fills the window with the existing
  `Spacing.s16` padding (`Spacing.s24` from medium). A shared `PageFrame`
  widget does this so no screen computes widths itself. Rules out a
  multi-column master-detail layout: it would change navigation and every
  screen's tests for a first web pass; it can come later on top of `PageFrame`.
- **D3 — Home navigation.** Compact and medium keep the bottom
  `NavigationBar`. Expanded replaces it with a `NavigationRail` on the left
  (icons and labels, the same two destinations, the same `context.go`
  locations), and the destination's scaffold gets no bottom bar. The rail is
  drawn by `HomeScreen`, beside the destination's scaffold, so the two
  destination screens only lose their bottom bar. Crossing the breakpoint
  (a window resized, a tablet rotated) keeps the destination screen's state:
  `HomeScreen` builds the same tree shape in every class (a `Row` whose
  rail is present only when expanded, the screen in a trailing `Expanded`,
  keyed if needed), so the lists are not fetched again and the scroll
  position stays (review R1-2). Rules out a top tab bar,
  which would be one more pattern than Material's adaptive navigation.
- **D4 — Backdrop.** Behind every page, a `Backdrop` widget paints the page
  background colour and an abstract motif: a few large, soft, overlapping
  curved shapes (`CustomPainter`, gradients, no image asset, no randomness:
  the same window size always draws the same picture), anchored to the
  top-right and bottom-left corners so the centre, where content sits, stays
  calm. Colours: teal and slate tints only, never rose (rose means invitee
  activity, DESIGN_SYSTEM_PLAN D3), new tokens `motifA`, `motifB`, `motifC` in
  `LightColors` / `DarkColors`, carried by `WishlistColors`. The motif is
  stronger on the welcome page (`BackdropIntensity.bold`) than behind app
  screens (`BackdropIntensity.subtle`). `PageFrame` draws it as the bottom
  layer of each page's body, so each scaffold stays opaque and page
  transitions do not show two pages at once. Rules out a background behind
  the `Navigator` with transparent scaffolds (pages would bleed into each
  other during transitions) and a bitmap (one more asset per theme and
  density).
- **D5 — Text on the motif.** Text drawn straight on the page (headings,
  empty states, the welcome hero) keeps WCAG AA: the motif's tints are light
  enough (dark: dark enough) that `bodyText`, `onSurface` and
  `onSurfaceVariant` reach 4.5:1 on each motif colour, checked by
  `contrast_test.dart`. Cards keep their opaque surface.
- **D6 — Welcome page at `/welcome`.** A signed-out visitor at `/` is sent to
  `/welcome` instead of `/sign-in`. Every other signed-out location still goes
  to `/sign-in?from=<location>`, so share links and deep links behave as
  today. A signed-in user at `/welcome` goes to `/`. `/welcome` is public, like
  `/sign-in`, and so is the version screen `/about`, which the welcome page's
  footer links to: it shows the app's and the server's versions only, and
  `/api/version` is already public (review R1-1). Rules out showing the welcome content on `/` itself (one route
  meaning two pages depending on the session makes the guard harder to
  reason about) and sending deep links to the welcome page (it would add a
  click before every join).
- **D7 — Log in and Register.** The welcome page has two buttons: "Log in"
  → `/sign-in`, "Register" → `/sign-in?mode=register`. With Google the two are
  the same act, since the first Google sign-in creates the account; the
  register mode changes only the sign-in card's heading and prompt ("Create
  your account" / "Your Google account is all you need"). `mode` is ignored
  for any other value and is not carried into `from`. When email and password
  sign-in arrives (NEEDS.md, Constraints), Register gets its own form behind
  the same button. The sign-in card gains a "What is Wishlist?" link back to
  `/welcome`, shown only when no `from` is set (someone arriving from a share
  link is mid-flow). Rules out a Register button that pretends to be a
  different flow.
- **D8 — Welcome content.** A hero (the app name, a headline, one sentence
  on the purpose, the two buttons), then three short feature cards, then a
  footer with the version link (`/about`). Copy, EN and FR in the ARB files:
  - headline: "Wish lists for every occasion" / "Des listes d'envies pour
    chaque occasion";
  - purpose: "Keep the things you'd love to receive, share them with family
    and friends for each occasion, and let them coordinate without spoiling
    the surprise." / FR equivalent;
  - "Lists for everything you wish for": permanent lists, for you or for
    someone else (a child);
  - "Shared for each occasion": Christmas, a birthday… invite people with a
    link;
  - "The surprise stays a surprise": what invitees do on your list stays
    hidden from you.
  The copy states the product's purpose (NEEDS.md, Problem) and claims
  nothing the first release does not do: reserving is described as invitees
  coordinating, not as a feature list.
- **D9 — Every screen.** All screens put their body in a `PageFrame` with
  the width of D2; the sign-in screen and the welcome page use the bold
  backdrop, the others the subtle one. App bars keep the full window width.
  The version screen (`/about`) too. On expanded windows, home's two
  destinations have the rail on the left and their app bar spans the rest of
  the width, as in Material's adaptive layout (review R1-4).

## Review envelope

REVIEW.md defaults apply. The change is client-only and presentational, with
one routing change:

- No new endpoint, no stored data, no new external service.
- The guard change (D6) adds two public routes, `/welcome` and `/about`,
  neither showing user data. The auth boundary is the
  server; the client guard only decides which page shows, so a mistake there
  is a wrong page, not access. `safeFrom` is unchanged.
- Nothing here reads or shows invitee activity; the server stays the only
  place the surprise rule is enforced. The welcome page shows no user data.

## Boundaries crossed

None of REVIEW.md F4's: no API, schema, stored-data or export change.

- **URLs:** `/welcome` is new. Bookmarks of `/sign-in` keep working.
- **Older clients:** a cached old web build keeps the old layout until
  reloaded; the server is not involved.

## Conventions

- No colour, width or spacing literal in a screen (`docs/DESIGN.md`, Tokens):
  breakpoints, content widths and motif colours are tokens.
- New user-visible text goes through the ARB files, EN and FR, sentence case,
  no emoji.
- Golden images are regenerated with `.\goldens.ps1` only (Linux, Docker),
  never on Windows.

## Open decisions

None blocking. Later: a master-detail layout for lists on expanded windows
(D2), a theme switch.

## Execution units

### Wave 1

#### U1 — Breakpoints, page frame and backdrop

- **Goal:** the design system gains window classes, content widths, a
  `PageFrame` and a `Backdrop` with an abstract motif in light and dark.
- **Scope:** `client/lib/src/design/tokens.dart`,
  `client/lib/src/design/wishlist_colors.dart`,
  `client/lib/src/design/theme.dart` (only to carry the new colours),
  `client/lib/src/design/widgets/page_frame.dart` (new),
  `client/lib/src/design/widgets/backdrop.dart` (new),
  `client/test/design/**` (new tests and goldens; `contrast_test.dart`),
  `docs/DESIGN.md`.
- **Context:** `docs/DESIGN.md`; this plan D1, D2, D4, D5. Example to follow:
  `client/lib/src/design/widgets/privacy_banner.dart` and its test and goldens
  under `client/test/design/widgets/`.
- **Do:**
  1. Tokens: `Breakpoints` (D1), `ContentWidths` (D2), motif colours (D4) in
     both palettes; `WishlistColors` carries the motif colours (with `lerp`).
  2. `Backdrop({required Widget child, BackdropIntensity intensity})`: fills
     its constraints with `pageBackground` and paints the motif behind
     `child`. Deterministic, no assets, no animation.
  3. `PageFrame({required Widget child, double maxWidth, BackdropIntensity
     intensity, EdgeInsets? padding})`: `Backdrop` filling the body, the
     child centred horizontally, capped at `maxWidth`, padded `Spacing.s16`
     (compact) or `Spacing.s24` (medium and up). Does not scroll by itself:
     the child keeps its own `ListView` / `SingleChildScrollView`, and the
     frame must work with both a scrolling child and a `Center`ed one.
     A scrolling child scrolls under the full width (the scroll bar stays at
     the window edge, and the wheel scrolls anywhere over the page), with its
     content capped. The mechanism is fixed (review R1-3): the frame gives a
     scrolling child the full width, and the child's scroll view takes its
     padding from `PageFrame.paddingOf(context, maxWidth)`, which returns the
     class padding plus the side margins that centre a column of `maxWidth`.
     A non-scrolling child (`PageFrame.centered`) is centred and capped by
     the frame itself. DESIGN.md says which to use when.
  4. Contrast pairs for D5 in `contrast_test.dart`.
  5. `docs/DESIGN.md`: a "Layout" section (window classes, content widths,
     `PageFrame`, backdrop, rose never in the motif).
- **Acceptance:** `flutter analyze` clean; `flutter test` passes; new tests:
  `PageFrame` caps the child at `maxWidth` on a 1440 px window and fills a
  390 px one, padding per class; a `ListView` child scrolls inside it;
  `Backdrop` paints with no rose (test the colours it is given);
  contrast pairs pass; goldens of the backdrop, light and dark, subtle and
  bold, at 390×844 and 1440×900 generated with `.\goldens.ps1` and
  checked with `.\goldens.ps1 -Check`; the token grep in DESIGN.md finds
  nothing outside `design/`.
- **Out of scope:** changing any screen, the router, the theme's other
  colours.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the motif cannot keep
  D5's contrast; `PageFrame` cannot serve both scrolling and centred children
  without each screen changing more than its body wrapper.
- **Depends on:** —

### Wave 2

#### U2 — Welcome page, guard and sign-in screen

- **Goal:** signed-out visitors land on a welcome page explaining the site,
  with Log in and Register, and the sign-in screen sits on the bold backdrop.
- **Scope:** `client/lib/src/app_router.dart`,
  `client/lib/src/welcome/welcome_screen.dart` (new),
  `client/lib/src/auth/sign_in_screen.dart`,
  `client/lib/src/auth/account_screen.dart` (body in `PageFrame` only),
  `client/lib/l10n/*.arb`, `client/test/app_router_test.dart`,
  `client/test/welcome/**` (new), `client/test/auth/**`,
  `client/test/auth_screens_golden_test.dart`, `client/test/goldens/**`,
  `client/test/l10n/**`.
- **Context:** this plan D6–D9; `docs/DESIGN.md` (Layout, from U1);
  `authRedirect` and its tests. Example to follow: `sign_in_screen.dart` and
  `auth_screens_golden_test.dart`.
- **Do:**
  1. `authRedirect`: signed out at `/` (no query) → `/welcome`;
     `/welcome` and `/about` pass signed out; signed in at `/welcome` → `/`.
     Everything else unchanged. Add `kWelcomePath`. Register the route.
  2. `WelcomeScreen` per D8, in a `PageFrame(maxWidth: ContentWidths.welcome,
     intensity: bold)`, with no app bar: hero left and feature cards right on
     expanded windows, stacked on compact. Buttons: Register filled, Log in
     outlined.
  3. Sign-in screen: `PageFrame` (form width, bold); register mode per D7
     (`mode=register` → other heading and prompt); "What is Wishlist?" link to
     `/welcome` when no `from`.
  4. Account screen body in `PageFrame` (reading width).
  5. ARB strings EN and FR.
- **Acceptance:** `flutter analyze` clean; `flutter test` passes; tests:
  `authRedirect` cases for D6 (signed out `/` → `/welcome`; `/welcome`
  and `/about` pass, the existing `/about?x=1` expectation changing to pass; signed in `/welcome` → `/`; signed out `/account` still →
  `/sign-in?from=/account`; `/join` still → `/sign-in?from=/join`);
  welcome screen: both buttons navigate to the right location, both
  languages render; sign-in screen: register heading with `mode=register`,
  normal heading otherwise and for an unknown mode, the welcome link only
  without `from`; ARB parity test passes; goldens (welcome 390×844 and
  1440×900, light and dark, EN; sign-in and account updated) regenerated
  with `.\goldens.ps1` and passing `.\goldens.ps1 -Check`.
- **Out of scope:** other screens, email/password registration, any server
  change, analytics.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); the redirect change
  would alter any existing `authRedirect` test's expectation other than
  signed-out `/` and signed-out `/about`.
- **Depends on:** U1.

### Wave 3

#### U3 — Wide layout for home and the signed-in screens

- **Goal:** every signed-in screen is capped and centred on the backdrop, and
  home uses a navigation rail on expanded windows.
- **Scope:** `client/lib/src/home/home_screen.dart`,
  `client/lib/src/lists/*.dart` (screens only: body wrappers, the bottom bar
  parameter), `client/lib/src/shared/*_screen.dart`,
  `client/lib/src/version_screen.dart`, `client/test/home/**`,
  `client/test/lists/**`, `client/test/shared/**`,
  `client/test/version_screen*.dart`, `client/test/goldens/version_*`.
- **Context:** this plan D2, D3, D9; `docs/DESIGN.md` (Layout). Example to
  follow: the account screen as U2 left it.
- **Do:**
  1. `HomeScreen`: below `Breakpoints.expanded` as today; from it, a `Row` of
     a `NavigationRail` (labels shown, same destinations and locations) and
     the destination screen without a bottom bar.
  2. Each screen's body in a `PageFrame` (U1's `paddingOf` for scroll views,
     whose padding this unit changes, `centered` otherwise): reading width for my lists, list
     detail, shared with me, occasion, occasion members, join and version;
     form width for the list, gift and occasion forms. Subtle backdrop.
  3. Update the goldens these screens have (lists goldens, version screen
     goldens) and add a 1440×900 golden of my lists and of list detail, light
     and dark.
- **Acceptance:** `flutter analyze` clean; `flutter test` passes; tests: home
  shows a `NavigationBar` and no rail at 390 px, a `NavigationRail` and no bar
  at 1280 px, and selecting the rail's second destination goes to `/shared`;
  resizing my lists from 800 to 1280 px and back issues no second
  `GET /api/lists` (R1-2);
  a list card's width is at most `ContentWidths.reading` at 1440 px; the
  existing screen tests pass unchanged apart from goldens; goldens regenerated
  with `.\goldens.ps1` and passing `.\goldens.ps1 -Check`.
- **Out of scope:** master-detail layouts, new features, the welcome and
  sign-in screens, the router.
- **Latitude:** local design.
- **Escalate if:** a file outside Scope is needed (X3); a screen needs more
  than its body wrapper, its scroll view's padding and its bottom bar to fit
  the frame.
- **Depends on:** U1, U2 (U2 touches the shared golden folder and l10n).

## Definition of done

- At 1440×900 no screen's content is wider than its D2 width, and home shows
  a navigation rail instead of a bottom bar; at 390×844 the layout is as
  before apart from the backdrop.
- Every page shows the abstract backdrop, in light and dark, with no rose in
  it, and the contrast test covers text on it.
- A signed-out visit to `/` shows the welcome page; Log in and Register lead
  to the sign-in screen, Register with its own heading; share links still go
  straight to sign-in and then to the join screen.
- All §2 checks pass, goldens included, and the new behaviour has tests.
