@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';

import 'support/fakes.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  const compact = Size(390, 844);
  const expanded = Size(1440, 900);

  // The golden's name, the location the app opens at, whether a session is
  // stored, and the window's size. The sign-in screen shows the Android
  // button: tests do not run as the web, where Google's script draws its own.
  const screens = {
    'sign_in_screen': ('/sign-in', false, compact),
    'account_screen': ('/account', true, compact),
    'welcome_screen_390x844': ('/welcome', false, compact),
    'welcome_screen_1440x900': ('/welcome', false, expanded),
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: (location, signedIn, size))
        in screens.entries) {
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
          tester.platformDispatcher.defaultRouteNameTestValue = location;
          addTearDown(tester.platformDispatcher.clearAllTestValues);
          // No DEBUG ribbon: the goldens show the app as users see it.
          WidgetsApp.debugAllowBannerOverride = false;
          addTearDown(() => WidgetsApp.debugAllowBannerOverride = true);
          installFakeGoogleSignIn();

          final server = FakeServer();
          final app = buildApp(
            server,
            store: MemoryTokenStore(signedIn ? server.addSession() : null),
          );
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
