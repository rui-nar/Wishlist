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

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: mode, value: brightness) in brightnesses.entries) {
      for (final (name, unsubscribed) in [
        ('before', false),
        ('after', true),
      ]) {
        testWidgets('unsubscribe page $name, $mode', (tester) async {
          tester.view.physicalSize = const Size(390, 844);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.reset);
          tester.platformDispatcher.localesTestValue = const [
            Locale('en', 'GB'),
          ];
          tester.platformDispatcher.platformBrightnessTestValue = brightness;
          tester.platformDispatcher.defaultRouteNameTestValue =
              '/unsubscribe#$kUnsubscribeToken';
          addTearDown(tester.platformDispatcher.clearAllTestValues);
          // No DEBUG ribbon: the goldens show the app as users see it.
          WidgetsApp.debugAllowBannerOverride = false;
          addTearDown(() => WidgetsApp.debugAllowBannerOverride = true);
          installFakeGoogleSignIn();

          final app = buildApp(FakeServer(), store: MemoryTokenStore());
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();
          if (unsubscribed) {
            await tester.tap(find.text('Stop email notifications'));
            await tester.pumpAndSettle();
          }

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/unsubscribe_${name}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
