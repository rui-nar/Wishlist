@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/shared/pending_join.dart';

import '../lists/support/fake_lists_server.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

/// Bob's list for Léa, with an occasion Alice can join with `tok`.
String _bobsOccasion(FakeListsServer server) {
  final list = server.addList(
    'Christmas',
    recipientName: 'Léa',
    ownerNames: ['Bob Durand'],
  );
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
    description: 'The illustrated edition',
    links: ['https://books.example/sea'],
  );
  server.addGift(list, 'Wool socks');
  return server.addOccasion(list, 'Christmas 2026', '2026-12-24', token: 'tok');
}

void main() {
  const brightnesses = {'light': Brightness.light, 'dark': Brightness.dark};

  // Each screen: its data, the location the app opens at, and the link it
  // was opened with.
  final screens =
      <String, (String, String?) Function(FakeListsServer)>{
    'shared_with_me_empty': (server) => ('/shared', null),
    'shared_with_me': (server) {
      server.joined.add(_bobsOccasion(server));
      final own = server.addList('Birthday', ownerNames: ['Sam Lee']);
      server.joined.add(server.addOccasion(own, 'Thirty', '2027-03-02'));
      return ('/shared', null);
    },
    'occasion_view': (server) {
      final occasion = _bobsOccasion(server);
      server.joined.add(occasion);
      return ('/shared/$occasion', null);
    },
    'join_confirmation': (server) {
      _bobsOccasion(server);
      return ('/join', 'tok');
    },
    'join_error': (server) => ('/join', 'gone'),
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
          final (location, token) = setUp(server);
          await startApp(
            tester,
            server,
            location,
            pendingJoin: PendingJoin(MemoryJoinBrowser(), token),
          );

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
