@Tags(['golden'])
library;

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/l10n/app_localizations.dart';
import 'package:shushgift/src/design/theme.dart';
import 'package:shushgift/src/design/widgets/gift_card.dart';
import 'package:shushgift/src/design/widgets/image_viewer.dart';
import 'package:shushgift/src/design/widgets/privacy_banner.dart';
import 'package:shushgift/src/design/widgets/status_chip.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

const _width = 390.0;
const _longTitle =
    'Wireless noise-cancelling over-ear headphones with a '
    'charging case and a very long product name';

void main() {
  final themes = {'light': buildLightTheme(), 'dark': buildDarkTheme()};

  /// A solid-colour picture standing in for a product photo.
  Future<ImageProvider> photo(WidgetTester tester) async {
    final bytes = await tester.runAsync(() async {
      final recorder = ui.PictureRecorder();
      Canvas(recorder).drawRect(
        const Rect.fromLTWH(0, 0, 64, 64),
        Paint()..color = const Color(0xFF94A3B8),
      );
      final image = await recorder.endRecording().toImage(64, 64);
      return (await image.toByteData(format: ui.ImageByteFormat.png))!;
    });
    return MemoryImage(bytes!.buffer.asUint8List());
  }

  Future<void> pumpGolden(
    WidgetTester tester,
    ThemeData theme,
    double height,
    Widget child,
  ) async {
    tester.view.physicalSize = Size(_width, height);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: theme,
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: Align(alignment: Alignment.topLeft, child: child),
          ),
        ),
      ),
    );
    // Decoding happens off the test's fake clock: wait for it for real.
    await tester.runAsync(() async {
      for (final element in find.byType(Image).evaluate()) {
        await precacheImage((element.widget as Image).image, element);
      }
    });
    await tester.pumpAndSettle();
  }

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: mode, value: theme) in themes.entries) {
      testWidgets('status chips, $mode', (tester) async {
        await pumpGolden(
          tester,
          theme,
          140,
          const Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              StatusChip(
                label: 'Reserved',
                variant: StatusChipVariant.inviteeActivity,
                icon: Icons.lock_outline,
              ),
              StatusChip(label: 'Reserved'),
              StatusChip(
                label: 'Hidden from you',
                variant: StatusChipVariant.hidden,
                icon: Icons.visibility_off_outlined,
              ),
              StatusChip(label: 'Hidden', variant: StatusChipVariant.hidden),
              StatusChip(label: 'Draft'),
              StatusChip(label: 'Draft', icon: Icons.edit_outlined),
            ],
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/status_chips_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('privacy banner, $mode', (tester) async {
        await pumpGolden(
          tester,
          theme,
          120,
          const SizedBox(
            width: _width - 32,
            child: PrivacyBanner(
              message:
                  'The person this list is for cannot see who reserved '
                  'what.',
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/privacy_banner_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('gift card with no chips, $mode', (tester) async {
        final image = await photo(tester);
        await pumpGolden(
          tester,
          theme,
          160,
          SizedBox(
            width: _width - 32,
            child: GiftCard(
              title: 'Headphones',
              metadata: '129 EUR - example.com',
              image: image,
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/gift_card_plain_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('gift card with chips, $mode', (tester) async {
        final image = await photo(tester);
        await pumpGolden(
          tester,
          theme,
          160,
          SizedBox(
            width: _width - 32,
            child: GiftCard(
              title: 'Headphones',
              metadata: '129 EUR - example.com',
              image: image,
              chips: const [
                StatusChip(
                  label: 'Reserved',
                  variant: StatusChipVariant.inviteeActivity,
                  icon: Icons.lock_outline,
                ),
                StatusChip(label: 'Draft'),
              ],
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/gift_card_chips_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('gift card with an action, $mode', (tester) async {
        final image = await photo(tester);
        await pumpGolden(
          tester,
          theme,
          160,
          SizedBox(
            width: _width - 32,
            child: GiftCard(
              title: 'Headphones',
              metadata: '129 EUR - example.com',
              image: image,
              action: IconButton(
                tooltip: 'More',
                onPressed: () {},
                icon: const Icon(Icons.more_vert),
              ),
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/gift_card_action_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('gift card with a long title, $mode', (tester) async {
        final image = await photo(tester);
        await pumpGolden(
          tester,
          theme,
          160,
          SizedBox(
            width: _width - 32,
            child: GiftCard(
              title: _longTitle,
              metadata: '129 EUR - example.com',
              image: image,
              chips: const [StatusChip(label: 'Draft')],
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/gift_card_long_title_$mode.png'),
        );
      }, tags: ['golden']);

      testWidgets('gift card with no image, $mode', (tester) async {
        await pumpGolden(
          tester,
          theme,
          160,
          const SizedBox(
            width: _width - 32,
            child: GiftCard(
              title: 'Headphones',
              metadata: '129 EUR - example.com',
              chips: [StatusChip(label: 'Draft')],
            ),
          ),
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/gift_card_no_image_$mode.png'),
        );
      }, tags: ['golden']);
      testWidgets('image viewer, $mode', (tester) async {
        final image = await photo(tester);
        tester.view.physicalSize = const Size(_width, 300);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await tester.pumpWidget(
          MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: theme,
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: ImageViewer(image: image),
          ),
        );
        await tester.runAsync(() async {
          for (final element in find.byType(Image).evaluate()) {
            await precacheImage((element.widget as Image).image, element);
          }
        });
        await tester.pumpAndSettle();
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile('goldens/image_viewer_$mode.png'),
        );
      }, tags: ['golden']);
    }
  });
}
