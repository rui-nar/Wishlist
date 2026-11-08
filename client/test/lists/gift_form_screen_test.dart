import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/lists/gift_form_screen.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';

import 'support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;
  late String listId;

  setUp(() {
    server = FakeListsServer();
    listId = server.addList('Birthday');
  });

  String addPath() => 'POST /api/lists/$listId/gifts';

  /// Types [text] in the field labelled [label], scrolled into view first.
  Future<void> type(WidgetTester tester, String label, String text) async {
    await tester.ensureVisible(fieldLabelled(label));
    await tester.pumpAndSettle();
    await tester.enterText(fieldLabelled(label), text);
  }

  Future<void> save(WidgetTester tester, [String label = 'Add a gift']) async {
    final button = find.widgetWithText(FilledButton, label);
    await tester.ensureVisible(button);
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();
  }

  group('adding', () {
    testWidgets('an empty title is refused', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await save(tester);

      expect(find.text('Enter what the gift is'), findsOneWidget);
      expect(server.calls, isNot(contains(addPath())));
    });

    testWidgets('a link that is not http or https is refused', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await type(tester, 'What is it?', 'Headphones');
      for (final bad in ['javascript:alert(1)', 'shop.example/h', 'ftp://x']) {
        await type(tester, 'Link 1', bad);
        await save(tester);

        expect(
          find.text('Enter a web address starting with http:// or https://'),
          findsOneWidget,
          reason: bad,
        );
      }
      expect(server.calls, isNot(contains(addPath())));
    });

    testWidgets('an amount the server would refuse is refused', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await type(tester, 'What is it?', 'Headphones');
      for (final bad in ['19.999', '-1', '10000000000', 'abc']) {
        await type(tester, 'Price (indicative)', bad);
        await save(tester);

        expect(
          find.text('Enter an amount such as 149.90'),
          findsOneWidget,
          reason: bad,
        );
      }
      expect(server.calls, isNot(contains(addPath())));
    });

    testWidgets('an amount without a currency is refused, and an unknown '
        'currency too', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await type(tester, 'What is it?', 'Headphones');
      await type(tester, 'Price (indicative)', '149');
      await type(tester, 'Currency', '');
      await save(tester);
      expect(find.text('Enter a currency code such as EUR'), findsOneWidget);

      await type(tester, 'Currency', 'xyz');
      await save(tester);
      expect(find.text('Unknown currency code'), findsOneWidget);

      expect(server.calls, isNot(contains(addPath())));
    });

    testWidgets('a currency without an amount is no price: none is sent', (
      tester,
    ) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await type(tester, 'What is it?', 'Headphones');
      await type(tester, 'Currency', 'usd');
      await save(tester);

      expect(server.bodies[addPath()]!['price_amount'], isNull);
      expect(server.bodies[addPath()]!['price_currency'], isNull);
    });

    testWidgets(
      'sends every field, EUR by default, and goes back to the list',
      (tester) async {
        await startApp(tester, server, '/lists/$listId');
        await tester.tap(find.text('Add a gift'));
        await tester.pumpAndSettle();

        await type(tester, 'What is it?', ' Headphones ');
        await type(tester, 'Details (size, colour, model...)', 'Black');
        await type(tester, 'Price (indicative)', '149,90');
        await type(tester, 'Link 1', 'https://shop.example/h');
        await tester.ensureVisible(find.text('Add a link'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Add a link'));
        await tester.pumpAndSettle();
        await type(tester, 'Link 2', 'https://other.example/h');
        await tester.ensureVisible(find.text('Add a link'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Add a link'));
        await tester.pumpAndSettle();
        // An empty link field is left out.
        await save(tester);

        expect(server.bodies[addPath()], {
          'title': 'Headphones',
          'description': 'Black',
          'links': ['https://shop.example/h', 'https://other.example/h'],
          'price_amount': '149.90',
          'price_currency': 'EUR',
        });
        expect(find.byType(ListDetailScreen), findsOneWidget);
        expect(find.text('Headphones'), findsOneWidget);
        expect(find.text('€149.90'), findsOneWidget);
      },
    );

    testWidgets('links can be removed, and stop at ten', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      for (var i = 1; i < kMaxLinks; i++) {
        final add = find.text('Add a link');
        await tester.ensureVisible(add);
        await tester.pumpAndSettle();
        await tester.tap(add);
        await tester.pumpAndSettle();
      }
      expect(find.text('Add a link'), findsNothing);
      expect(find.byTooltip('Remove this link'), findsNWidgets(kMaxLinks));

      await type(tester, 'Link 1', 'https://a.example');
      await type(tester, 'Link 2', 'https://b.example');
      final remove = find.byTooltip('Remove this link').first;
      await tester.ensureVisible(remove);
      await tester.pumpAndSettle();
      await tester.tap(remove);
      await tester.pumpAndSettle();

      expect(find.text('https://a.example'), findsNothing);
      expect(find.text('https://b.example'), findsOneWidget);
      expect(find.text('Add a link'), findsOneWidget);
    });
  });

  group('editing', () {
    late String giftId;

    setUp(() {
      giftId = server.addGift(
        listId,
        'Headphones',
        description: 'Black',
        links: ['https://shop.example/h'],
        priceAmount: '149.00',
        priceCurrency: 'GBP',
      );
    });

    String editLocation() => '/lists/$listId/gifts/$giftId/edit';

    testWidgets('loading, then the gift as it is', (tester) async {
      server.hold = Completer();
      await startApp(tester, server, editLocation(), settle: false);

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      server.hold!.complete();
      await tester.pumpAndSettle();

      expect(find.text('Edit gift'), findsOneWidget);
      expect(find.text('Headphones'), findsOneWidget);
      expect(find.text('Black'), findsOneWidget);
      expect(find.text('https://shop.example/h'), findsOneWidget);
      expect(find.text('149.00'), findsOneWidget);
      expect(find.text('GBP'), findsOneWidget);
    });

    testWidgets('emptying the amount removes the price', (tester) async {
      await startApp(tester, server, editLocation());

      await type(tester, 'Price (indicative)', '');
      await save(tester, 'Save');

      expect(server.bodies['PATCH /api/gifts/$giftId'], {
        'title': 'Headphones',
        'description': 'Black',
        'links': ['https://shop.example/h'],
        'price_amount': null,
        'price_currency': null,
      });
    });

    testWidgets('a gift that is gone says so', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/gone/edit');

      expect(find.text('This gift no longer exists.'), findsOneWidget);
    });

    testWidgets('an error loading it offers a retry', (tester) async {
      server.status['GET /api/lists/$listId'] = 503;
      await startApp(tester, server, editLocation());

      expect(
        find.text('The server could not complete the request. Try again.'),
        findsOneWidget,
      );
      server.status.clear();
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Headphones'), findsOneWidget);
    });

    testWidgets('delete asks first; cancel deletes nothing', (tester) async {
      await startApp(tester, server, editLocation());

      final delete = find.text('Delete gift');
      await tester.ensureVisible(delete);
      await tester.pumpAndSettle();
      await tester.tap(delete);
      await tester.pumpAndSettle();
      expect(find.text('Delete this gift?'), findsOneWidget);

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(server.calls, isNot(contains('DELETE /api/gifts/$giftId')));
      expect(find.byType(GiftFormScreen), findsOneWidget);
    });

    testWidgets('confirming deletes it and goes back to the list', (
      tester,
    ) async {
      await startApp(tester, server, '/lists/$listId');
      await tester.tap(find.text('Headphones'));
      await tester.pumpAndSettle();

      final delete = find.text('Delete gift');
      await tester.ensureVisible(delete);
      await tester.pumpAndSettle();
      await tester.tap(delete);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();

      expect(server.gift(giftId), isNull);
      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(find.text('No gifts yet. Add the first one.'), findsOneWidget);
    });

    testWidgets('a failed save says so and stays on the form', (tester) async {
      server.status['PATCH /api/gifts/$giftId'] = 500;
      await startApp(tester, server, editLocation());

      await save(tester, 'Save');

      expect(
        find.text('Your changes could not be saved. Try again.'),
        findsOneWidget,
      );
      expect(find.byType(GiftFormScreen), findsOneWidget);
    });
  });

  testWidgets('in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    server.addGift(
      listId,
      'Casque',
      priceAmount: '149.00',
      priceCurrency: 'EUR',
    );
    await startApp(tester, server, '/lists/$listId');

    expect(find.textContaining(RegExp('^149,00[  ]€\$')), findsOneWidget);

    await tester.tap(find.text('Ajouter un cadeau'));
    await tester.pumpAndSettle();

    expect(fieldLabelled("De quoi s'agit-il ?"), findsOneWidget);
    expect(fieldLabelled('Prix (indicatif)'), findsOneWidget);
    expect(fieldLabelled('Devise'), findsOneWidget);
    expect(find.text('Liens vers des boutiques'), findsOneWidget);

    await type(tester, 'Prix (indicatif)', '12,345');
    await type(tester, 'Lien 1', 'pas un lien');
    final add = find.widgetWithText(FilledButton, 'Ajouter un cadeau');
    await tester.ensureVisible(add);
    await tester.pumpAndSettle();
    await tester.tap(add);
    await tester.pumpAndSettle();

    expect(find.text("Indiquez de quel cadeau il s'agit"), findsOneWidget);
    expect(find.text('Saisissez un montant comme 149,90'), findsOneWidget);
    expect(
      find.text('Saisissez une adresse web commençant par http:// ou https://'),
      findsOneWidget,
    );
  });
}
