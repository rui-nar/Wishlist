@Tags(['golden'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/main.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  // The whole app, as a phone shows it: the device's language and brightness
  // pick the locale and the theme, as they do in use (D8, D9).
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};
  const locales = {'en': Locale('en', 'GB'), 'fr': Locale('fr', 'FR')};

  final clients = {
    // Answers /api/version with v1.2.0 on validation.
    'success': MockClient((request) async => http.Response(
          jsonEncode({'version': 'v1.2.0', 'env': 'validation'}),
          200,
        )),
    'unreachable': MockClient((request) async {
      throw http.ClientException('Connection refused', request.url);
    }),
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: state, value: client) in clients.entries) {
      for (final MapEntry(key: language, value: locale) in locales.entries) {
        for (final MapEntry(key: mode, value: brightness)
            in brightnesses.entries) {
          testWidgets('version screen, $state, $language, $mode',
              (tester) async {
            tester.view.physicalSize = const Size(390, 844);
            tester.view.devicePixelRatio = 1;
            addTearDown(tester.view.reset);
            tester.platformDispatcher.localesTestValue = [locale];
            tester.platformDispatcher.platformBrightnessTestValue = brightness;
            addTearDown(tester.platformDispatcher.clearAllTestValues);
            // No DEBUG ribbon: the goldens show the app as users see it.
            WidgetsApp.debugAllowBannerOverride = false;
            addTearDown(() => WidgetsApp.debugAllowBannerOverride = true);

            await tester.pumpWidget(WishlistApp(
              httpClient: client,
              apiBaseUrl: 'http://api.test',
              appVersion: 'v1.2.3',
            ));
            await tester.pumpAndSettle();

            await expectLater(
              find.byType(WishlistApp),
              matchesGoldenFile(
                'goldens/version_screen_${state}_${language}_$mode.png',
              ),
            );
          }, tags: ['golden']);
        }
      }
    }
  });
}
