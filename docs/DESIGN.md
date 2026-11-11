# Design

How the Shush Gift client looks and how a screen uses the design system:
tokens, themes, components, the invitee colour and localisation. The code is
in `client/lib/src/design/`; the decisions behind it are in
[the design-system plan](plans/DESIGN_SYSTEM_PLAN.md). The skeleton screen,
`client/lib/src/version_screen.dart`, is the smallest working example.

## Foundations

The look is "Lagoon", the direction the owner chose (`docs/NEEDS.md`,
Constraints). The mock-ups it was chosen from are at
https://claude.ai/artifact/PSc8n5pwZLeVxvLCPHNVmi (artboard "C · Lagoon",
private to the owner).

Lagoon builds on TraxJourney's design foundations:

- Inter for text, Space Grotesk for titles, both bundled with the app and
  never downloaded (plan D4);
- an 8-point spacing grid;
- radii of 6, 8, 12 and 16;
- flat cards with a 1 px border and no shadow;
- slate greys, a teal accent (`#0F766E` in light), and rose for invitee
  activity only;
- sentence case, no emoji, Material outlined icons.

The app has a light and a dark theme and follows the device's setting
(plan D9). There is no in-app switch yet.

## Tokens

Every colour, spacing, radius and type size is a `const` in one file,
`client/lib/src/design/tokens.dart`. Screens read them from there or from the
theme. **No hex colour or spacing literal appears in a screen**: if a value is
missing, add it to `tokens.dart` rather than writing it inline. This finds
nothing outside the design folder:

```bash
grep -rnE "Color\(0x|EdgeInsets\.all\([0-9]" client/lib --exclude-dir=design
```

| Token | Where it lives | How a screen reads it |
|---|---|---|
| Colours with a Material role (`primary`, `surface`, `onSurfaceVariant`, `outline`, `error`...) | `LightColors`, `DarkColors` | `Theme.of(context).colorScheme` |
| Page background, body text | `LightColors`, `DarkColors`, carried by `ShushGiftColors` | `context.shushGiftColors` (`scaffoldBackgroundColor` and the body text styles already use them) |
| Invitee activity (rose) and its container colours | `LightColors`, `DarkColors`, carried by `ShushGiftColors` | `context.shushGiftColors`, for invitee activity only (below) |
| Backdrop motif: `motifA`, `motifB`, `motifC` | `LightColors`, `DarkColors`, carried by `ShushGiftColors` | never directly: `Backdrop` paints them (Layout, below) |
| Window classes: `medium` 600, `expanded` 840 | `Breakpoints` | against `MediaQuery.sizeOf(context).width` (Layout) |
| Content widths: `reading` 760, `form` 560, `welcome` 1120 | `ContentWidths` | through `PageFrame` (Layout) |
| Spacing: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 | `Spacing.s4` ... `Spacing.s64` | directly: `EdgeInsets.all(Spacing.s16)` |
| Radii: `sm` 6 (tags, thumbnails), `md` 8 (buttons, fields), `lg` 12 (cards), `xl` 16 (dialogs, sheets), `pill` | `Radii` | directly, or through the themed widget |
| Font families | `FontFamilies.display`, `FontFamilies.text` | through the text theme |
| Type sizes | `TypeSizes` | through the text theme (below) |

The full palette, light and dark, is the table in plan D2. The colour scheme
is written out role by role in `client/lib/src/design/theme.dart`, never
seeded, so no Material default colour leaks in.

### Contrast

`client/test/design/contrast_test.dart` checks that every text colour on the
background it is drawn on reaches 4.5:1 (WCAG AA), in both themes. When a
screen draws text in a new foreground and background pair, add the pair to
the test; if it fails, change the colour in `tokens.dart`, not the test.

