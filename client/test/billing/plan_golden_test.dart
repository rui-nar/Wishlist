@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/billing/billing_repository.dart';

import '../support/fakes.dart';
import 'support.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  final free = billingStatus(offer: kBillingOffer);
  final premium = billingStatus(
    plan: 'premium',
    status: 'active',
    renewsAt: '2027-03-12T12:00:00Z',
    limits: const {'max_lists': null, 'max_gifts_per_list': null},
    canManage: true,
  );
  // Granted by the admin (admin panel plan D8).
  final manual = billingStatus(
    plan: 'premium',
    source: 'manual',
    status: 'active',
    renewsAt: '2027-03-12T12:00:00Z',
    limits: const {'max_lists': null, 'max_gifts_per_list': null},
  );

  // In the iOS app (Apple IAP plan D8): Apple selling, and Premium bought
  // there.
  final iosFree = billingStatus(appleOffer: kAppleOffer, offer: kBillingOffer);

  // The golden's name, the location the app opens at, the plan, and whether
  // in the iOS app; the others as on the web.
  final screens = {
    'account_screen_free_offer': ('/account', free, false),
    'account_screen_premium': ('/account', premium, false),
    'plan_screen_free': (kPlanPath, free, false),
    'plan_screen_premium': (kPlanPath, premium, false),
    'plan_screen_manual': (kPlanPath, manual, false),
    'plan_screen_ios_free': (kPlanPath, iosFree, true),
    'plan_screen_ios_apple': (kPlanPath, kAppleSubscribed, true),
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: (location, billing, ios))
        in screens.entries) {
      for (final MapEntry(key: mode, value: brightness)
          in brightnesses.entries) {
        testWidgets('$screen, $mode', (tester) async {
          tester.view.physicalSize = const Size(390, 844);
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
          if (ios) {
            installFakeStore();
          } else {
            debugOnTheWeb = true;
            addTearDown(() => debugOnTheWeb = null);
          }

          final server = FakeServer()..billing = billing;
          final app = buildApp(
            server,
            store: MemoryTokenStore(server.addSession()),
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
