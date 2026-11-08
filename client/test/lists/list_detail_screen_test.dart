import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/lists/gift_form_screen.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';

import '../support/fakes.dart';
import 'support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;
  late String listId;

  setUp(() {
    server = FakeListsServer();
    listId = server.addList('Christmas', recipientName: 'Léa');
  });

  testWidgets('signed out, a list goes through sign-in and back',
      (tester) async {
    final app =
        await startApp(tester, server, '/lists/$listId', signedIn: false);

    expect(find.byType(SignInScreen), findsOneWidget);

    await app.auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(find.text('Christmas'), findsOneWidget);
  });

  testWidgets('loading: progress until the list arrives', (tester) async {
    server.hold = Completer();
    await startApp(tester, server, '/lists/$listId', settle: false);

    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    server.hold!.complete();
    await tester.pumpAndSettle();
    expect(find.text('Christmas'), findsOneWidget);
  });

  testWidgets('empty: who it is for, and no gifts yet', (tester) async {
    await startApp(tester, server, '/lists/$listId');

    expect(find.text('For Léa'), findsOneWidget);
    expect(find.text('No gifts yet. Add the first one.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Add a gift'), findsOneWidget);
  });

  testWidgets('content: gifts oldest first, with price and link count',
      (tester) async {
    server.addGift(
      listId,
      'Headphones',
      links: ['https://shop.example/h', 'https://other.example/h'],
      priceAmount: '149.00',
      priceCurrency: 'EUR',
    );
    server.addGift(listId, 'Book');

    await startApp(tester, server, '/lists/$listId');

    final cards = tester.widgetList<GiftCard>(find.byType(GiftCard)).toList();
    expect(cards.map((card) => card.title), ['Headphones', 'Book']);
    expect(cards[0].metadata, '€149.00');
    expect(find.text('2 links'), findsOneWidget);
    expect(cards[1].metadata, isNull);
    expect(cards[1].action, isNull);
  });

  testWidgets('error: says why and retries', (tester) async {
    server.status['GET /api/lists/$listId'] = 500;
    await startApp(tester, server, '/lists/$listId');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );

    server.status.remove('GET /api/lists/$listId');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(find.text('For Léa'), findsOneWidget);
  });

  testWidgets('a list that is gone, or not mine, says so', (tester) async {
    await startApp(tester, server, '/lists/someone-elses');

    expect(find.text('This list no longer exists.'), findsOneWidget);
    expect(find.text('Try again'), findsNothing);
    await tester.tap(find.text('Back to my lists'));
    await tester.pumpAndSettle();
    expect(find.text('My lists'), findsOneWidget);
  });

  testWidgets('one link opens in the external browser', (tester) async {
    final launcher = installFakeUrlLauncher();
    server.addGift(listId, 'Headphones', links: ['https://shop.example/h']);
    await startApp(tester, server, '/lists/$listId');

    final button = find.byTooltip('Open the link');
    expect(tester.getSize(button).shortestSide, greaterThanOrEqualTo(44));
    await tester.tap(button);
    await tester.pumpAndSettle();

    expect(launcher.launched, [
      ('https://shop.example/h', PreferredLaunchMode.externalApplication),
    ]);
    expect(find.byType(GiftFormScreen), findsNothing);
  });

  testWidgets('several links are offered in a menu', (tester) async {
    final launcher = installFakeUrlLauncher();
    server.addGift(listId, 'Headphones', links: [
      'https://shop.example/h',
      'https://other.example/h',
    ]);
    await startApp(tester, server, '/lists/$listId');

    final button = find.byTooltip('Open a link');
    expect(tester.getSize(button).shortestSide, greaterThanOrEqualTo(44));
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.tap(find.text('https://other.example/h'));
    await tester.pumpAndSettle();

    expect(launcher.launched.single.$1, 'https://other.example/h');
  });

  testWidgets('a link the client does not trust is not opened',
      (tester) async {
    final launcher = installFakeUrlLauncher();
    server.addGift(listId, 'Odd', links: ['javascript:alert(1)']);
    await startApp(tester, server, '/lists/$listId');

    await tester.tap(find.byTooltip('Open the link'));
    await tester.pumpAndSettle();

    expect(launcher.launched, isEmpty);
    expect(find.text('The link could not be opened.'), findsOneWidget);
  });

  testWidgets('a gift opens its edit form; the list shows the change after',
      (tester) async {
    final giftId = server.addGift(listId, 'Headphones');
    await startApp(tester, server, '/lists/$listId');

    await tester.tap(find.text('Headphones'));
    await tester.pumpAndSettle();
    expect(find.byType(GiftFormScreen), findsOneWidget);

    await tester.enterText(fieldLabelled('What is it?'), 'Earphones');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(server.gift(giftId)!['title'], 'Earphones');
    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(find.text('Earphones'), findsOneWidget);
  });

  group('deleting the list', () {
    Future<void> askToDelete(WidgetTester tester) async {
      await tester.tap(find.byTooltip('Show menu'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete list'));
      await tester.pumpAndSettle();
    }

    testWidgets('asks first; cancel deletes nothing', (tester) async {
      await startApp(tester, server, '/lists/$listId');

      await askToDelete(tester);
      expect(find.text('Delete this list?'), findsOneWidget);

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(server.calls, isNot(contains('DELETE /api/lists/$listId')));
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('confirming deletes it and goes back to My lists',
        (tester) async {
      server.addList('Birthday');
      await startApp(tester, server, '/lists/$listId');

      await askToDelete(tester);
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();

      expect(server.lists.containsKey(listId), isFalse);
      expect(find.text('My lists'), findsOneWidget);
      expect(find.text('Birthday'), findsOneWidget);
      expect(find.text('Christmas'), findsNothing);
    });

    testWidgets('a failed deletion says so and stays', (tester) async {
      server.status['DELETE /api/lists/$listId'] = 500;
      await startApp(tester, server, '/lists/$listId');

      await askToDelete(tester);
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();

      expect(find.text('It could not be deleted. Try again.'), findsOneWidget);
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });
  });
}
