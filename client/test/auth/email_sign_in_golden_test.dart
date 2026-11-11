@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shushgift/main.dart';

import '../support/fakes.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  // The golden's name and the location the app opens at.
  const screens = {
    'sign_in_with_email': '/sign-in',
    'sign_in_with_apple': '/sign-in',
    'email_sign_up': '/email-sign-up',
    'check_inbox': '/email-sign-up',
    'create_account': '/create-account#$kEmailLinkToken',
    'reset_password': '/reset-password#$kEmailLinkToken',
    'email_link_expired': '/create-account',
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: location) in screens.entries) {
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
          SharedPreferences.setMockInitialValues({});

          final apple = screen == 'sign_in_with_apple';
          final app = buildApp(FakeServer(
            emailSignIn: true,
            appleClientId: apple ? kAppleClientId : null,
            appleRedirectUri: apple ? kAppleRedirectUri : null,
          ));
          await tester.pumpWidget(app.app);
          await app.auth.restore();
          await tester.pumpAndSettle();
          if (screen == 'check_inbox') {
            await tester.enterText(
              find.byType(TextFormField),
              'alice@example.com',
            );
            await tester.tap(find.text('Send the link'));
            await tester.pumpAndSettle();
          }

          await expectLater(
            find.byType(ShushGiftApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
