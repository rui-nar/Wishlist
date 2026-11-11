@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';

import '../support/fakes.dart';
import 'support/fake_admin.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  // The golden's name, the location the app opens at, and what to do there.
  final screens = <String, (String, Future<void> Function(WidgetTester)?)>{
    'admin_users': ('/admin', null),
    'admin_user': ('/admin/users/$kBobId', null),
    'admin_delete_dialog': (
      '/admin/users/$kBobId',
      (tester) async {
        await tester.tap(find.text('Delete this account'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField), 'bob@example.com');
        await tester.pumpAndSettle();
      },
    ),
    'not_found': ('/nowhere', null),
  };
  const wide = {'admin_users', 'admin_user'};
  final windows = [
    for (final screen in screens.keys) ...[
      (screen: screen, size: const Size(390, 844), suffix: ''),
      if (wide.contains(screen))
        (screen: screen, size: const Size(1440, 900), suffix: '_1440x900'),
    ],
  ];

  group('goldens', skip: _skip, () {
    for (final (:screen, :size, :suffix) in windows) {
      for (final MapEntry(key: mode, value: brightness)
          in brightnesses.entries) {
        testWidgets('$screen$suffix, $mode', (tester) async {
          final (location, after) = screens[screen]!;
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
          // Bob's Stripe subscription with a grant beside it.
          FakeAdmin(server).grants[kBobId] = '2027-06-01T12:00:00Z';
          final app = buildApp(
            server,
            store: MemoryTokenStore(server.addSession()),
          );
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();
          await after?.call(tester);

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/$screen${suffix}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
