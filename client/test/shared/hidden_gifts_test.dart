import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/api/api_image.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/status_chip.dart';
import 'package:wishlist/src/lists/gift_form_screen.dart';
import 'package:wishlist/src/lists/gift_image_section.dart';
import 'package:wishlist/src/shared/occasion_screen.dart';

import '../lists/support/fake_lists_server.dart';

/// Hidden gifts for an occasion's givers: the section, the sheet and the
/// form in its hidden mode (HIDDEN_GIFTS_PLAN D7, D8, D14).
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
    server.addGift(list, 'Book');
    occasion = server.addOccasion(
      list,
      'Christmas 2026',
      '2026-12-24',
      invitees: ['Carol'],
    );
    server.joined.add(occasion);
  });

  String hiddenPath() => '/api/occasions/$occasion/hidden-gifts';

  /// The rose chips of the gift titled [title].
  List<String> roseChips(WidgetTester tester, String title) => [
        for (final chip in tester
            .widget<GiftCard>(find.widgetWithText(GiftCard, title))
            .chips
            .whereType<StatusChip>())
          if (chip.variant == StatusChipVariant.inviteeActivity) chip.label,
      ];

  Future<void> tapVisible(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  Future<void> openSheet(WidgetTester tester, String title) =>
      tapVisible(tester, find.widgetWithText(GiftCard, title));

  Finder inSheet(String label) => find.descendant(
        of: find.byType(BottomSheet),
        matching: find.text(label),
      );

  Finder inDialog(String label) => find.descendant(
        of: find.byType(AlertDialog),
        matching: find.text(label),
      );

  final addButton = find.widgetWithText(OutlinedButton, 'Add a hidden gift');

  /// The form's save button, labelled [label].
  Future<void> save(WidgetTester tester, String label) => tapVisible(
        tester,
        find.widgetWithText(FilledButton, label),
      );

  Future<void> type(WidgetTester tester, String label, String text) async {
    await tester.ensureVisible(fieldLabelled(label));
    await tester.pumpAndSettle();
    await tester.enterText(fieldLabelled(label), text);
  }

  group('the section', () {
    testWidgets('below the gifts: heading, explanation, who added each',
        (tester) async {
      tester.view.physicalSize = const Size(800, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      server
        ..addHidden(occasion, 'Mine', author: kAliceName, mine: true)
        ..addHidden(occasion, 'Carols', author: 'Carol')
        ..addHidden(occasion, 'Orphan')
        ..addHidden(occasion, 'Unnamed', author: '  ');
      await startApp(tester, server, '/shared/$occasion');

      expect(find.text('Hidden gifts'), findsOneWidget);
      expect(
        find.text(
          'Only the people giving for this occasion see these. '
          'Léa will see the ones bought, once the occasion has passed.',
        ),
        findsOneWidget,
      );
      expect(roseChips(tester, 'Mine'), ['Added by you']);
      expect(roseChips(tester, 'Carols'), ['Added by Carol']);
      // The author's account is deleted: no name, no chip.
      expect(roseChips(tester, 'Orphan'), isEmpty);
      expect(roseChips(tester, 'Unnamed'), ['Added by Unnamed person']);
      // Below the list's gifts, oldest first.
      expect(
        [
          for (final card
              in tester.widgetList<GiftCard>(find.byType(GiftCard)))
            card.title,
        ],
        ['Book', 'Mine', 'Carols', 'Orphan', 'Unnamed'],
      );
      expect(server.calls, contains('GET ${hiddenPath()}'));
    });

    testWidgets('a claim on it shows next to who added it, and reserving goes '
        'through the claim routes', (tester) async {
      final carols = server.addHidden(occasion, 'Carols', author: 'Carol');
      final dans = server.addHidden(occasion, 'Dans', author: 'Dan');
      server.addClaim(dans, occasion, [FakeListsServer.giver('Carol')]);
      await startApp(tester, server, '/shared/$occasion');

      expect(roseChips(tester, 'Dans'), ['Added by Dan', 'Reserved by Carol']);

      await openSheet(tester, 'Carols');
      await tester.tap(inSheet('Reserve'));
      await tester.pumpAndSettle();

      expect(
        server.calls,
        contains('POST /api/occasions/$occasion/gifts/$carols/reservation'),
      );
      expect(roseChips(tester, 'Carols'), ['Added by Carol', 'Reserved by you']);
    });

    testWidgets('Add a hidden gift opens the form, and the gift shows after',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');

      await tapVisible(tester, addButton);
      expect(find.byType(GiftFormScreen), findsOneWidget);

      await type(tester, 'What is it?', 'Weekend away');
      await save(tester, 'Add a hidden gift');

      expect(server.calls, contains('POST ${hiddenPath()}'));
      expect(server.bodies['POST ${hiddenPath()}'], {
        'title': 'Weekend away',
        'description': '',
        'links': <String>[],
        'price_amount': null,
        'price_currency': null,
      });
      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(roseChips(tester, 'Weekend away'), ['Added by you']);
    });

    testWidgets('once passed: no Add, the gifts are still shown',
        (tester) async {
      server
        ..passed.add(occasion)
        ..addHidden(occasion, 'Mine', author: kAliceName, mine: true);
      await startApp(tester, server, '/shared/$occasion');

      expect(addButton, findsNothing);
      expect(find.text('Hidden gifts'), findsOneWidget);
      expect(find.widgetWithText(GiftCard, 'Mine'), findsOneWidget);
    });

    testWidgets('once passed with none: no section at all', (tester) async {
      server.passed.add(occasion);
      await startApp(tester, server, '/shared/$occasion');

      expect(find.text('Hidden gifts'), findsNothing);
      expect(addButton, findsNothing);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.addHidden(occasion, 'Carols', author: 'Carol');
      await startApp(tester, server, '/shared/$occasion');

      expect(find.text('Cadeaux cachés'), findsOneWidget);
      expect(
        find.text(
          'Seules les personnes qui offrent pour cette occasion les voient. '
          "Léa verra ceux qui ont été achetés, une fois l'occasion passée.",
        ),
        findsOneWidget,
      );
      expect(roseChips(tester, 'Carols'), ['Ajouté par Carol']);
      expect(
        find.widgetWithText(OutlinedButton, 'Ajouter un cadeau caché'),
        findsOneWidget,
      );
    });
  });

  group("the author's sheet", () {
    late String mine;

    setUp(() {
      mine = server.addHidden(occasion, 'Mine', author: kAliceName, mine: true);
    });

    int reads() =>
        server.calls.where((call) => call == 'GET ${hiddenPath()}').length;

    testWidgets('Edit and Delete for the author, with the claim actions',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');

      expect(inSheet('Edit gift'), findsOneWidget);
      expect(inSheet('Delete gift'), findsOneWidget);
      expect(inSheet('Reserve'), findsOneWidget);
      expect(inSheet('Added by you'), findsOneWidget);
    });

    testWidgets('nothing for another giver', (tester) async {
      server.addHidden(occasion, 'Carols', author: 'Carol');
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Carols');

      expect(inSheet('Edit gift'), findsNothing);
      expect(inSheet('Delete gift'), findsNothing);
    });

    testWidgets('nothing on a list gift', (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Book');

      expect(inSheet('Edit gift'), findsNothing);
      expect(inSheet('Delete gift'), findsNothing);
    });

    testWidgets('still there while reserved by someone else', (tester) async {
      server.addClaim(mine, occasion, [FakeListsServer.giver('Carol')]);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');

      expect(inSheet('Edit gift'), findsOneWidget);
      expect(inSheet('Delete gift'), findsOneWidget);
    });

    testWidgets('gone once bought', (tester) async {
      server.addClaim(
        mine,
        occasion,
        [FakeListsServer.giver('Carol')],
        bought: true,
      );
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');

      expect(inSheet('Edit gift'), findsNothing);
      expect(inSheet('Delete gift'), findsNothing);
    });

    testWidgets('gone once the occasion has passed', (tester) async {
      server.passed.add(occasion);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');

      expect(inSheet('Edit gift'), findsNothing);
      expect(inSheet('Delete gift'), findsNothing);
    });

    testWidgets('Edit opens the form with the gift, and saving comes back',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');
      await tester.tap(inSheet('Edit gift'));
      await tester.pumpAndSettle();

      expect(find.byType(GiftFormScreen), findsOneWidget);
      expect(find.text('Mine'), findsOneWidget);
      await type(tester, 'What is it?', 'Mine, better');
      await save(tester, 'Save');

      expect(
        server.calls,
        contains('PATCH ${hiddenPath()}/$mine'),
      );
      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(find.widgetWithText(GiftCard, 'Mine, better'), findsOneWidget);
    });

    testWidgets('Delete is confirmed, then the page loads again',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      final before = reads();
      await openSheet(tester, 'Mine');
      await tester.tap(inSheet('Delete gift'));
      await tester.pumpAndSettle();

      expect(server.calls, isNot(contains('DELETE ${hiddenPath()}/$mine')));
      await tester.tap(inDialog('Delete'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('DELETE ${hiddenPath()}/$mine'));
      expect(find.widgetWithText(GiftCard, 'Mine'), findsNothing);
      expect(reads(), before + 1);
    });

    testWidgets('Delete cancelled changes nothing', (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Mine');
      await tester.tap(inSheet('Delete gift'));
      await tester.pumpAndSettle();
      await tester.tap(inDialog('Cancel'));
      await tester.pumpAndSettle();

      expect(server.calls, isNot(contains('DELETE ${hiddenPath()}/$mine')));
      expect(find.widgetWithText(GiftCard, 'Mine'), findsOneWidget);
    });

    testWidgets('bought meanwhile: Delete says so and loads the page again',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');
      final before = reads();
      await openSheet(tester, 'Mine');
      server.addClaim(
        mine,
        occasion,
        [FakeListsServer.giver('Carol')],
        bought: true,
      );
      await tester.tap(inSheet('Delete gift'));
      await tester.pumpAndSettle();
      await tester.tap(inDialog('Delete'));
      await tester.pumpAndSettle();

      expect(
        find.text('This gift has been bought: it can no longer be changed.'),
        findsOneWidget,
      );
      expect(reads(), before + 1);
      expect(find.widgetWithText(GiftCard, 'Mine'), findsOneWidget);
    });
  });

  group('the form, hidden mode', () {
    String? previewPath(WidgetTester tester) {
      final preview = find.byKey(const ValueKey('gift-image-preview'));
      if (preview.evaluate().isEmpty) return null;
      return (tester.widget<Image>(preview).image as ApiImage).path;
    }

    Future<void> tapText(WidgetTester tester, String text) =>
        tapVisible(tester, find.text(text));

    String addCall() => 'POST ${hiddenPath()}';

    testWidgets('every property, sent to the hidden route', (tester) async {
      await startApp(tester, server, '/shared/$occasion/hidden/new');

      await type(tester, 'What is it?', 'Weekend away');
      await type(tester, 'Details (size, colour, model...)', 'Near the sea');
      await type(tester, 'Link 1', 'https://shop.example/w');
      await type(tester, 'Price (indicative)', '199.50');
      await save(tester, 'Add a hidden gift');

      expect(server.bodies[addCall()], {
        'title': 'Weekend away',
        'description': 'Near the sea',
        'links': ['https://shop.example/w'],
        'price_amount': '199.50',
        'price_currency': 'EUR',
      });
      expect(server.calls, isNot(contains('POST /api/lists/$list/gifts')));
    });

    testWidgets('adds with an uploaded image', (tester) async {
      installFakeImagePicker(kTestImage);
      await startApp(tester, server, '/shared/$occasion/hidden/new');

      await tapText(tester, 'Choose image');
      expect(server.uploads, hasLength(1));
      await type(tester, 'What is it?', 'Weekend away');
      await save(tester, 'Add a hidden gift');

      expect(
        server.bodies[addCall()]!['image_id'],
        server.images.keys.single,
      );
    });

    testWidgets('adds with an image from a URL', (tester) async {
      await startApp(tester, server, '/shared/$occasion/hidden/new');

      await tapText(tester, 'Image URL');
      await tester.enterText(
        fieldLabelled('Image address'),
        'https://shop.example/w.png',
      );
      await tester.tap(find.text('Use this image'));
      await tester.pumpAndSettle();
      expect(server.calls, contains('POST /api/images/from-url'));
      await type(tester, 'What is it?', 'Weekend away');
      await save(tester, 'Add a hidden gift');

      expect(
        server.bodies[addCall()]!['image_id'],
        server.images.keys.single,
      );
    });

    testWidgets('adds with a pasted image', (tester) async {
      await startApp(tester, server, '/shared/$occasion/hidden/new');

      final section = tester.state<GiftImageSectionState>(
        find.byType(GiftImageSection),
      );
      final pasted = Uint8List.fromList([...kTestImage]);
      expect(
        section.handlePaste([
          PastedFile(type: 'image/png', read: () async => pasted),
        ]),
        isTrue,
      );
      await tester.pumpAndSettle();
      expect(server.uploads.single, pasted);
      await type(tester, 'What is it?', 'Weekend away');
      await save(tester, 'Add a hidden gift');

      expect(
        server.bodies[addCall()]!['image_id'],
        server.images.keys.single,
      );
    });

    testWidgets('once passed, adding says so and goes back', (tester) async {
      await startApp(tester, server, '/shared/$occasion/hidden/new');
      server.passed.add(occasion);

      await type(tester, 'What is it?', 'Weekend away');
      await save(tester, 'Add a hidden gift');

      expect(
        find.text('This occasion has passed: nothing can be changed any more.'),
        findsOneWidget,
      );
      expect(find.byType(OccasionScreen), findsOneWidget);
    });

    group('editing', () {
      late String mine;

      setUp(() {
        mine = server.addHidden(
          occasion,
          'Mine',
          author: kAliceName,
          mine: true,
          description: 'Blue',
          links: ['https://shop.example/m'],
          priceAmount: '20.00',
          priceCurrency: 'EUR',
          image: true,
        );
      });

      String edit() => '/shared/$occasion/hidden/$mine/edit';

      testWidgets('loads the gift, with its image; no Mark as received',
          (tester) async {
        await startApp(tester, server, edit());
        await loadImages(tester);

        expect(fieldLabelled('What is it?'), findsOneWidget);
        expect(find.text('Mine'), findsOneWidget);
        expect(find.text('Blue'), findsOneWidget);
        expect(find.text('20.00'), findsOneWidget);
        expect(previewPath(tester), startsWith('/api/occasions/$occasion/'));
        expect(find.text('Mark as received'), findsNothing);
        expect(find.text('Delete gift'), findsOneWidget);
      });

      testWidgets('saves through the hidden route', (tester) async {
        await startApp(tester, server, edit());

        await type(tester, 'What is it?', 'Mine, better');
        await save(tester, 'Save');

        expect(
          server.bodies['PATCH ${hiddenPath()}/$mine']!['title'],
          'Mine, better',
        );
        expect(find.byType(OccasionScreen), findsOneWidget);
      });

      testWidgets('deletes through the hidden route, confirmed', (tester) async {
        await startApp(tester, server, edit());

        await tapVisible(tester, find.text('Delete gift'));
        await tester.tap(inDialog('Delete'));
        await tester.pumpAndSettle();

        expect(server.calls, contains('DELETE ${hiddenPath()}/$mine'));
        expect(find.byType(OccasionScreen), findsOneWidget);
      });

      testWidgets('bought meanwhile: says it can no longer be changed',
          (tester) async {
        await startApp(tester, server, edit());
        server.addClaim(
          mine,
          occasion,
          [FakeListsServer.giver('Carol')],
          bought: true,
        );

        await type(tester, 'What is it?', 'Mine, better');
        await save(tester, 'Save');

        expect(
          find.text('This gift has been bought: it can no longer be changed.'),
          findsOneWidget,
        );
        expect(find.byType(OccasionScreen), findsOneWidget);
      });

      testWidgets("someone else's gift is not theirs to edit", (tester) async {
        final carols = server.addHidden(occasion, 'Carols', author: 'Carol');
        await startApp(tester, server, '/shared/$occasion/hidden/$carols/edit');

        expect(find.text('This gift no longer exists.'), findsOneWidget);
        await tapVisible(tester, find.text('Back to the occasion'));
        expect(find.byType(OccasionScreen), findsOneWidget);
      });
    });
  });
}