One pair is known to need this. `onSurfaceVariant` (hints, labels, metadata)
on `surfaceContainerHighest` is 4.04:1 in dark, below the bar. Text fields are
filled with `surface` today, so nothing draws it. **If text fields are filled
with `surfaceContainerHighest`, or any screen draws `onSurfaceVariant` text on
it, add that pair to the contrast test first**, and fix the colour if it
fails (review item R2-1 of [the plan's review](reviews/DESIGN_SYSTEM_PLAN.md)).

## Typography

Space Grotesk for display, headline and title styles, Inter for body and
label styles. Use the styles of `Theme.of(context).textTheme`, never a
`TextStyle` with a size of its own.

| Text style | Size / weight / family | Used for |
|---|---|---|
| `headlineMedium` | 22 / 700 / Space Grotesk | Page headings |
| `titleLarge` | 19 / 700 / Space Grotesk | App bar title |
| `titleMedium` | 16 / 500 / Space Grotesk | Card titles |
| `bodyLarge` | 15 / 400 / Inter | Main text |
| `bodyMedium` | 14 / 400 / Inter | Secondary text, banners |
| `bodySmall` | 13 / 400 / Inter | Metadata, in `onSurfaceVariant` |
| `labelLarge` | 15 / 600 / Inter | Buttons |
| `labelMedium` | 12 / 600 / Inter | Chips |
| `labelSmall` | 12 / 500 / Inter | Eyebrows |

Body styles are already in the body-text colour. To colour a style, use
`copyWith(color: ...)` with a theme colour, as the skeleton screen does for
its error message.

Card titles are Space Grotesk Medium (500): no static 600 exists upstream.
Adding a weight means adding its file to `client/assets/fonts/`,
`pubspec.yaml`, `client/assets/fonts/README.md` and
`client/test/flutter_test_config.dart`, which loads the fonts for tests.

## Components

**Use a themed Material widget whenever Material has one.** The theme already
gives these the Lagoon look, so a screen uses them as they are, without
styling:

| Widget | What the theme sets |
|---|---|
| `FilledButton`, `OutlinedButton`, `TextButton` | 8 px radius, at least 44 px tall |
| `Card` | 12 px radius, 1 px `outline` border, no shadow, no margin |
| `AppBar` | `surface` colour, 1 px bottom border, no elevation or scroll tint |
| `TextField` (`InputDecoration`) | filled with `surface`, 8 px radius, `outline` border, 2 px `primary` when focused |
| `NavigationBar`, `SnackBar`, `Dialog` | surface colours, no tint, the radii above |

Do not wrap a Material widget in a custom one to style it: change the theme in
`theme.dart` instead, so every screen gets the change.

**Use a custom widget only where Material has none.** They are in
`client/lib/src/design/widgets/`:

| Widget | What it is |
|---|---|
| `StatusChip` | A pill. Variants: `inviteeActivity` (rose), `hidden` (teal) and `neutral` |
| `PrivacyBanner` | A teal container with an eye-off icon and a message, telling someone what is hidden from them |
| `GiftCard` | The gift card of the mock-up: image slot, title, metadata line, chips, optional action. The slot shows the placeholder when there is no image or it fails to load; with `onImageTap` the image is tappable (its 64 px exceed the 44 px hit area) and the tap does not reach the card's own |
| `showImageViewer` | A full-screen dialog with the image in an `InteractiveViewer` (pinch and drag to zoom) and a close button with a tooltip (the one string a design widget takes from `AppLocalizations`). Opened by the card's `onImageTap` |
| `PageFrame`, `Backdrop` | A page's body: content capped and centred on the abstract backdrop (Layout, below) |

**Components take display values, never data** (plan D7). A component gets
strings and widgets, not a gift or a list. It never decides what a role may
see: it shows what it is given. Deciding is the screen's job, and enforcing
the surprise rule is the server's.

A new custom widget gets widget tests for its behaviour (tap targets of at
least 44 px, semantics labels on icon-only controls) and goldens in light and
dark.

## Layout

How a page sits in the window, from a phone to a desktop monitor
([the web layout plan](plans/WEB_LAYOUT_PLAN.md), D1, D2, D4, D5).

**Window classes.** Material 3's: compact below `Breakpoints.medium` (600 px),
medium up to `Breakpoints.expanded` (840 px), expanded from there. A layout
compares `MediaQuery.sizeOf(context).width` with them, never the platform or
`kIsWeb`: a narrow browser window gets the phone layout, a tablet the wide
one.

**Content widths.** Page content is a centred column, capped at
`ContentWidths.reading` (760) for lists, details and the account screen,
`ContentWidths.form` (560) for forms and `ContentWidths.welcome` (1120) for
the welcome page. Below the cap it fills the window, padded `Spacing.s16` on
compact windows and `Spacing.s24` from medium. App bars keep the full window
width.

**`PageFrame`** (`design/widgets/page_frame.dart`) does this, so no screen
computes a width. Every page puts its body in one, in one of two forms:

- **A body that scrolls** (`ListView`, `SingleChildScrollView`): `PageFrame`,
  with the scroll view's padding from `PageFrame.paddingOf(context, width)`.
  The scroll view spans the window, so the scroll bar stays at the window
  edge and the wheel scrolls anywhere over the page, while its content is
  capped:

  ```dart
  body: PageFrame(
    child: ListView(
      padding: PageFrame.paddingOf(context, ContentWidths.reading),
      children: [...],
    ),
  ),
  ```

- **A body that does not scroll by itself** (a `Center`ed card, a short
  `Column`): `PageFrame.centered(maxWidth: ContentWidths.form, child: ...)`.
  The frame pads it, caps it and centres it horizontally; a `Center` child
  still centres vertically. `padding:` replaces the class padding when a page
  needs its own.

`paddingOf` measures the window. A page drawn beside something else, such as
a navigation rail, gets a column narrower by that thing's width, still
centred.

**Backdrop.** `PageFrame` draws a `Backdrop` (`design/widgets/backdrop.dart`)
as the bottom layer of the body: the page background and an abstract motif of
large, soft, overlapping curved shapes, anchored to the top-right and
bottom-left corners so the centre stays calm. It is painted, not an image,
and has no randomness: the same window size draws the same picture.
`BackdropIntensity.bold` is for the welcome page and the sign-in screen,
`BackdropIntensity.subtle` (the default) for every other screen. Scaffolds
stay opaque, so two pages never show through each other during a transition.

- **The motif is teal and slate only, never rose** (Invitee colour, below).
  Its colours are `motifA`, `motifB` and `motifC` in `tokens.dart`; change
  them there.
- **Text on the motif keeps 4.5:1.** Headings, body text and metadata drawn
  straight on the page sit on the motif. `contrast_test.dart` checks
  `bodyText`, `onSurface` and `onSurfaceVariant` on each motif colour and on
  every blend the backdrop paints; a new motif colour must pass it. Text that
  needs more calm goes on a `Card`, whose surface stays opaque.

## Invitee colour

Rose has one meaning. The rule, from the plan's Conventions:

> **Only invitee activity is rose.** `ShushGiftColors.inviteeActivity` and its
> container colours are used only for invitee activity: reservations,
> purchases, pledges, comments and their counts. Nothing else is rose, so that
> a rose element on a recipient's screen would be a visible bug.

Rose is not a Material role on purpose (plan D3): Material widgets paint
`secondary` and `tertiary` on their own, so both are slate. Use
`StatusChip(variant: StatusChipVariant.inviteeActivity)` or
`context.shushGiftColors` for invitee activity, and nothing else rose: not for
errors (those are `error` red), highlights or decoration.

The colour does not enforce the surprise rule; the server does. It only makes
a breach visible.

## Localisation

Every string a user sees comes from the translation files, in English and
French, in sentence case and without emoji. Proper names and user data are
the only exceptions. The files are `client/lib/l10n/app_en.arb` (the
template) and `client/lib/l10n/app_fr.arb`.

To add a string:

1. Add the key to `app_en.arb`, with an `@key` entry holding a `description`
   (where the string appears) and, for each placeholder, its `type` and an
   `example`:

   ```json
   "serverHttpError": "Server answered HTTP {status}",
   "@serverHttpError": {
     "description": "The server's version could not be read: the server answered with an HTTP error status.",
     "placeholders": {
       "status": {"type": "int", "example": "503"}
     }
   }
   ```

2. Add the same key, with the same placeholders, to `app_fr.arb`. The French
   file needs no `@key` entries: the template's apply.
3. Run `flutter pub get` in `client/`. It regenerates `AppLocalizations` in
   `client/lib/l10n/*.dart`, which is not committed (every build regenerates
   it).
4. Read it in the widget:

   ```dart
   final l10n = AppLocalizations.of(context);
   Text(l10n.serverHttpError(503));
   ```

`client/test/l10n/arb_parity_test.dart` fails when a key or a placeholder is
in one file and not the other. The app takes the device's language when it is
English or French, and English otherwise.

## Goldens

Every custom widget has golden tests, images compared pixel by pixel, in light
and dark (`client/test/design/widgets/widgets_golden_test.dart`). The backdrop's
are at both intensities, at 390x844 and 1440x900
(`client/test/design/widgets/backdrop_golden_test.dart`). The skeleton
screen's are also in English and French
(`client/test/version_screen_golden_test.dart`). They render on Linux only; how to regenerate and check them is in
[DEVELOPMENT](DEVELOPMENT.md#golden-tests). A golden changes only in a commit
that says why its pixels changed.
