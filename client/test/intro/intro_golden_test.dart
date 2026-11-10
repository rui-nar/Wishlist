@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';

import '../support/fakes.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  const compact = Size(390, 844);
  const expanded = Size(1440, 900);

  // The golden's name, the page shown (from 0) and the window's size.
  const screens = {
    'intro_page1_390x844': (0, compact),
    'intro_page2_390x844': (1, compact),
    'intro_page3_390x844': (2, compact),
    'intro_page1_1440x900': (0, expanded),
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: (page, size)) in screens.entries) {
      for (final MapEntry(key: mode, value: brightness)
          in brightnesses.entries) {
        testWidgets('$screen, $mode', (tester) async {
          tester.view.physicalSize = size;
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.reset);
          tester.platformDispatcher.localesTestValue = const [
            Locale('en', 'GB'),
          ];
          tester.platformDispatcher.platformBrightnessTestValue = brightness;
          tester.platformDispatcher.defaultRouteNameTestValue = '/intro';
          addTearDown(tester.platformDispatcher.clearAllTestValues);
          // No DEBUG ribbon: the goldens show the app as users see it.
          WidgetsApp.debugAllowBannerOverride = false;
          addTearDown(() => WidgetsApp.debugAllowBannerOverride = true);
          installFakeGoogleSignIn();

          final server = FakeServer();
          final app = buildApp(
            server,
            store: MemoryTokenStore(server.addSession()),
          );
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();
          for (var i = 0; i < page; i++) {
            await tester.tap(find.text('Next'));
            await tester.pumpAndSettle();
          }

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
