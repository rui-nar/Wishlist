import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/theme.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/privacy_banner.dart';
import 'package:wishlist/src/design/widgets/status_chip.dart';
import 'package:wishlist/src/design/wishlist_colors.dart';

void main() {
  Future<void> pump(WidgetTester tester, Widget child, {ThemeData? theme}) {
    return tester.pumpWidget(
      MaterialApp(
        theme: theme ?? buildLightTheme(),
        home: Scaffold(body: Center(child: child)),
      ),
    );
  }

  Color chipBackground(WidgetTester tester) {
    final box = tester.widget<DecoratedBox>(
      find.descendant(
        of: find.byType(StatusChip),
        matching: find.byType(DecoratedBox),
      ),
    );
    return (box.decoration as BoxDecoration).color!;
  }

  Color chipForeground(WidgetTester tester) =>
      tester.widget<Text>(find.text('Label')).style!.color!;

  group('StatusChip', () {
    for (final (name, theme, colors, scheme) in [
      ('light', buildLightTheme(), WishlistColors.light, buildLightTheme()),
      ('dark', buildDarkTheme(), WishlistColors.dark, buildDarkTheme()),
    ]) {
      testWidgets('each variant uses its colours in $name', (tester) async {
        final cs = scheme.colorScheme;
        final expected = {
          StatusChipVariant.inviteeActivity: (
            colors.inviteeActivityContainer,
            colors.onInviteeActivityContainer,
          ),
          StatusChipVariant.hidden: (
            cs.primaryContainer,
            cs.onPrimaryContainer,
          ),
          StatusChipVariant.neutral: (
            cs.secondaryContainer,
            cs.onSecondaryContainer,
          ),
        };
        for (final entry in expected.entries) {
          await pump(
            tester,
            StatusChip(label: 'Label', variant: entry.key),
            theme: theme,
          );
          expect(
            chipBackground(tester),
            entry.value.$1,
            reason: '${entry.key}',
          );
          expect(
            chipForeground(tester),
            entry.value.$2,
            reason: '${entry.key}',
          );
        }
      });
    }

    testWidgets('shows the leading icon when given', (tester) async {
      await pump(
        tester,
        const StatusChip(label: 'Label', icon: Icons.lock_outline),
      );
      expect(find.byIcon(Icons.lock_outline), findsOneWidget);
    });
  });

  group('PrivacyBanner', () {
    testWidgets('shows the message', (tester) async {
      await pump(tester, const PrivacyBanner(message: 'Hidden from you'));
      expect(find.text('Hidden from you'), findsOneWidget);
    });

    testWidgets('excludes its icon from semantics', (tester) async {
      await pump(tester, const PrivacyBanner(message: 'Hidden from you'));
      expect(
        find.ancestor(
          of: find.byIcon(Icons.visibility_off_outlined),
          matching: find.byType(ExcludeSemantics),
        ),
        findsOneWidget,
      );
      expect(
        tester
            .widget<ExcludeSemantics>(
              find.ancestor(
                of: find.byIcon(Icons.visibility_off_outlined),
                matching: find.byType(ExcludeSemantics),
              ),
            )
            .excluding,
        isTrue,
      );
    });
  });

  group('GiftCard', () {
    testWidgets('with no chips renders none', (tester) async {
      await pump(tester, const GiftCard(title: 'Headphones'));
      expect(find.byType(StatusChip), findsNothing);
      expect(find.byType(Wrap), findsNothing);
    });

    testWidgets('renders the chips it is given', (tester) async {
      await pump(
        tester,
        const GiftCard(
          title: 'Headphones',
          chips: [
            StatusChip(label: 'One'),
            StatusChip(label: 'Two'),
          ],
        ),
      );
      expect(find.byType(StatusChip), findsNWidgets(2));
    });

    testWidgets('shows a gift icon when there is no image', (tester) async {
      await pump(tester, const GiftCard(title: 'Headphones'));
      expect(find.byIcon(Icons.card_giftcard_outlined), findsOneWidget);
      expect(find.byType(Image), findsNothing);
    });

    testWidgets('onTap fires', (tester) async {
      var taps = 0;
      await pump(tester, GiftCard(title: 'Headphones', onTap: () => taps++));
      await tester.tap(find.text('Headphones'));
      expect(taps, 1);
    });

    testWidgets('the action keeps a hit area of at least 44 px', (
      tester,
    ) async {
      await pump(
        tester,
        const GiftCard(
          title: 'Headphones',
          action: SizedBox.square(dimension: 10),
        ),
      );
      final size = tester.getSize(
        find.byKey(const ValueKey('gift-card-action')),
      );
      expect(size.width, greaterThanOrEqualTo(44));
      expect(size.height, greaterThanOrEqualTo(44));
    });

    testWidgets('a long title wraps to two lines then ends with an ellipsis', (
      tester,
    ) async {
      await pump(tester, GiftCard(title: 'A very long title ' * 20));
      final title = tester.widget<Text>(find.textContaining('A very long'));
      expect(title.maxLines, 2);
      expect(title.overflow, TextOverflow.ellipsis);
    });
  });
}
