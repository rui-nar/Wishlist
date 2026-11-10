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
    'list_detail_image': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      server.addGift(
        list,
        'Noise-cancelling headphones',
        priceAmount: '149.00',
        priceCurrency: 'EUR',
        image: true,
      );
      server.addGift(list, 'Wool socks');
      return '/lists/$list';
    },
    // A revealed gift and a received one (HIDDEN_GIFTS_PLAN D13).
    'list_detail_received': (server) {
      final list = server.addList('Birthday');
      server.addGift(list, 'Wool socks');
      server.addRevealed(
        list,
        'Noise-cancelling headphones',
        links: ['https://shop.example/h'],
        priceAmount: '149.00',
        priceCurrency: 'EUR',
      );
      server.markReceived(server.addGift(list, 'A book about the sea'));
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
    'gift_form_image': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final gift = server.addGift(
        list,
        'Noise-cancelling headphones',
        priceAmount: '149.00',
        priceCurrency: 'EUR',
        image: true,
      );
      return '/lists/$list/gifts/$gift/edit';
    },
    // An image URL the server could not download (D14).
    'gift_form_image_error': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      server.status['POST /api/images/from-url'] = 422;
      server.details['POST /api/images/from-url'] = 'url_fetch_failed';
      return '/lists/$list/gifts/new';
    },
    'list_occasions': (server) {
      server.accounts.publicBaseUrl = 'https://wishlist.example';
      final list = server.addList('Christmas', recipientName: 'Léa');
      server.addGift(list, 'Wool socks');
      server.addOccasion(
        list,
        'Christmas 2026',
        '2026-12-24',
        token: 'tok',
        invitees: ['Carol', 'Dan'],
      );
      server.addOccasion(list, 'Birthday', '2027-03-02');
      return '/lists/$list';
    },
    'occasion_form': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
      return '/lists/$list/occasions/$occasion/edit';
    },
    // The date moved earlier: the warning under it (HIDDEN_GIFTS_PLAN D13).
    'occasion_form_warning': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
      return '/lists/$list/occasions/$occasion/edit';
    },
    'occasion_members': (server) {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final occasion = server.addOccasion(
        list,
        'Christmas 2026',
        '2026-12-24',
        invitees: ['Carol Dupont', 'Dan Smith', 'Eve Martin'],
      );
      server.removed[occasion]!.add(server.members[occasion]!.removeLast());
      return '/lists/$list/occasions/$occasion/members';
    },
  };

  // What a screen does once open, before its picture is taken.
  final after = <String, Future<void> Function(WidgetTester)>{
    'list_detail_image': loadImages,
    'gift_form_image': loadImages,
    'gift_form_image_error': (tester) async {
      await tester.tap(find.text('Image URL'));
      await tester.pumpAndSettle();
      await tester.enterText(
        fieldLabelled('Image address'),
        'https://shop.example/h.png',
      );
      await tester.tap(find.text('Use this image'));
      await tester.pumpAndSettle();
    },
    // The Received section open, its gift in view.
    'list_detail_received': (tester) async {
      final received = find.text('Received (1)');
      await tester.ensureVisible(received);
      await tester.pumpAndSettle();
      await tester.tap(received);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('A book about the sea'));
      await tester.pumpAndSettle();
    },
    'occasion_form_warning': (tester) async {
      await tester.tap(find.byIcon(Icons.calendar_today_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('15'));
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
    },
    // The occasions, below the gifts.
    'list_occasions': (tester) async {
      await tester.scrollUntilVisible(
        find.text('Birthday'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
    },
  };

  // Each picture's screen and window: every screen on a phone, named
  // without its size, and the screens also drawn on a desktop window
  // (WEB_LAYOUT_PLAN D2, D3), named with it.
  const wide = {'my_lists', 'list_detail'};
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
        final name = '$screen${suffix}_$mode';
        testWidgets('$screen$suffix, $mode', (tester) async {
          tester.view.physicalSize = size;
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
          await startApp(tester, server, screens[screen]!(server));
          await after[screen]?.call(tester);

          await expectLater(
            find.byType(WishlistApp),
            matchesGoldenFile('goldens/$name.png'),
          );
        }, tags: ['golden']);
      }
    }
  });
}
