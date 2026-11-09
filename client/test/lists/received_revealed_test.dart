import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/status_chip.dart';
import 'package:wishlist/src/lists/gift_form_screen.dart';

import 'support/fake_lists_server.dart';

/// Received and revealed gifts on the owner's list (HIDDEN_GIFTS_PLAN D5,
/// D6, D13).
void main() {
  late FakeListsServer server;

  setUp(() => server = FakeListsServer());

  Future<void> tapVisible(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  /// The button [label] on the card of the gift [title].
  Finder button(String title, String label) => find.descendant(
        of: find.widgetWithText(GiftCard, title),
        matching: find.widgetWithText(TextButton, label),
      );

  /// The titles of the cards, top to bottom, the sections' included.
  List<String> cardTitles(WidgetTester tester) => [
        for (final card in tester.widgetList<GiftCard>(find.byType(GiftCard)))
          card.title,
      ];

  Future<void> openReceived(WidgetTester tester) async {
    await tapVisible(tester, find.textContaining('Received ('));
  }

  /// Nothing rose on an owner's list screen (Conventions).
  void expectNothingRose(WidgetTester tester) {
    for (final chip in tester.widgetList<StatusChip>(find.byType(StatusChip))) {
      expect(chip.variant, isNot(StatusChipVariant.inviteeActivity));
    }
  }

  testWidgets('both sections are absent when empty', (tester) async {
    final listId = server.addList('Birthday');
    server.addGift(listId, 'Book');
    await startApp(tester, server, '/lists/$listId');

    expect(find.text('Gifts from your occasions'), findsNothing);
    expect(find.textContaining('Received ('), findsNothing);
    expect(cardTitles(tester), ['Book']);
  });

  // The same on a list for me and on a list for someone else (D6).
  for (final recipient in [null, 'Léa']) {
    final kind = recipient == null ? 'for me' : 'for someone else';

    group('a list $kind', () {
      late String listId;

      setUp(() => listId = server.addList('Birthday', recipientName: recipient));

      int loads() =>
          server.calls.where((call) => call == 'GET /api/lists/$listId').length;

      testWidgets('revealed gifts: the gift alone, three actions, no form',
          (tester) async {
        server.addGift(listId, 'Book');
        server.addRevealed(
          listId,
          'Scarf',
          links: ['https://shop.example/s'],
          priceAmount: '30.00',
          priceCurrency: 'EUR',
        );
        server.addRevealed(listId, 'Gloves');
        await startApp(tester, server, '/lists/$listId');

        expect(find.text('Gifts from your occasions'), findsOneWidget);
        // The list's gifts, then the revealed ones by title.
        expect(cardTitles(tester), ['Book', 'Gloves', 'Scarf']);
        for (final label in ['Received', 'Keep on my list', 'Dismiss']) {
          expect(button('Scarf', label), findsOneWidget);
        }
        final card = tester.widget<GiftCard>(find.widgetWithText(GiftCard, 'Scarf'));
        expect(card.metadata, '€30.00');
        expect(card.onTap, isNull);
        expect(find.textContaining('Received ('), findsNothing);
        expectNothingRose(tester);

        await tester.tap(find.text('Gloves'));
        await tester.pumpAndSettle();
        expect(find.byType(GiftFormScreen), findsNothing);
      });

      testWidgets('received: the gift moves under Received, reloaded',
          (tester) async {
        final scarf = server.addRevealed(listId, 'Scarf');
        await startApp(tester, server, '/lists/$listId');
        final before = loads();

        await tapVisible(tester, button('Scarf', 'Received'));

        expect(server.calls, contains('POST /api/gifts/$scarf/received'));
        expect(loads(), before + 1);
        expect(find.text('Gifts from your occasions'), findsNothing);
        expect(find.text('Received (1)'), findsOneWidget);
      });

      testWidgets('keep: the gift is at the end of the list, reloaded',
          (tester) async {
        server.addGift(listId, 'Book');
        server.addGift(listId, 'Pen');
        final scarf = server.addRevealed(listId, 'Scarf');
        await startApp(tester, server, '/lists/$listId');
        final before = loads();

        await tapVisible(tester, button('Scarf', 'Keep on my list'));

        expect(server.calls, contains('POST /api/gifts/$scarf/keep'));
        expect(loads(), before + 1);
        expect(find.text('Gifts from your occasions'), findsNothing);
        expect(cardTitles(tester), ['Book', 'Pen', 'Scarf']);
        // Now an ordinary gift, under its new id: it opens its form.
        expect(server.gift(scarf), isNull);
        await tester.tap(find.text('Scarf'));
        await tester.pumpAndSettle();
        expect(find.byType(GiftFormScreen), findsOneWidget);
      });

      testWidgets('dismiss asks first; cancel changes nothing',
          (tester) async {
        final scarf = server.addRevealed(listId, 'Scarf');
        await startApp(tester, server, '/lists/$listId');

        await tapVisible(tester, button('Scarf', 'Dismiss'));
        expect(find.text('Dismiss this gift?'), findsOneWidget);
        await tester.tap(find.text('Cancel'));
        await tester.pumpAndSettle();

        expect(server.calls, isNot(contains('DELETE /api/gifts/$scarf')));
        expect(cardTitles(tester), ['Scarf']);
      });

      testWidgets('dismiss, confirmed, deletes it and reloads',
          (tester) async {
        final scarf = server.addRevealed(listId, 'Scarf');
        await startApp(tester, server, '/lists/$listId');
        final before = loads();

        await tapVisible(tester, button('Scarf', 'Dismiss'));
        await tester.tap(find.widgetWithText(TextButton, 'Dismiss').last);
        await tester.pumpAndSettle();

        expect(server.calls, contains('DELETE /api/gifts/$scarf'));
        expect(loads(), before + 1);
        expect(find.text('Gifts from your occasions'), findsNothing);
        expect(find.byType(GiftCard), findsNothing);
      });

      testWidgets('Received: collapsed with its count, newest first',
          (tester) async {
        server.addGift(listId, 'Book');
        final pen = server.addGift(listId, 'Pen');
        final scarf = server.addRevealed(listId, 'Scarf');
        server
          ..markReceived(pen)
          ..markReceived(scarf);
        await startApp(tester, server, '/lists/$listId');

        expect(find.text('Received (2)'), findsOneWidget);
        expect(cardTitles(tester), ['Book']);

        await openReceived(tester);

        expect(cardTitles(tester), ['Book', 'Scarf', 'Pen']);
        expect(button('Pen', 'Put back'), findsOneWidget);
        expect(button('Pen', 'Delete'), findsOneWidget);
        expect(
          tester.widget<GiftCard>(find.widgetWithText(GiftCard, 'Pen')).onTap,
          isNull,
        );
        expectNothingRose(tester);
      });

      testWidgets('put back: the gift is back in its place, reloaded',
          (tester) async {
        server.addGift(listId, 'Book');
        final pen = server.addGift(listId, 'Pen');
        server.addGift(listId, 'Socks');
        server.markReceived(pen);
        await startApp(tester, server, '/lists/$listId');
        await openReceived(tester);
        final before = loads();

        await tapVisible(tester, button('Pen', 'Put back'));

        expect(server.calls, contains('DELETE /api/gifts/$pen/received'));
        expect(loads(), before + 1);
        expect(find.textContaining('Received ('), findsNothing);
        expect(cardTitles(tester), ['Book', 'Pen', 'Socks']);
      });

      testWidgets('put back answered not_revealed says when, keeps it under '
          'Received and reloads (review R2-1)', (tester) async {
        final scarf = server.addRevealed(listId, 'Scarf');
        server
          ..markReceived(scarf)
          ..notRevealed.add(scarf);
        await startApp(tester, server, '/lists/$listId');
        await openReceived(tester);
        final before = loads();

        await tapVisible(tester, button('Scarf', 'Put back'));

        expect(server.calls, contains('DELETE /api/gifts/$scarf/received'));
        expect(
          find.text(
            'This gift can be put back once its occasion has passed again.',
          ),
          findsOneWidget,
        );
        expect(loads(), before + 1);
        expect(find.text('Received (1)'), findsOneWidget);
        expect(button('Scarf', 'Put back'), findsOneWidget);
      });

      testWidgets('deleting a received gift asks first, then reloads',
          (tester) async {
        final pen = server.addGift(listId, 'Pen');
        server.markReceived(pen);
        await startApp(tester, server, '/lists/$listId');
        await openReceived(tester);

        await tapVisible(tester, button('Pen', 'Delete'));
        expect(find.text('Delete this gift?'), findsOneWidget);
        await tester.tap(find.text('Cancel'));
        await tester.pumpAndSettle();
        expect(server.calls, isNot(contains('DELETE /api/gifts/$pen')));

        final before = loads();
        await tapVisible(tester, button('Pen', 'Delete'));
        await tester.tap(find.widgetWithText(TextButton, 'Delete').last);
        await tester.pumpAndSettle();

        expect(server.calls, contains('DELETE /api/gifts/$pen'));
        expect(loads(), before + 1);
        expect(find.textContaining('Received ('), findsNothing);
      });
    });
  }

  testWidgets('a failed action says so and reloads', (tester) async {
    final listId = server.addList('Birthday');
    final scarf = server.addRevealed(listId, 'Scarf');
    server.status['POST /api/gifts/$scarf/keep'] = 500;
    await startApp(tester, server, '/lists/$listId');

    await tapVisible(tester, button('Scarf', 'Keep on my list'));

    expect(
      find.text('Your changes could not be saved. Try again.'),
      findsOneWidget,
    );
    expect(cardTitles(tester), ['Scarf']);
  });

  testWidgets('a gift gone meanwhile says so; dismissing it is done',
      (tester) async {
    final listId = server.addList('Birthday');
    final scarf = server.addRevealed(listId, 'Scarf');
    final gloves = server.addRevealed(listId, 'Gloves');
    await startApp(tester, server, '/lists/$listId');
    // Hidden again (its occasion's date moved later): the random id's 404.
    server.status['POST /api/gifts/$scarf/received'] = 404;
    server.status['DELETE /api/gifts/$gloves'] = 404;

    await tapVisible(tester, button('Scarf', 'Received'));
    expect(find.text('This gift no longer exists.'), findsOneWidget);

    ScaffoldMessenger.of(tester.element(find.byType(GiftCard).first))
        .removeCurrentSnackBar();
    await tester.pumpAndSettle();
    await tapVisible(tester, button('Gloves', 'Dismiss'));
    await tester.tap(find.widgetWithText(TextButton, 'Dismiss').last);
    await tester.pumpAndSettle();
    expect(find.text('This gift no longer exists.'), findsNothing);
    expect(find.text('It could not be deleted. Try again.'), findsNothing);
  });

  testWidgets('in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    final listId = server.addList('Anniversaire');
    server.addRevealed(listId, 'Écharpe');
    server.markReceived(server.addGift(listId, 'Livre'));
    await startApp(tester, server, '/lists/$listId');

    expect(find.text('Cadeaux de vos occasions'), findsOneWidget);
    for (final label in ['Reçu', 'Garder sur ma liste', 'Écarter']) {
      expect(button('Écharpe', label), findsOneWidget);
    }
    await tapVisible(tester, find.text('Reçus (1)'));
    expect(button('Livre', 'Remettre sur la liste'), findsOneWidget);
    expect(button('Livre', 'Supprimer'), findsOneWidget);

    await tapVisible(tester, button('Écharpe', 'Écarter'));
    expect(find.text('Écarter ce cadeau ?'), findsOneWidget);
  });
}
