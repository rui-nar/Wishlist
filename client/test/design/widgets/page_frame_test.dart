import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/theme.dart';
import 'package:wishlist/src/design/tokens.dart';
import 'package:wishlist/src/design/widgets/backdrop.dart';
import 'package:wishlist/src/design/widgets/page_frame.dart';

void main() {
  const content = Key('content');

  Future<void> pump(WidgetTester tester, double width, Widget body) {
    tester.view.physicalSize = Size(width, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    return tester.pumpWidget(
      MaterialApp(theme: buildLightTheme(), home: Scaffold(body: body)),
    );
  }

  group('PageFrame.centered', () {
    Widget frame({double maxWidth = ContentWidths.reading}) =>
        PageFrame.centered(
          maxWidth: maxWidth,
          child: const SizedBox(key: content, height: 100),
        );

    testWidgets('caps and centres the child on a 1440 px window',
        (tester) async {
      await pump(tester, 1440, frame());
      final box = tester.getRect(find.byKey(content));
      expect(box.width, ContentWidths.reading);
      expect(box.left, (1440 - ContentWidths.reading) / 2);
      expect(box.top, Spacing.s24);
    });

    testWidgets('fills a 390 px window, padded 16', (tester) async {
      await pump(tester, 390, frame());
      final box = tester.getRect(find.byKey(content));
      expect(box.left, Spacing.s16);
      expect(box.width, 390 - 2 * Spacing.s16);
      expect(box.top, Spacing.s16);
    });

    testWidgets('pads 24 from the medium class', (tester) async {
      await pump(tester, Breakpoints.medium, frame());
      final box = tester.getRect(find.byKey(content));
      expect(box.left, Spacing.s24);
      expect(box.width, Breakpoints.medium - 2 * Spacing.s24);
    });

    testWidgets('caps at the width it is given', (tester) async {
      await pump(tester, 1440, frame(maxWidth: ContentWidths.form));
      expect(tester.getSize(find.byKey(content)).width, ContentWidths.form);
    });

    testWidgets('a Center child centres vertically', (tester) async {
      await pump(
        tester,
        1440,
        const PageFrame.centered(
          child: Center(child: SizedBox(key: content, width: 200, height: 100)),
        ),
      );
      final body = tester.getRect(find.byType(PageFrame));
      expect(tester.getCenter(find.byKey(content)), body.center);
    });

    testWidgets('a padding replaces the class padding', (tester) async {
      await pump(
        tester,
        390,
        const PageFrame.centered(
          padding: EdgeInsets.zero,
          child: SizedBox(key: content, height: 100),
        ),
      );
      expect(tester.getRect(find.byKey(content)).left, 0);
      expect(tester.getSize(find.byKey(content)).width, 390);
    });

    testWidgets('draws the backdrop at the given intensity', (tester) async {
      await pump(
        tester,
        390,
        const PageFrame.centered(
          intensity: BackdropIntensity.bold,
          child: SizedBox(),
        ),
      );
      final backdrop = tester.widget<Backdrop>(find.byType(Backdrop));
      expect(backdrop.intensity, BackdropIntensity.bold);
      expect(tester.getSize(find.byType(Backdrop)).width, 390);
    });
  });

  group('PageFrame with a scrolling child', () {
    Widget list() => PageFrame(
          child: Builder(
            builder: (context) => ListView(
              padding: PageFrame.paddingOf(context, ContentWidths.reading),
              children: [
                for (var i = 0; i < 60; i++)
                  SizedBox(key: ValueKey(i), height: 50, child: Text('Item $i')),
              ],
            ),
          ),
        );

    testWidgets('paddingOf gives the class padding on a 390 px window',
        (tester) async {
      late EdgeInsets padding;
      await pump(
        tester,
        390,
        Builder(builder: (context) {
          padding = PageFrame.paddingOf(context, ContentWidths.reading);
          return const SizedBox();
        }),
      );
      expect(padding, const EdgeInsets.all(Spacing.s16));
    });

    testWidgets('paddingOf centres a capped column from the medium class',
        (tester) async {
      late EdgeInsets medium;
      await pump(
        tester,
        700,
        Builder(builder: (context) {
          medium = PageFrame.paddingOf(context, ContentWidths.reading);
          return const SizedBox();
        }),
      );
      expect(medium, const EdgeInsets.all(Spacing.s24));

      late EdgeInsets wide;
      await pump(
        tester,
        1440,
        Builder(builder: (context) {
          wide = PageFrame.paddingOf(context, ContentWidths.reading);
          return const SizedBox();
        }),
      );
      expect(
        wide,
        const EdgeInsets.symmetric(
          horizontal: (1440 - ContentWidths.reading) / 2,
          vertical: Spacing.s24,
        ),
      );
    });

    testWidgets('the list spans the window and its items are capped',
        (tester) async {
      await pump(tester, 1440, list());
      expect(tester.getSize(find.byType(ListView)).width, 1440);
      final item = tester.getRect(find.byKey(const ValueKey(0)));
      expect(item.width, ContentWidths.reading);
      expect(item.left, (1440 - ContentWidths.reading) / 2);
    });

    testWidgets('the list scrolls by dragging', (tester) async {
      await pump(tester, 390, list());
      expect(find.text('Item 0'), findsOneWidget);
      await tester.drag(find.byType(ListView), const Offset(0, -600));
      await tester.pumpAndSettle();
      expect(find.text('Item 0'), findsNothing);
    });

    testWidgets('the wheel scrolls the list from the side margin',
        (tester) async {
      await pump(tester, 1440, list());
      // Outside the capped column, over the backdrop.
      final pointer = TestPointer(1, PointerDeviceKind.mouse);
      await tester.sendEventToBinding(pointer.hover(const Offset(50, 400)));
      await tester.sendEventToBinding(pointer.scroll(const Offset(0, 600)));
      await tester.pumpAndSettle();
      expect(find.text('Item 0'), findsNothing);
    });
  });
}
