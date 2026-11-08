import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/api/api_image.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/image_viewer.dart';
import 'package:wishlist/src/design/widgets/privacy_banner.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/shared/shared_with_me_screen.dart';

import '../lists/support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;
  late String list;
  late String occasion;

  setUp(() {
    server = FakeListsServer();
    list = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    occasion = server.addOccasion(
      list,
      'Christmas 2026',
      '2026-12-24',
      token: 'tok',
      invitees: ['Carol'],
    );
    server.joined.add(occasion);
  });

  testWidgets('loading: progress until the occasion arrives', (tester) async {
    server.hold = Completer();
    await startApp(tester, server, '/shared/$occasion', settle: false);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    server.hold!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('content: the list, who it is for, the banner and the gifts',
      (tester) async {
    server.addGift(
      list,
      'Headphones',
      links: ['https://shop.example/h'],
      priceAmount: '149.00',
      priceCurrency: 'EUR',
    );
    server.addGift(list, 'Book');
    await startApp(tester, server, '/shared/$occasion');

    expect(find.widgetWithText(AppBar, 'Christmas'), findsOneWidget);
    expect(find.text('Christmas 2026'), findsOneWidget);
    expect(find.text('Dec 24, 2026'), findsOneWidget);
    expect(find.text('For Léa · shared by Bob Durand'), findsOneWidget);
    expect(
      tester.widget<PrivacyBanner>(find.byType(PrivacyBanner)).message,
      "Léa doesn't see what you do here",
    );
    final cards = tester.widgetList<GiftCard>(find.byType(GiftCard)).toList();
    expect(cards.map((card) => card.title), ['Headphones', 'Book']);
    expect(cards[0].metadata, '€149.00');
    expect(find.text('1 link'), findsOneWidget);
    expect(cards[1].action, isNull);
  });

  testWidgets('a list made for oneself: the banner names its owner',
      (tester) async {
    final own = server.addList('Birthday', ownerNames: ['Sam Lee']);
    final birthday = server.addOccasion(own, 'Birthday', '2027-03-02');
    server.joined.add(birthday);
    await startApp(tester, server, '/shared/$birthday');

    expect(
      tester.widget<PrivacyBanner>(find.byType(PrivacyBanner)).message,
      "Sam Lee doesn't see what you do here",
    );
  });

  testWidgets('read-only: no edit control, no link, no invitee',
      (tester) async {
    server.addGift(list, 'Headphones', links: ['https://shop.example/h']);
    await startApp(tester, server, '/shared/$occasion');

    for (final owners in [
      'Add a gift',
      'New occasion',
      'Copy link',
      'Share',
      'Invitees',
      'Carol',
      'Rename',
      'Delete list',
    ]) {
      expect(find.text(owners), findsNothing, reason: owners);
    }
    expect(find.byType(FloatingActionButton), findsNothing);
    expect(find.byType(TextField), findsNothing);
    // A gift without details opens nothing.
    expect(tester.widget<GiftCard>(find.byType(GiftCard)).onTap, isNull);

    await tester.tap(find.byTooltip('Show menu'));
    await tester.pumpAndSettle();
    expect(find.text('Leave the occasion'), findsOneWidget);
    expect(find.text('Rename'), findsNothing);

    // Only the invitee's own calls: Shared with me, under this page, and
    // the occasion.
    expect(
      server.calls.toSet(),
      {'GET /api/shared', 'GET /api/occasions/$occasion'},
    );
  });

  testWidgets('a gift with details shows them when tapped', (tester) async {
    server.addGift(list, 'Headphones', description: 'Black, over-ear');
    await startApp(tester, server, '/shared/$occasion');

    expect(find.text('Details'), findsOneWidget);
    expect(find.text('Black, over-ear'), findsNothing);
    await tester.tap(find.text('Headphones'));
    await tester.pumpAndSettle();

    expect(find.text('Black, over-ear'), findsOneWidget);
  });

  group('gift images', () {
    late String imageId;

    setUp(() {
      final gift = server.addGift(list, 'Headphones', image: true);
      imageId = (server.gift(gift)!['image'] as Map)['id'] as String;
    });

    testWidgets('the card shows the thumbnail on the occasion path',
        (tester) async {
      final app = await startApp(tester, server, '/shared/$occasion');

      final card = tester.widget<GiftCard>(find.byType(GiftCard));
      expect(
        card.image,
        ApiImage(app.api, '/api/occasions/$occasion/images/$imageId/thumb'),
      );
      expect(
        server.calls,
        contains('GET /api/occasions/$occasion/images/$imageId/thumb'),
      );
    });

    testWidgets('tapping the thumbnail opens the full image in the viewer',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');

      await tester.tap(find.byKey(const ValueKey('gift-card-image')));
      await tester.pumpAndSettle();

      expect(find.byType(ImageViewer), findsOneWidget);
      expect(
        server.calls,
        contains('GET /api/occasions/$occasion/images/$imageId/full'),
      );

      await tester.tap(find.byTooltip('Close'));
      await tester.pumpAndSettle();
      expect(find.byType(ImageViewer), findsNothing);
    });

    testWidgets('tapping the card elsewhere keeps its behaviour',
        (tester) async {
      server.addGift(list, 'Book', description: 'The illustrated edition');
      await startApp(tester, server, '/shared/$occasion');

      await tester.tap(find.text('Book'));
      await tester.pumpAndSettle();

      expect(find.text('The illustrated edition'), findsOneWidget);
      expect(find.byType(ImageViewer), findsNothing);
    });
  });

  testWidgets('a gift link opens in the external browser', (tester) async {
    final launcher = installFakeUrlLauncher();
    server.addGift(list, 'Headphones', links: ['https://shop.example/h']);
    await startApp(tester, server, '/shared/$occasion');

    await tester.tap(find.byTooltip('Open the link'));
    await tester.pumpAndSettle();

    expect(launcher.launched, [
      ('https://shop.example/h', PreferredLaunchMode.externalApplication),
    ]);
  });

  testWidgets('leaving asks first; cancel leaves nothing', (tester) async {
    await startApp(tester, server, '/shared/$occasion');

    await tester.tap(find.byTooltip('Show menu'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Leave the occasion'));
    await tester.pumpAndSettle();

    expect(find.text('Leave this occasion?'), findsOneWidget);
    expect(
      find.text(
        'You no longer see this list. You can join again with a current link.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(server.calls, isNot(contains('DELETE /api/occasions/$occasion/membership')));
    expect(server.joined, contains(occasion));
  });

  testWidgets('leaving calls the server and goes to Shared with me',
      (tester) async {
    await startApp(tester, server, '/shared/$occasion');

    await tester.tap(find.byTooltip('Show menu'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Leave the occasion'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Leave'));
    await tester.pumpAndSettle();

    expect(server.calls, contains('DELETE /api/occasions/$occasion/membership'));
    expect(server.joined, isEmpty);
    expect(find.byType(SharedWithMeScreen), findsOneWidget);
  });

  testWidgets('a failed leave says so and stays', (tester) async {
    server.status['DELETE /api/occasions/$occasion/membership'] = 500;
    await startApp(tester, server, '/shared/$occasion');

    await tester.tap(find.byTooltip('Show menu'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Leave the occasion'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Leave'));
    await tester.pumpAndSettle();

    expect(
      find.text('You could not leave the occasion. Try again.'),
      findsOneWidget,
    );
    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('no longer shared (removed, left or deleted) says so',
      (tester) async {
    server.joined.clear();
    await startApp(tester, server, '/shared/$occasion');

    expect(
      find.text('This occasion is no longer shared with you.'),
      findsOneWidget,
    );
    expect(find.byType(PrivacyBanner), findsNothing);

    await tester.tap(find.text('Back to shared with me'));
    await tester.pumpAndSettle();
    expect(find.byType(SharedWithMeScreen), findsOneWidget);
  });

  testWidgets('an owner opening the occasion lands on the list',
      (tester) async {
    final mine = server.addList('Birthday');
    final own = server.addOccasion(mine, 'Birthday 2026', '2026-06-01');
    await startApp(tester, server, '/shared/$own');

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(find.byType(PrivacyBanner), findsNothing);
  });

  testWidgets('error: says why and retries', (tester) async {
    server.status['GET /api/occasions/$occasion'] = 500;
    await startApp(tester, server, '/shared/$occasion');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );

    server.status.remove('GET /api/occasions/$occasion');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    server.addGift(
      list,
      'Casque',
      priceAmount: '149.00',
      priceCurrency: 'EUR',
    );
    await startApp(tester, server, '/shared/$occasion');

    expect(
      tester.widget<PrivacyBanner>(find.byType(PrivacyBanner)).message,
      'Léa ne voit pas ce que vous faites ici',
    );
    expect(find.text('Pour Léa · partagée par Bob Durand'), findsOneWidget);
    expect(
      tester.widget<GiftCard>(find.byType(GiftCard)).metadata,
      matches(RegExp('^149,00[  ]€\$')),
    );
  });
}
