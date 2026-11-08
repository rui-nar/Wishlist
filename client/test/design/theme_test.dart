import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/theme.dart';
import 'package:wishlist/src/design/wishlist_colors.dart';

void main() {
  // The D2 table, role by role. Hex values are written out here rather than
  // read from tokens.dart so a token edit that drifts from the plan fails.
  Map<String, Color> roles(ColorScheme s) => {
        'primary': s.primary,
        'onPrimary': s.onPrimary,
        'primaryContainer': s.primaryContainer,
        'onPrimaryContainer': s.onPrimaryContainer,
        'surface': s.surface,
        'onSurface': s.onSurface,
        'onSurfaceVariant': s.onSurfaceVariant,
        'outline': s.outline,
        'outlineVariant': s.outlineVariant,
        'secondary': s.secondary,
        'onSecondary': s.onSecondary,
        'secondaryContainer': s.secondaryContainer,
        'onSecondaryContainer': s.onSecondaryContainer,
        'tertiary': s.tertiary,
        'onTertiary': s.onTertiary,
        'tertiaryContainer': s.tertiaryContainer,
        'onTertiaryContainer': s.onTertiaryContainer,
        'surfaceContainerLowest': s.surfaceContainerLowest,
        'surfaceContainerLow': s.surfaceContainerLow,
        'surfaceContainer': s.surfaceContainer,
        'surfaceContainerHigh': s.surfaceContainerHigh,
        'surfaceContainerHighest': s.surfaceContainerHighest,
        'inverseSurface': s.inverseSurface,
        'onInverseSurface': s.onInverseSurface,
        'inversePrimary': s.inversePrimary,
        'error': s.error,
        'onError': s.onError,
        'errorContainer': s.errorContainer,
        'onErrorContainer': s.onErrorContainer,
      };

  const light = <String, int>{
    'primary': 0xFF0F766E,
    'onPrimary': 0xFFFFFFFF,
    'primaryContainer': 0xFFCCFBF1,
    'onPrimaryContainer': 0xFF134E4A,
    'surface': 0xFFFFFFFF,
    'onSurface': 0xFF1E293B,
    'onSurfaceVariant': 0xFF475569,
    'outline': 0xFFCBD5E1,
    'outlineVariant': 0xFFE2E8F0,
    'secondary': 0xFF334155,
    'onSecondary': 0xFFFFFFFF,
    'secondaryContainer': 0xFFE2E8F0,
    'onSecondaryContainer': 0xFF1E293B,
    'tertiary': 0xFF334155,
    'onTertiary': 0xFFFFFFFF,
    'tertiaryContainer': 0xFFE2E8F0,
    'onTertiaryContainer': 0xFF1E293B,
    'surfaceContainerLowest': 0xFFFFFFFF,
    'surfaceContainerLow': 0xFFF8FAFC,
    'surfaceContainer': 0xFFF1F5F9,
    'surfaceContainerHigh': 0xFFE2E8F0,
    'surfaceContainerHighest': 0xFFE2E8F0,
    'inverseSurface': 0xFF1E293B,
    'onInverseSurface': 0xFFF1F5F9,
    'inversePrimary': 0xFF5EEAD4,
    'error': 0xFFB91C1C,
    'onError': 0xFFFFFFFF,
    'errorContainer': 0xFFFEE2E2,
    'onErrorContainer': 0xFF7F1D1D,
  };

  const dark = <String, int>{
    'primary': 0xFF2DD4BF,
    'onPrimary': 0xFF042F2E,
    'primaryContainer': 0xFF134E4A,
    'onPrimaryContainer': 0xFFCCFBF1,
    'surface': 0xFF1E293B,
    'onSurface': 0xFFF1F5F9,
    'onSurfaceVariant': 0xFF94A3B8,
    'outline': 0xFF334155,
    'outlineVariant': 0xFF273449,
    'secondary': 0xFFCBD5E1,
    'onSecondary': 0xFF0F172A,
    'secondaryContainer': 0xFF334155,
    'onSecondaryContainer': 0xFFF1F5F9,
    'tertiary': 0xFFCBD5E1,
    'onTertiary': 0xFF0F172A,
    'tertiaryContainer': 0xFF334155,
    'onTertiaryContainer': 0xFFF1F5F9,
    'surfaceContainerLowest': 0xFF0F172A,
    'surfaceContainerLow': 0xFF1E293B,
    'surfaceContainer': 0xFF1E293B,
    'surfaceContainerHigh': 0xFF273449,
    'surfaceContainerHighest': 0xFF334155,
    'inverseSurface': 0xFFF1F5F9,
    'onInverseSurface': 0xFF1E293B,
    'inversePrimary': 0xFF0F766E,
    'error': 0xFFF87171,
    'onError': 0xFF450A0A,
    'errorContainer': 0xFF7F1D1D,
    'onErrorContainer': 0xFFFEE2E2,
  };

  // Theme, D2 roles, brightness, page background, body text.
  final themes = {
    'light':
        (buildLightTheme(), light, Brightness.light, 0xFFF1F5F9, 0xFF334155),
    'dark': (buildDarkTheme(), dark, Brightness.dark, 0xFF0F172A, 0xFFCBD5E1),
  };

  for (final MapEntry(
        key: name,
        value: (theme, expected, brightness, page, body),
      ) in themes.entries) {
    group('$name theme', () {
      test('every ColorScheme role has its D2 value', () {
        expect(theme.useMaterial3, isTrue);
        expect(theme.colorScheme.brightness, brightness);
        final actual = roles(theme.colorScheme);
        expect(actual.keys, unorderedEquals(expected.keys));
        for (final role in expected.keys) {
          expect(actual[role], Color(expected[role]!), reason: role);
        }
      });

      test('the page background is the scaffold background', () {
        expect(theme.scaffoldBackgroundColor, Color(page));
      });

      test('carries the WishlistColors extension', () {
        final colors = theme.extension<WishlistColors>();
        expect(colors, isNotNull);
        expect(
          colors,
          brightness == Brightness.light
              ? WishlistColors.light
              : WishlistColors.dark,
        );
        expect(colors!.pageBackground, Color(page));
        expect(colors.bodyText, Color(body));
      });

      test('titles use Space Grotesk and body text uses Inter', () {
        expect(theme.textTheme.titleMedium!.fontFamily, 'Space Grotesk');
        expect(theme.textTheme.bodyMedium!.fontFamily, 'Inter');
      });

      testWidgets('a FilledButton is at least 44 px tall', (tester) async {
        await tester.pumpWidget(MaterialApp(
          theme: theme,
          home: Scaffold(
            body: Center(
              child: FilledButton(onPressed: () {}, child: const Text('Go')),
            ),
          ),
        ));
        expect(
          tester.getSize(find.byType(FilledButton)).height,
          greaterThanOrEqualTo(44),
        );
        expect(
          theme.filledButtonTheme.style!.minimumSize!.resolve({})!.height,
          44,
        );
      });
    });
  }

  test('invitee activity is rose in both themes (D3)', () {
    expect(WishlistColors.light.inviteeActivity, const Color(0xFFE11D48));
    expect(WishlistColors.light.inviteeActivityContainer,
        const Color(0xFFFFE4E6));
    expect(WishlistColors.light.onInviteeActivityContainer,
        const Color(0xFF9F1239));
    expect(WishlistColors.dark.inviteeActivity, const Color(0xFFFB7185));
    expect(WishlistColors.dark.inviteeActivityContainer,
        const Color(0xFF4C0519));
    expect(WishlistColors.dark.onInviteeActivityContainer,
        const Color(0xFFFFE4E6));
  });
}
