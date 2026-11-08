/// Lagoon design tokens: the only place colours, spacing, radii and type sizes
/// are written (DESIGN_SYSTEM_PLAN D1).
///
/// Screens read these through [Theme.of] or `context.wishlistColors`, never
/// as literals.
library;

import 'dart:ui' show Color;

/// Light palette (D2, D3).
abstract final class LightColors {
  /// Teal accent: filled buttons, links, focus.
  static const primary = Color(0xFF0F766E);
  static const onPrimary = Color(0xFFFFFFFF);
  static const primaryContainer = Color(0xFFCCFBF1);
  static const onPrimaryContainer = Color(0xFF134E4A);

  /// Cards, sheets and the app bar.
  static const surface = Color(0xFFFFFFFF);

  /// Headings.
  static const onSurface = Color(0xFF1E293B);

  /// Behind the surfaces: `scaffoldBackgroundColor`.
  static const pageBackground = Color(0xFFF1F5F9);

  /// Running text.
  static const bodyText = Color(0xFF334155);

  /// Hints and metadata. Slate-600, not slate-500: slate-500 on the page
  /// background is below 4.5:1.
  static const onSurfaceVariant = Color(0xFF475569);

  /// Borders and dividers.
  static const outline = Color(0xFFCBD5E1);

  /// Subtle dividers.
  static const outlineVariant = Color(0xFFE2E8F0);

  /// Slate. Tertiary repeats it so no Material widget paints a colour that
  /// could be mistaken for invitee activity.
  static const secondary = Color(0xFF334155);
  static const onSecondary = Color(0xFFFFFFFF);

  /// Navigation indicator, selected chips.
  static const secondaryContainer = Color(0xFFE2E8F0);
  static const onSecondaryContainer = Color(0xFF1E293B);

  static const surfaceContainerLowest = Color(0xFFFFFFFF);
  static const surfaceContainerLow = Color(0xFFF8FAFC);
  static const surfaceContainer = Color(0xFFF1F5F9);
  static const surfaceContainerHigh = Color(0xFFE2E8F0);
  static const surfaceContainerHighest = Color(0xFFE2E8F0);

  /// Snack bars.
  static const inverseSurface = Color(0xFF1E293B);
  static const onInverseSurface = Color(0xFFF1F5F9);
  static const inversePrimary = Color(0xFF5EEAD4);

  static const error = Color(0xFFB91C1C);
  static const onError = Color(0xFFFFFFFF);
  static const errorContainer = Color(0xFFFEE2E2);
  static const onErrorContainer = Color(0xFF7F1D1D);

  /// Rose, for invitee activity only: reservations, purchases, pledges,
  /// comments and their counts. Nothing else is rose (D3).
  static const inviteeActivity = Color(0xFFE11D48);
  static const inviteeActivityContainer = Color(0xFFFFE4E6);
  static const onInviteeActivityContainer = Color(0xFF9F1239);
}

/// Dark palette (D2, D3). Same roles as [LightColors].
abstract final class DarkColors {
  static const primary = Color(0xFF2DD4BF);
  static const onPrimary = Color(0xFF042F2E);
  static const primaryContainer = Color(0xFF134E4A);
  static const onPrimaryContainer = Color(0xFFCCFBF1);

  static const surface = Color(0xFF1E293B);
  static const onSurface = Color(0xFFF1F5F9);
  static const pageBackground = Color(0xFF0F172A);
  static const bodyText = Color(0xFFCBD5E1);
  static const onSurfaceVariant = Color(0xFF94A3B8);
  static const outline = Color(0xFF334155);
  static const outlineVariant = Color(0xFF273449);

  static const secondary = Color(0xFFCBD5E1);
  static const onSecondary = Color(0xFF0F172A);
  static const secondaryContainer = Color(0xFF334155);
  static const onSecondaryContainer = Color(0xFFF1F5F9);

  static const surfaceContainerLowest = Color(0xFF0F172A);
  static const surfaceContainerLow = Color(0xFF1E293B);
  static const surfaceContainer = Color(0xFF1E293B);
  static const surfaceContainerHigh = Color(0xFF273449);
  static const surfaceContainerHighest = Color(0xFF334155);

  static const inverseSurface = Color(0xFFF1F5F9);
  static const onInverseSurface = Color(0xFF1E293B);
  static const inversePrimary = Color(0xFF0F766E);

  static const error = Color(0xFFF87171);
  static const onError = Color(0xFF450A0A);
  static const errorContainer = Color(0xFF7F1D1D);
  static const onErrorContainer = Color(0xFFFEE2E2);

  static const inviteeActivity = Color(0xFFFB7185);
  static const inviteeActivityContainer = Color(0xFF4C0519);
  static const onInviteeActivityContainer = Color(0xFFFFE4E6);
}

/// The 8-point spacing grid, with 4, 12 and 20 for tight spots. Each name is
/// its value, so a layout reads as the grid it uses.
abstract final class Spacing {
  static const double s4 = 4;
  static const double s8 = 8;
  static const double s12 = 12;
  static const double s16 = 16;
  static const double s20 = 20;
  static const double s24 = 24;
  static const double s32 = 32;
  static const double s40 = 40;
  static const double s48 = 48;
  static const double s64 = 64;
}

/// Corner radii.
abstract final class Radii {
  /// Small elements: tags, image thumbnails.
  static const double sm = 6;

  /// Buttons and text fields.
  static const double md = 8;

  /// Cards.
  static const double lg = 12;

  /// Dialogs and sheets.
  static const double xl = 16;

  /// Pills: status chips.
  static const double pill = 999;
}

/// Font families bundled in `assets/fonts/` (D4).
abstract final class FontFamilies {
  /// Display, headline and title styles.
  static const display = 'Space Grotesk';

  /// Body and label styles.
  static const text = 'Inter';
}

/// Type sizes of D5, in logical pixels.
abstract final class TypeSizes {
  static const double headlineMedium = 22;

  /// App bar title.
  static const double titleLarge = 19;

  /// Card titles.
  static const double titleMedium = 16;
  static const double bodyLarge = 15;
  static const double bodyMedium = 14;

  /// Metadata.
  static const double bodySmall = 13;

  /// Buttons.
  static const double labelLarge = 15;

  /// Chips.
  static const double labelMedium = 12;

  /// Eyebrows.
  static const double labelSmall = 12;
}
