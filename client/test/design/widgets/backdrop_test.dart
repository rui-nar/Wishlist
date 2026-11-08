import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/theme.dart';
import 'package:wishlist/src/design/widgets/backdrop.dart';
import 'package:wishlist/src/design/wishlist_colors.dart';

void main() {
  Future<void> pump(
    WidgetTester tester,
    ThemeData theme, {
    BackdropIntensity intensity = BackdropIntensity.subtle,
  }) {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    return tester.pumpWidget(
      MaterialApp(
        theme: theme,
        home: Scaffold(
          body: Backdrop(intensity: intensity, child: const Text('Content')),
        ),
      ),
    );
  }

  BackdropPainter painter(WidgetTester tester) {
    final paint = tester.widget<CustomPaint>(
      find.descendant(
        of: find.byType(Backdrop),
        matching: find.byWidgetPredicate(
          (w) => w is CustomPaint && w.painter is BackdropPainter,
        ),
      ),
    );
    return paint.painter! as BackdropPainter;
  }

  final themes = {
    'light': (buildLightTheme(), WishlistColors.light),
    'dark': (buildDarkTheme(), WishlistColors.dark),
  };
  final rose = [
    for (final c in [WishlistColors.light, WishlistColors.dark]) ...[
      c.inviteeActivity,
      c.inviteeActivityContainer,
      c.onInviteeActivityContainer,
    ],
  ];

  for (final MapEntry(key: name, value: (theme, colors)) in themes.entries) {
    group('$name theme', () {
      testWidgets('paints the page background and the motif colours',
          (tester) async {
        await pump(tester, theme);
        final p = painter(tester);
        expect(p.background, colors.pageBackground);
        expect(p.motifA, colors.motifA);
        expect(p.motifB, colors.motifB);
        expect(p.motifC, colors.motifC);
        expect(p.intensity, BackdropIntensity.subtle);
      });

      testWidgets('paints no rose: teal and slate only (D4)', (tester) async {
        await pump(tester, theme, intensity: BackdropIntensity.bold);
        for (final color in painter(tester).colors) {
          expect(rose, isNot(contains(color)), reason: '$color');
          // Teal is about 170 degrees, slate about 215; rose is about 345.
          expect(
            HSVColor.fromColor(color).hue,
            inInclusiveRange(150, 240),
            reason: '$color',
          );
        }
      });
    });
  }

  testWidgets('fills its constraints and shows its child', (tester) async {
    await pump(tester, buildLightTheme(), intensity: BackdropIntensity.bold);
    expect(tester.getSize(find.byType(Backdrop)), const Size(1440, 900));
    expect(find.text('Content'), findsOneWidget);
    expect(painter(tester).intensity, BackdropIntensity.bold);
  });

  test('repaints only when a colour or the intensity changes', () {
    const colors = WishlistColors.light;
    BackdropPainter make({
      Color? motifA,
      BackdropIntensity intensity = BackdropIntensity.subtle,
    }) =>
        BackdropPainter(
          background: colors.pageBackground,
          motifA: motifA ?? colors.motifA,
          motifB: colors.motifB,
          motifC: colors.motifC,
          intensity: intensity,
        );

    expect(make().shouldRepaint(make()), isFalse);
    expect(
      make().shouldRepaint(make(motifA: WishlistColors.dark.motifA)),
      isTrue,
    );
    expect(
      make().shouldRepaint(make(intensity: BackdropIntensity.bold)),
      isTrue,
    );
  });
}
