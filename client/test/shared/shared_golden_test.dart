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

/// Bob's list for Léa, with an occasion Alice can join with `tok`; the
/// first gift has a picture when [image] is set.
String _bobsOccasion(FakeListsServer server, {bool image = false}) {
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
    image: image,
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

/// Bob's occasion joined, with a gift in each activity state Alice can see
/// (RESERVING_PLAN D13); the first is free.
String _activeOccasion(FakeListsServer server) {
  final occasion = _bobsOccasion(server);
  server.joined.add(occasion);
  final list = server.occasions[occasion]!['list_id'] as String;
  final elsewhere = server.addOccasion(list, 'Birthday', '2027-03-02');
  final [_, book, socks] = [for (final gift in server.gifts) gift['id'] as String];
  String gift(String title) => server.addGift(list, title);
  final carol = FakeListsServer.giver('Carol Lambert');
  final alice = FakeListsServer.giver(kAliceName, mine: true);
  server
    ..addClaim(book, occasion, [carol])
    ..addClaim(socks, occasion, [alice])
    ..addClaim(gift('Scarf'), occasion, [carol], bought: true)
    ..addClaim(gift('Candle'), occasion, [], bought: true)
    ..addClaim(gift('Board game'), occasion, [carol, alice], group: true)
    ..addClaim(gift('Bike lights'), occasion, [carol], group: true, bought: true)
    ..addClaim(gift('Teapot'), elsewhere, [FakeListsServer.giver('Eve')]);
  return occasion;
}

/// Bob's occasion joined, its headphones a group gift with pledges.
String _groupOccasion(FakeListsServer server) {
  final occasion = _bobsOccasion(server);
  server.joined.add(occasion);
  server.addClaim(server.gifts.first['id'] as String, occasion, [
    FakeListsServer.giver('Carol Lambert', amount: '50.00', currency: 'EUR'),
    FakeListsServer.giver('Dan Moreau'),
    FakeListsServer.giver(kAliceName, mine: true, amount: '30.00', currency: 'EUR'),
  ], group: true);
  return occasion;
}

/// Alice's own list for Léa, its occasion with Carol's reservation and a
/// group gift Alice is in: her giver view (RESERVING_PLAN D14).
String _giverOccasion(FakeListsServer server) {
  final list = server.addList('Christmas', recipientName: 'Léa');
  final headphones = server.addGift(
    list,
    'Noise-cancelling headphones',
    links: ['https://shop.example/h'],
    priceAmount: '149.00',
    priceCurrency: 'EUR',
  );
  final book = server.addGift(list, 'A book about the sea');
  server.addGift(list, 'Wool socks');
  final occasion = server.addOccasion(
    list,
    'Christmas 2026',
    '2026-12-24',
    invitees: ['Carol Lambert'],
  );
  server
    ..addClaim(book, occasion, [FakeListsServer.giver('Carol Lambert')])
    ..addClaim(headphones, occasion, [
      FakeListsServer.giver('Carol Lambert', amount: '50.00', currency: 'EUR'),
      FakeListsServer.giver(kAliceName, mine: true),
    ], group: true);
  return '/lists/$list/occasions/$occasion';
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
    'occasion_view_image': (server) {
      final occasion = _bobsOccasion(server, image: true);
      server.joined.add(occasion);
      return ('/shared/$occasion', null);
    },
    'occasion_activity': (server) =>
        ('/shared/${_activeOccasion(server)}', null),
    'gift_sheet_group': (server) => ('/shared/${_groupOccasion(server)}', null),
    'occasion_giver': (server) => (_giverOccasion(server), null),
    'pledge_dialog': (server) => ('/shared/${_groupOccasion(server)}', null),
    'join_confirmation': (server) {
      _bobsOccasion(server);
      return ('/join', 'tok');
    },
    'join_error': (server) => ('/join', 'gone'),
  };

  // What is tapped once the screen is shown.
  final then = <String, Future<void> Function(WidgetTester)>{
    'gift_sheet_group': (tester) async {
      await tester.tap(find.text('Noise-cancelling headphones'));
      await tester.pumpAndSettle();
    },
    'pledge_dialog': (tester) async {
      await tester.tap(find.text('Noise-cancelling headphones'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Change my amount'));
      await tester.pumpAndSettle();
    },
  };

  // Every activity chip needs a taller screen.
  const tall = {'occasion_activity'};

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: screen, value: setUp) in screens.entries) {
      for (final MapEntry(key: mode, value: brightness)
          in brightnesses.entries) {
        testWidgets('$screen, $mode', (tester) async {
          tester.view.physicalSize =
              Size(390, tall.contains(screen) ? 1120 : 844);
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
          if (screen == 'occasion_view_image') await loadImages(tester);
          await then[screen]?.call(tester);

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/${screen}_$mode.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
