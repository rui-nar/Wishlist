import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/api/api_image.dart';
import 'package:shushgift/src/billing/billing_repository.dart';
import 'package:shushgift/src/billing/plan_screen.dart';
import 'package:shushgift/src/design/widgets/gift_card.dart';
import 'package:shushgift/src/lists/gift_form_screen.dart';
import 'package:shushgift/src/lists/list_detail_screen.dart';
import 'package:shushgift/src/lists/list_form_screen.dart';

import 'support/fake_lists_server.dart';

/// The free plan's limit, as its owner meets it on the four paths that grow
/// a list (PREMIUM_PLAN D4, D6, D18).
void main() {
  const newList = 'POST /api/lists';
  const title = 'Free plan limit reached';
  const giftsBody = 'The free plan includes 20 gifts per list. '
      'The gifts on this list stay as they are.';
  const genericFailure = 'Your changes could not be saved. Try again.';

  late FakeListsServer server;
  late String listId;

  String addGift() => 'POST /api/lists/$listId/gifts';

  setUp(() {
    server = FakeListsServer();
    listId = server.addList('Birthday');
  });

  void onTheWeb() {
    debugOnTheWeb = true;
    addTearDown(() => debugOnTheWeb = null);
  }

  Finder inDialog(String label) => find.descendant(
        of: find.byType(AlertDialog),
        matching: find.text(label),
      );

  String field(WidgetTester tester, String label) =>
      tester.widget<TextFormField>(fieldLabelled(label)).controller!.text;

  Future<void> tapVisible(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  Future<void> type(WidgetTester tester, String label, String text) async {
    await tester.ensureVisible(fieldLabelled(label));
    await tester.pumpAndSettle();
    await tester.enterText(fieldLabelled(label), text);
  }

  Finder saveButton(String label) => find.widgetWithText(FilledButton, label);

  bool enabled(WidgetTester tester, String label) =>
      tester.widget<FilledButton>(saveButton(label)).onPressed != null;

  Finder giftButton(String gift, String label) => find.descendant(
        of: find.widgetWithText(GiftCard, gift),
        matching: find.widgetWithText(TextButton, label),
      );

  /// The form for a new list for Léa, filled in and saved.
  Future<void> createListForLea(WidgetTester tester) async {
    await startApp(tester, server, '/lists/new');
    await tester.enterText(fieldLabelled('List title'), 'Christmas');
    await tester.tap(find.text('For someone else'));
    await tester.pumpAndSettle();
    await tester.enterText(fieldLabelled('Their name'), 'Léa');
    await tester.tap(find.text('Create'));
    await tester.pumpAndSettle();
  }

  void expectListFormFilled(WidgetTester tester) {
    expect(find.byType(ListFormScreen), findsOneWidget);
    expect(field(tester, 'List title'), 'Christmas');
    expect(field(tester, 'Their name'), 'Léa');
  }

  group('creating a list', () {
    testWidgets('names the limit and keeps the form; retrying sends the same',
        (tester) async {
      server.refuseAtLimit(newList, 'lists', 1);
      await createListForLea(tester);

      expect(inDialog(title), findsOneWidget);
      expect(
        inDialog('The free plan includes 1 list. Your lists stay as they are.'),
        findsOneWidget,
      );
      // The form is there, under the dialog.
      expectListFormFilled(tester);

      await tester.tap(inDialog('Not now'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expectListFormFilled(tester);
      expect(find.byType(ListDetailScreen), findsNothing);
      expect(find.text(genericFailure), findsNothing);
      expect(enabled(tester, 'Create'), isTrue);

      server.allowGrowth(newList);
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(server.bodies[newList], {
        'title': 'Christmas',
        'recipient_kind': 'other',
        'recipient_name': 'Léa',
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('a limit above one is said in the plural', (tester) async {
      server.refuseAtLimit(newList, 'lists', 3);
      await createListForLea(tester);

      expect(
        inDialog(
          'The free plan includes 3 lists. Your lists stay as they are.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('a 402 without our code is the generic failure',
        (tester) async {
      server.status[newList] = 402;
      await createListForLea(tester);

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsOneWidget);
      expectListFormFilled(tester);
    });
  });

  group('adding a gift', () {
    /// The add form filled in, a pending image included, and saved.
    Future<void> addFilledGift(WidgetTester tester) async {
      installFakeImagePicker(kTestImage);
      await startApp(tester, server, '/lists/$listId/gifts/new');
      await tapVisible(tester, find.text('Choose image'));
      await type(tester, 'What is it?', 'Headphones');
      await type(tester, 'Details (size, colour, model...)', 'Black');
      await type(tester, 'Price (indicative)', '149,90');
      await type(tester, 'Link 1', 'https://shop.example/h');
      await tapVisible(tester, saveButton('Add a gift'));
    }

    void expectGiftFormFilled(WidgetTester tester) {
      expect(find.byType(GiftFormScreen), findsOneWidget);
      expect(field(tester, 'What is it?'), 'Headphones');
      expect(field(tester, 'Details (size, colour, model...)'), 'Black');
      expect(field(tester, 'Price (indicative)'), '149,90');
      expect(field(tester, 'Link 1'), 'https://shop.example/h');
      final preview = find.byKey(const ValueKey('gift-image-preview'));
      expect(
        (tester.widget<Image>(preview).image as ApiImage).path,
        '/api/images/${server.images.keys.single}/full',
      );
    }

    testWidgets('names the limit and keeps the form, its pending image too',
        (tester) async {
      server.refuseAtLimit(addGift(), 'gifts', 20);
      await addFilledGift(tester);

      expect(inDialog(title), findsOneWidget);
      expect(inDialog(giftsBody), findsOneWidget);
      expectGiftFormFilled(tester);

      await tester.tap(inDialog('Not now'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expectGiftFormFilled(tester);
      expect(find.byType(ListDetailScreen), findsNothing);
      expect(enabled(tester, 'Add a gift'), isTrue);

      server.allowGrowth(addGift());
      await tapVisible(tester, saveButton('Add a gift'));

      expect(server.bodies[addGift()], {
        'title': 'Headphones',
        'description': 'Black',
        'links': ['https://shop.example/h'],
        'price_amount': '149.90',
        'price_currency': 'EUR',
        'image_id': server.images.keys.single,
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('See Premium opens the plan; back finds the form as it was',
        (tester) async {
      onTheWeb();
      server.refuseAtLimit(addGift(), 'gifts', 20);
      await addFilledGift(tester);

      await tester.tap(inDialog('See Premium'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(PlanScreen), findsOneWidget);

      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      expect(find.byType(PlanScreen), findsNothing);
      expectGiftFormFilled(tester);
      expect(enabled(tester, 'Add a gift'), isTrue);
    });

    testWidgets('a 402 without our code is the generic failure',
        (tester) async {
      server.status[addGift()] = 402;
      server.answers[addGift()] = {'detail': 'Pay', 'code': 'other'};
      await addFilledGift(tester);

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsOneWidget);
      expectGiftFormFilled(tester);
    });
  });

  group('keeping a revealed gift', () {
    late String scarf;

    String keep() => 'POST /api/gifts/$scarf/keep';

    setUp(() => scarf = server.addRevealed(listId, 'Scarf'));

    testWidgets('names the limit; the gift stays revealed', (tester) async {
      server.refuseAtLimit(keep(), 'gifts', 20);
      await startApp(tester, server, '/lists/$listId');
      int loads() =>
          server.calls.where((call) => call == 'GET /api/lists/$listId').length;
      final before = loads();

      await tapVisible(tester, giftButton('Scarf', 'Keep on my list'));

      expect(inDialog(title), findsOneWidget);
      expect(inDialog(giftsBody), findsOneWidget);

      await tester.tap(inDialog('Not now'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsNothing);
      expect(find.text('Gifts from your occasions'), findsOneWidget);
      expect(giftButton('Scarf', 'Keep on my list'), findsOneWidget);
      expect(
        tester
            .widget<TextButton>(giftButton('Scarf', 'Keep on my list'))
            .onPressed,
        isNotNull,
      );
      expect(loads(), before + 1);
    });

    testWidgets('See Premium opens the plan', (tester) async {
      onTheWeb();
      server.refuseAtLimit(keep(), 'gifts', 20);
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, giftButton('Scarf', 'Keep on my list'));
      await tester.tap(inDialog('See Premium'));
      await tester.pumpAndSettle();

      expect(find.byType(PlanScreen), findsOneWidget);
    });

    testWidgets('a 402 without our code is the generic failure',
        (tester) async {
      server.status[keep()] = 402;
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, giftButton('Scarf', 'Keep on my list'));

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsOneWidget);
    });
  });

  group('putting a received gift back', () {
    late String pen;

    String putBack() => 'DELETE /api/gifts/$pen/received';

    setUp(() {
      pen = server.addGift(listId, 'Pen');
      server.markReceived(pen);
    });

    Future<void> tapPutBack(WidgetTester tester) async {
      await startApp(tester, server, '/lists/$listId');
      await tapVisible(tester, find.text('Received (1)'));
      await tapVisible(tester, giftButton('Pen', 'Put back'));
    }

    testWidgets('names the limit; the gift stays received', (tester) async {
      server.refuseAtLimit(putBack(), 'gifts', 20);
      await tapPutBack(tester);

      expect(inDialog(title), findsOneWidget);
      expect(inDialog(giftsBody), findsOneWidget);

      await tester.tap(inDialog('Not now'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsNothing);
      expect(find.text('Received (1)'), findsOneWidget);
      expect(giftButton('Pen', 'Put back'), findsOneWidget);
    });

    testWidgets('a 402 without our code is the generic failure',
        (tester) async {
      server.status[putBack()] = 402;
      await tapPutBack(tester);

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsOneWidget);
    });
  });

  testWidgets('in the iOS app, See Premium is offered (Apple IAP plan D8)',
      (tester) async {
    debugOnIos = true;
    addTearDown(() => debugOnIos = null);
    server.refuseAtLimit(newList, 'lists', 1);
    await createListForLea(tester);

    expect(inDialog('See Premium'), findsOneWidget);
  });

  testWidgets('See Premium is on the web and iOS only; the message is '
      'everywhere',
      (tester) async {
    server.refuseAtLimit(newList, 'lists', 1);
    await createListForLea(tester);

    expect(inDialog(title), findsOneWidget);
    expect(inDialog('Not now'), findsOneWidget);
    expect(inDialog('See Premium'), findsNothing);
  });

  testWidgets('on the web, See Premium is offered', (tester) async {
    onTheWeb();
    server.refuseAtLimit(newList, 'lists', 1);
    await createListForLea(tester);

    expect(inDialog('Not now'), findsOneWidget);
    expect(inDialog('See Premium'), findsOneWidget);
  });

  testWidgets('See Premium from the list form; back finds it as it was',
      (tester) async {
    onTheWeb();
    server.refuseAtLimit(newList, 'lists', 1);
    await createListForLea(tester);

    await tester.tap(inDialog('See Premium'));
    await tester.pumpAndSettle();
    expect(find.byType(PlanScreen), findsOneWidget);

    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    expectListFormFilled(tester);
    expect(enabled(tester, 'Create'), isTrue);
  });

  group('the hidden-gift form never meets the limit', () {
    testWidgets('even answered plan_limit, it is the generic failure',
        (tester) async {
      onTheWeb();
      final list = server.addList(
        'Christmas',
        recipientName: 'Léa',
        ownerNames: ['Bob Durand'],
      );
      final occasion = server.addOccasion(
        list,
        'Christmas 2026',
        '2026-12-24',
        invitees: ['Carol'],
      );
      server.joined.add(occasion);
      final add = 'POST /api/occasions/$occasion/hidden-gifts';
      server.refuseAtLimit(add, 'gifts', 20);
      await startApp(tester, server, '/shared/$occasion/hidden/new');

      await type(tester, 'What is it?', 'Weekend away');
      await tapVisible(tester, saveButton('Add a hidden gift'));

      expect(server.calls, contains(add));
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text(genericFailure), findsOneWidget);
      expect(field(tester, 'What is it?'), 'Weekend away');
    });
  });

  group('in French', () {
    void french(WidgetTester tester) {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    }

    testWidgets('the limit on lists', (tester) async {
      french(tester);
      onTheWeb();
      server.refuseAtLimit(newList, 'lists', 1);
      await startApp(tester, server, '/lists/new');

      await tester.enterText(fieldLabelled('Titre de la liste'), 'Noël');
      await tester.tap(find.text('Créer'));
      await tester.pumpAndSettle();

      expect(
        inDialog('Limite de la formule gratuite atteinte'),
        findsOneWidget,
      );
      expect(
        inDialog(
          'La formule gratuite comprend 1 liste. '
          'Vos listes restent telles quelles.',
        ),
        findsOneWidget,
      );
      expect(inDialog('Pas maintenant'), findsOneWidget);
      expect(inDialog('Découvrir Premium'), findsOneWidget);
    });

    testWidgets('the limit on gifts', (tester) async {
      french(tester);
      final scarf = server.addRevealed(listId, 'Écharpe');
      server.refuseAtLimit('POST /api/gifts/$scarf/keep', 'gifts', 20);
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, giftButton('Écharpe', 'Garder sur ma liste'));

      expect(
        inDialog(
          'La formule gratuite comprend 20 cadeaux par liste. '
          'Les cadeaux de cette liste restent tels quels.',
        ),
        findsOneWidget,
      );
      expect(inDialog('Découvrir Premium'), findsNothing);
    });
  });
}
