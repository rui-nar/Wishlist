/// Lagoon light and dark themes (DESIGN_SYSTEM_PLAN D2, D5, D6).
///
/// Both are built by [_buildTheme] from a hand-written [ColorScheme] and the
/// [ShushGiftColors] extension, so the component themes are written once.
/// `main.dart` passes both to `MaterialApp` with [ThemeMode.system] (D9).
library;

import 'package:flutter/material.dart';

import 'tokens.dart';
import 'shushgift_colors.dart';

ThemeData buildLightTheme() => _buildTheme(_lightScheme, ShushGiftColors.light);

ThemeData buildDarkTheme() => _buildTheme(_darkScheme, ShushGiftColors.dark);

// Written out field by field, not seeded: `ColorScheme.fromSeed` would shift
// the chosen teal and slates to its own tonal palette (D2). Roles left out
// (the `fixed` ones, surfaceDim/Bright, shadow, scrim, surfaceTint) derive
// from the ones set here.
const _lightScheme = ColorScheme(
  brightness: Brightness.light,
  primary: LightColors.primary,
  onPrimary: LightColors.onPrimary,
  primaryContainer: LightColors.primaryContainer,
  onPrimaryContainer: LightColors.onPrimaryContainer,
  secondary: LightColors.secondary,
  onSecondary: LightColors.onSecondary,
  secondaryContainer: LightColors.secondaryContainer,
  onSecondaryContainer: LightColors.onSecondaryContainer,
  tertiary: LightColors.secondary,
  onTertiary: LightColors.onSecondary,
  tertiaryContainer: LightColors.secondaryContainer,
  onTertiaryContainer: LightColors.onSecondaryContainer,
  error: LightColors.error,
  onError: LightColors.onError,
  errorContainer: LightColors.errorContainer,
  onErrorContainer: LightColors.onErrorContainer,
  surface: LightColors.surface,
  onSurface: LightColors.onSurface,
  onSurfaceVariant: LightColors.onSurfaceVariant,
  surfaceContainerLowest: LightColors.surfaceContainerLowest,
  surfaceContainerLow: LightColors.surfaceContainerLow,
  surfaceContainer: LightColors.surfaceContainer,
  surfaceContainerHigh: LightColors.surfaceContainerHigh,
  surfaceContainerHighest: LightColors.surfaceContainerHighest,
  outline: LightColors.outline,
  outlineVariant: LightColors.outlineVariant,
  inverseSurface: LightColors.inverseSurface,
  onInverseSurface: LightColors.onInverseSurface,
  inversePrimary: LightColors.inversePrimary,
);

const _darkScheme = ColorScheme(
  brightness: Brightness.dark,
  primary: DarkColors.primary,
  onPrimary: DarkColors.onPrimary,
  primaryContainer: DarkColors.primaryContainer,
  onPrimaryContainer: DarkColors.onPrimaryContainer,
  secondary: DarkColors.secondary,
  onSecondary: DarkColors.onSecondary,
  secondaryContainer: DarkColors.secondaryContainer,
  onSecondaryContainer: DarkColors.onSecondaryContainer,
  tertiary: DarkColors.secondary,
  onTertiary: DarkColors.onSecondary,
  tertiaryContainer: DarkColors.secondaryContainer,
  onTertiaryContainer: DarkColors.onSecondaryContainer,
  error: DarkColors.error,
  onError: DarkColors.onError,
  errorContainer: DarkColors.errorContainer,
  onErrorContainer: DarkColors.onErrorContainer,
  surface: DarkColors.surface,
  onSurface: DarkColors.onSurface,
  onSurfaceVariant: DarkColors.onSurfaceVariant,
  surfaceContainerLowest: DarkColors.surfaceContainerLowest,
  surfaceContainerLow: DarkColors.surfaceContainerLow,
  surfaceContainer: DarkColors.surfaceContainer,
  surfaceContainerHigh: DarkColors.surfaceContainerHigh,
  surfaceContainerHighest: DarkColors.surfaceContainerHighest,
  outline: DarkColors.outline,
  outlineVariant: DarkColors.outlineVariant,
  inverseSurface: DarkColors.inverseSurface,
  onInverseSurface: DarkColors.onInverseSurface,
  inversePrimary: DarkColors.inversePrimary,
);

