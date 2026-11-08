@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';

import 'support/fake_lists_server.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  // Each screen: its data, and the location the app opens at.
  final screens = <String, String Function(FakeListsServer)>{
    'my_lists_empty': (server) => '/',
    'my_lists': (server) {
      final mine = server.addList('Birthday');
      server.addGift(mine, 'Headphones');
      server.addGift(mine, 'Book');
      server.addList('Christmas', recipientName: 'Léa');
      return '/';
    },
    'list_detail': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      server.addGift(
        list,
        'Noise-cancelling headphones',
        links: ['https://shop.example/h', 'https://other.example/h'],
        priceAmount: '149.00',
        priceCurrency: 'EUR',
      );
      server.addGift(
        list,
        'A book about the sea',
        links: ['https://books.example/sea'],
      );
      server.addGift(list, 'Wool socks');
      return '/lists/$list';
    },
    'gift_form': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final gift = server.addGift(
        list,
        'Noise-cancelling headphones',
        description: 'Black, over-ear',
        links: ['https://shop.example/h'],
        priceAmount: '149.00',
        priceCurrency: 'EUR',
      );
      return '/lists/$list/gifts/$gift/edit';
    },
  };

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: setUp) in screens.entries) {
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
          addTearDown(tester.platformDispatcher.clearAllTestValues);
          // No DEBUG ribbon: the goldens show the app as users see it.
          WidgetsApp.debugAllowBannerOverride = false;
          addTearDown(() => WidgetsApp.debugAllowBannerOverride = true);

          final server = FakeListsServer();
          await startApp(tester, server, setUp(server));

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
