@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/main.dart';
import 'package:shushgift/src/admin/admin_format.dart';

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
        // Below the plan's blocks, past what the list builds at first.
        await tester.scrollUntilVisible(
          find.text('Delete this account'),
          200,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pumpAndSettle();
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

          // The panel's today, so Carol's grant stays expired.
          adminClock = () => DateTime(2026, 11, 11, 10);
          addTearDown(() => adminClock = DateTime.now);
          final server = FakeServer();
          // Bob's Stripe subscription, an Apple one in its grace period
          // (Apple IAP plan D9), a Google one on hold (Android release plan
          // D8) and a grant beside them; Carol's grant whose day has passed.
          final admin = FakeAdmin(server);
          admin.grants
            ..[kBobId] = '2027-06-01T12:00:00Z'
            ..[kCarolId] = '2026-10-01T12:00:00Z';
          admin.rows.first
            ..['apple_subscription'] = stripeSubscription(
              'past_due',
              startedAt: '2026-08-01T09:00:00Z',
              periodEnd: '2026-11-20T12:00:00Z',
            )
            ..['apple_renewing'] = true
            ..['google_subscription'] = stripeSubscription(
              'past_due',
              startedAt: '2026-06-15T09:00:00Z',
              periodEnd: null,
            )
            ..['google_renewing'] = true;
          final app = buildApp(
            server,
            store: MemoryTokenStore(server.addSession()),
          );
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();
          await after?.call(tester);

          await expectLater(
            find.byType(ShushGiftApp),
            matchesGoldenFile('goldens/$screen${suffix}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