/// Buttons are at least this tall, the minimum tap target.
const double _minTapHeight = 44;

/// Material's default minimum button width.
const double _minButtonWidth = 64;

ThemeData _buildTheme(ColorScheme scheme, ShushGiftColors colors) {
  final border = BorderSide(color: scheme.outline);
  const buttonShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
  );
  const buttonMinimumSize = Size(_minButtonWidth, _minTapHeight);

  OutlineInputBorder inputBorder(Color color, {double width = 1}) =>
      OutlineInputBorder(
        borderRadius: const BorderRadius.all(Radius.circular(Radii.md)),
        borderSide: BorderSide(color: color, width: width),
      );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    // Inter everywhere by default; [_textTheme] puts the display, headline
    // and title styles in Space Grotesk on top.
    fontFamily: FontFamilies.text,
    textTheme: _textTheme(scheme, colors),
    scaffoldBackgroundColor: colors.pageBackground,
    extensions: [colors],
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: buttonMinimumSize,
        shape: buttonShape,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: buttonMinimumSize,
        shape: buttonShape,
        side: border,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: buttonMinimumSize,
        shape: buttonShape,
      ),
    ),
    // Flat cards: a 1 px border, no shadow, no tint. No margin: screens space
    // cards with the spacing tokens.
    cardTheme: CardThemeData(
      color: scheme.surface,
      elevation: 0,
      shadowColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.all(Radius.circular(Radii.lg)),
        side: border,
      ),
    ),
    appBarTheme: AppBarThemeData(
      backgroundColor: scheme.surface,
      foregroundColor: scheme.onSurface,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      shape: Border(bottom: border),
    ),
    inputDecorationTheme: InputDecorationThemeData(
      filled: true,
      fillColor: scheme.surface,
      border: inputBorder(scheme.outline),
      enabledBorder: inputBorder(scheme.outline),
      focusedBorder: inputBorder(scheme.primary, width: 2),
      errorBorder: inputBorder(scheme.error),
      focusedErrorBorder: inputBorder(scheme.error, width: 2),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: scheme.surface,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      indicatorColor: scheme.secondaryContainer,
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: scheme.inverseSurface,
      actionTextColor: scheme.inversePrimary,
      behavior: SnackBarBehavior.floating,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: scheme.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.xl)),
      ),
    ),
  );
}

/// The type scale of D5. Space Grotesk for display, headline and title
/// styles, Inter for body and label styles. Styles D5 does not list keep
/// Material's sizes and weights, which ThemeData merges underneath.
TextTheme _textTheme(ColorScheme scheme, ShushGiftColors colors) {
  const display = TextStyle(fontFamily: FontFamilies.display);
  const text = TextStyle(fontFamily: FontFamilies.text);

  return TextTheme(
    displayLarge: display,
    displayMedium: display,
    displaySmall: display,
    headlineLarge: display,
    headlineMedium: display.copyWith(
      fontSize: TypeSizes.headlineMedium,
      fontWeight: FontWeight.w700,
    ),
    headlineSmall: display,
    titleLarge: display.copyWith(
      fontSize: TypeSizes.titleLarge,
      fontWeight: FontWeight.w700,
    ),
    titleMedium: display.copyWith(
      fontSize: TypeSizes.titleMedium,
      fontWeight: FontWeight.w500,
    ),
    titleSmall: display,
    bodyLarge: text.copyWith(
      fontSize: TypeSizes.bodyLarge,
      fontWeight: FontWeight.w400,
      color: colors.bodyText,
    ),
    bodyMedium: text.copyWith(
      fontSize: TypeSizes.bodyMedium,
      fontWeight: FontWeight.w400,
      color: colors.bodyText,
    ),
    bodySmall: text.copyWith(
      fontSize: TypeSizes.bodySmall,
      fontWeight: FontWeight.w400,
      color: scheme.onSurfaceVariant,
    ),
    labelLarge: text.copyWith(
      fontSize: TypeSizes.labelLarge,
      fontWeight: FontWeight.w600,
    ),
    labelMedium: text.copyWith(
      fontSize: TypeSizes.labelMedium,
      fontWeight: FontWeight.w600,
    ),
    labelSmall: text.copyWith(
      fontSize: TypeSizes.labelSmall,
      fontWeight: FontWeight.w500,
    ),
  );
}
