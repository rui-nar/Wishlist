import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:wishlist/l10n/app_localizations.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/shared/gift_thread.dart';

import '../lists/support/fake_lists_server.dart';

/// The comment thread and follow toggle of a gift's sheet
/// (COMMENTS_NOTIFICATIONS_PLAN D2, D3, D20).
void main() {
  late FakeListsServer server;
  late String list;
  late String occasion;
  late String gift;
  late String comments;

  setUp(() {
    server = FakeListsServer();
    list = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    gift = server.addGift(list, 'Headphones');
    occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
    server.joined.add(occasion);
    comments = 'occasions/$occasion/gifts/$gift/comments';
  });

  String commentsCall(String method) => '$method /api/$comments';

  String followCall(String method) =>
      '$method /api/occasions/$occasion/gifts/$gift/follow';

  int threadReads() =>
      server.calls.where((call) => call == commentsCall('GET')).length;

  Future<void> tall(WidgetTester tester) async {
    tester.view.physicalSize = const Size(800, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
  }

  Future<void> openSheet(WidgetTester tester) async {
    await tall(tester);
    await startApp(tester, server, '/shared/$occasion');
    await tester.tap(find.widgetWithText(GiftCard, 'Headphones'));
    await tester.pumpAndSettle();
  }

  Future<void> tapText(WidgetTester tester, String label) async {
    await tester.tap(find.text(label).first);
    await tester.pumpAndSettle();
  }

  Future<void> tapInDialog(WidgetTester tester, String label) async {
    await tester.tap(
      find.descendant(of: find.byType(AlertDialog), matching: find.text(label)),
    );
    await tester.pumpAndSettle();
  }

  Finder sheetField() => find
      .descendant(of: find.byType(BottomSheet), matching: find.byType(TextField))
      .last;

  Future<void> write(WidgetTester tester, String text) async {
    await tester.enterText(sheetField(), text);
    await tester.pump();
  }

  TextButton button(WidgetTester tester, String label) =>
      tester.widget<TextButton>(find.widgetWithText(TextButton, label));

  /// A snack bar shown over the sheet, not behind it.
  Finder sheetSnackBar(String message) => find.descendant(
        of: find.byType(BottomSheet),
        matching: find.widgetWithText(SnackBar, message),
      );

  const serverError = 'The server could not complete the request. Try again.';

  group('reading', () {
    testWidgets('loads when the sheet opens, oldest first, with each author',
        (tester) async {
      server
        ..addComment(occasion, gift, 'First', author: 'Carol')
        ..addComment(occasion, gift, 'Second', mine: true)
        ..addComment(occasion, gift, 'Third');
      await tall(tester);
      await startApp(tester, server, '/shared/$occasion');
      expect(threadReads(), 0);
      await tester.tap(find.widgetWithText(GiftCard, 'Headphones'));
      await tester.pumpAndSettle();

      expect(threadReads(), 1);
      expect(find.text('Comments'), findsOneWidget);
      expect(find.text('Carol'), findsOneWidget);
      expect(find.text('You'), findsOneWidget);
      expect(find.text('Deleted user'), findsOneWidget);
      final first = tester.getTopLeft(find.text('First')).dy;
      final second = tester.getTopLeft(find.text('Second')).dy;
      final third = tester.getTopLeft(find.text('Third')).dy;
      expect(first, lessThan(second));
      expect(second, lessThan(third));
      expect(find.byType(SelectableText), findsNWidgets(3));
    });

    testWidgets('"edited" only on an edited comment', (tester) async {
      server
        ..addComment(occasion, gift, 'Changed', author: 'Carol', edited: true)
        ..addComment(occasion, gift, 'As written', author: 'Dan');
      await openSheet(tester);

      expect(find.textContaining('· edited'), findsOneWidget);
    });

    testWidgets('Edit and Delete only on my own comments', (tester) async {
      server
        ..addComment(occasion, gift, 'Carol wrote', author: 'Carol')
        ..addComment(occasion, gift, 'Nobody now');
      await openSheet(tester);

      expect(find.text('Edit'), findsNothing);
      expect(find.text('Delete'), findsNothing);
    });

    testWidgets('an empty thread says so', (tester) async {
      await openSheet(tester);

      expect(
        find.text(
          'No comments yet. Only the people giving for this occasion can '
          'read them.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('a hidden gift has a thread of its own', (tester) async {
      final hidden = server.addHidden(occasion, 'Skates', author: 'Carol');
      server.addComment(occasion, hidden, 'Size 39', author: 'Dan');
      await tall(tester);
      await startApp(tester, server, '/shared/$occasion');
      await tester.tap(find.widgetWithText(GiftCard, 'Skates'));
      await tester.pumpAndSettle();

      expect(find.text('Size 39'), findsOneWidget);
    });

  });

  group('writing', () {
    testWidgets('posting sends the trimmed text, clears the field and reloads',
        (tester) async {
      await openSheet(tester);
      final reads = threadReads();
      await write(tester, '  Should I take the blue one?\n');
      await tapText(tester, 'Send');

      expect(server.bodies[commentsCall('POST')], {
        'body': 'Should I take the blue one?',
      });
      expect(threadReads(), reads + 1);
      expect(find.text('Should I take the blue one?'), findsOneWidget);
      expect(tester.widget<TextField>(sheetField()).controller!.text, isEmpty);
      // Posting follows (D4), and the server's answer shows it.
      expect(find.text('Following'), findsOneWidget);
    });

    testWidgets('line endings are sent as line feeds and counted as one',
        (tester) async {
      await openSheet(tester);
      await write(tester, 'a\r\nb\rc');

      expect(find.text('5 / 2000'), findsOneWidget);
      await tapText(tester, 'Send');

      expect(server.bodies[commentsCall('POST')], {'body': 'a\nb\nc'});
    });

    testWidgets('nothing to send while the text is blank', (tester) async {
      await openSheet(tester);
      expect(button(tester, 'Send').onPressed, isNull);

      await write(tester, '   \n ');

      expect(find.text('0 / 2000'), findsOneWidget);
      expect(button(tester, 'Send').onPressed, isNull);
    });

    testWidgets('the counter takes code points: 2000 goes, 2001 is refused',
        (tester) async {
      await openSheet(tester);
      final limit = '😀' * 2000;
      await write(tester, limit);

      expect(find.text('2000 / 2000'), findsOneWidget);
      expect(button(tester, 'Send').onPressed, isNotNull);
      expect(find.text('A comment can be up to 2000 characters.'), findsNothing);

      await write(tester, '$limit!');

      expect(find.text('2001 / 2000'), findsOneWidget);
      expect(find.text('A comment can be up to 2000 characters.'), findsOneWidget);
      expect(button(tester, 'Send').onPressed, isNull);
      expect(server.calls, isNot(contains(commentsCall('POST'))));

      await write(tester, limit);
      await tapText(tester, 'Send');

      expect(server.threads['$occasion/$gift']!.single['body'], limit);
    });

    testWidgets('editing starts from the text and marks it edited',
        (tester) async {
      final id = server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      final reads = threadReads();
      await tapText(tester, 'Edit');

      final fields = find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byType(TextField),
      );
      expect(fields, findsNWidgets(2));
      expect(
        tester.widget<TextField>(fields.first).controller!.text,
        'Blue one',
      );
      await tester.enterText(fields.first, ' Red one ');
      await tester.pump();
      await tapText(tester, 'Save');

      final call = 'PATCH /api/$comments/$id';
      expect(server.bodies[call], {'body': 'Red one'});
      expect(threadReads(), reads + 1);
      expect(find.text('Red one'), findsOneWidget);
      expect(find.textContaining('· edited'), findsOneWidget);
      expect(fields, findsOneWidget);
    });

    testWidgets('cancelling or saving unchanged sends nothing', (tester) async {
      server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      final calls = server.calls.length;

      await tapText(tester, 'Edit');
      await tapText(tester, 'Cancel');
      await tapText(tester, 'Edit');
      await tapText(tester, 'Save');

      expect(server.calls.length, calls);
      expect(find.textContaining('· edited'), findsNothing);
      expect(find.byType(SelectableText), findsOneWidget);
    });

    testWidgets('an edit past the limit cannot be saved', (tester) async {
      server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      await tapText(tester, 'Edit');
      await tester.enterText(
        find
            .descendant(
              of: find.byType(BottomSheet),
              matching: find.byType(TextField),
            )
            .first,
        'x' * 2001,
      );
      await tester.pump();

      expect(button(tester, 'Save').onPressed, isNull);
    });

    testWidgets('deleting asks first, then the comment is gone', (tester) async {
      final id = server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      await tapText(tester, 'Delete');

      expect(find.text('Delete this comment?'), findsOneWidget);
      await tapInDialog(tester, 'Cancel');
      expect(server.calls, isNot(contains('DELETE /api/$comments/$id')));
      expect(find.text('Blue one'), findsOneWidget);

      final reads = threadReads();
      await tapText(tester, 'Delete');
      await tapInDialog(tester, 'Delete');

      expect(server.calls, contains('DELETE /api/$comments/$id'));
      expect(threadReads(), reads + 1);
      expect(find.text('Blue one'), findsNothing);
    });

    testWidgets('one write at a time: everything waits while one is on its way',
        (tester) async {
      server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      await write(tester, 'Hello');
      server.hold = Completer();
      await tester.tap(find.text('Send'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(button(tester, 'Send').onPressed, isNull);
      expect(button(tester, 'Edit').onPressed, isNull);
      expect(button(tester, 'Delete').onPressed, isNull);
      expect(find.text('Follow'), findsOneWidget);
      expect(
        tester
            .widget<TextButton>(
              find.ancestor(
                of: find.text('Follow'),
                matching: find.byWidgetPredicate(
                  (widget) => widget is TextButton,
                ),
              ),
            )
            .onPressed,
        isNull,
      );

      server.hold!.complete();
      server.hold = null;
      await tester.pumpAndSettle();
      expect(find.text('Hello'), findsOneWidget);
    });
  });

  group('following', () {
    TextButton toggle(WidgetTester tester, String label) =>
        tester.widget<TextButton>(
          find.ancestor(
            of: find.text(label),
            matching: find.byWidgetPredicate((widget) => widget is TextButton),
          ),
        );

    testWidgets('the toggle calls the right route and shows the answer',
        (tester) async {
      await openSheet(tester);
      final reads = threadReads();
      expect(toggle(tester, 'Follow').onPressed, isNotNull);

      await tapText(tester, 'Follow');
      expect(server.calls, contains(followCall('PUT')));
      expect(threadReads(), reads + 1);
      expect(find.text('Following'), findsOneWidget);

      await tapText(tester, 'Following');
      expect(server.calls, contains(followCall('DELETE')));
      expect(threadReads(), reads + 2);
      expect(find.text('Follow'), findsOneWidget);
    });

    testWidgets('after stopping by hand, posting does not follow again',
        (tester) async {
      server.following.add('$occasion/$gift');
      await openSheet(tester);
      await tapText(tester, 'Following');
      await write(tester, 'Still here');
      await tapText(tester, 'Send');

      expect(find.text('Still here'), findsOneWidget);
      expect(find.text('Follow'), findsOneWidget);
      expect(find.text('Following'), findsNothing);
    });

    testWidgets('no toggle until the state is known', (tester) async {
      await tall(tester);
      await startApp(tester, server, '/shared/$occasion');
      server.hold = Completer();
      await tester.tap(find.widgetWithText(GiftCard, 'Headphones'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(find.text('Follow'), findsNothing);
      expect(find.text('Following'), findsNothing);
      expect(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.byType(CircularProgressIndicator),
        ),
        findsOneWidget,
      );

      server.hold!.complete();
      server.hold = null;
      await tester.pumpAndSettle();
      expect(find.text('Follow'), findsOneWidget);
    });

    testWidgets('a failure says so and changes nothing shown', (tester) async {
      server.status[followCall('PUT')] = 500;
      await openSheet(tester);
      final reads = threadReads();
      await tapText(tester, 'Follow');

      expect(sheetSnackBar(serverError), findsOneWidget);
      expect(threadReads(), reads + 1);
      expect(find.text('Follow'), findsOneWidget);
    });
  });

  group('failures', () {
    testWidgets('a post that fails keeps the text, says so over the sheet, '
        'and reloads', (tester) async {
      server.status[commentsCall('POST')] = 500;
      await openSheet(tester);
      final reads = threadReads();
      await write(tester, 'Keep me');
      await tapText(tester, 'Send');

      expect(sheetSnackBar(serverError), findsOneWidget);
      expect(threadReads(), reads + 1);
      expect(tester.widget<TextField>(sheetField()).controller!.text, 'Keep me');
    });

    testWidgets('text the server refuses says so and is kept', (tester) async {
      await openSheet(tester);
      await write(tester, 'bad\u0001text');
      await tapText(tester, 'Send');

      expect(
        sheetSnackBar(
          'This comment could not be saved. Check its text and try again.',
        ),
        findsOneWidget,
      );
      expect(
        tester.widget<TextField>(sheetField()).controller!.text,
        'bad\u0001text',
      );
    });

    testWidgets('a comment deleted meanwhile: says so and shows the thread now',
        (tester) async {
      final id = server.addComment(occasion, gift, 'Blue one', mine: true);
      await openSheet(tester);
      server.threads['$occasion/$gift']!.clear();
      await tapText(tester, 'Delete');
      await tapInDialog(tester, 'Delete');

      expect(server.calls, contains('DELETE /api/$comments/$id'));
      expect(
        sheetSnackBar(
          'That is no longer there. The comments have been refreshed.',
        ),
        findsOneWidget,
      );
      expect(find.text('Blue one'), findsNothing);
    });

    testWidgets('an edit that fails stays open with its text', (tester) async {
      final id = server.addComment(occasion, gift, 'Blue one', mine: true);
      server.status['PATCH /api/$comments/$id'] = 500;
      await openSheet(tester);
      await tapText(tester, 'Edit');
      final field = find
          .descendant(
            of: find.byType(BottomSheet),
            matching: find.byType(TextField),
          )
          .first;
      await tester.enterText(field, 'Red one');
      await tester.pump();
      await tapText(tester, 'Save');

      expect(sheetSnackBar(serverError), findsOneWidget);
      expect(find.text('Save'), findsOneWidget);
      expect(tester.widget<TextField>(field).controller!.text, 'Red one');
    });

    testWidgets('a gift gone meanwhile: the thread says it is unavailable',
        (tester) async {
      await openSheet(tester);
      await write(tester, 'Hello');
      server.gifts.remove(server.gift(gift));
      await tapText(tester, 'Send');

      expect(
        sheetSnackBar(
          'That is no longer there. The comments have been refreshed.',
        ),
        findsOneWidget,
      );
      expect(
        find.text('This conversation is no longer available.'),
        findsOneWidget,
      );
      expect(find.text('Send'), findsNothing);
      expect(find.text('Follow'), findsNothing);
    });

    testWidgets('failing to load says so, never that the thread is empty, '
        'and retries', (tester) async {
      server
        ..addComment(occasion, gift, 'Blue one', author: 'Carol')
        ..status[commentsCall('GET')] = 500;
      await openSheet(tester);

      expect(sheetSnackBar(serverError), findsOneWidget);
      expect(find.text('The comments could not be loaded.'), findsOneWidget);
      expect(find.textContaining('No comments yet'), findsNothing);
      expect(find.text('Send'), findsNothing);
      expect(find.text('Follow'), findsNothing);

      server.status.remove(commentsCall('GET'));
      await tapText(tester, 'Try again');

      expect(find.text('Blue one'), findsOneWidget);
      expect(find.text('The comments could not be loaded.'), findsNothing);
    });

    testWidgets('a reload that fails after a write keeps what is shown',
        (tester) async {
      server.addComment(occasion, gift, 'Blue one', author: 'Carol');
      await openSheet(tester);
      server.status[commentsCall('GET')] = 500;
      await write(tester, 'Hello');
      await tapText(tester, 'Send');

      expect(sheetSnackBar(serverError), findsOneWidget);
      expect(find.text('Blue one'), findsOneWidget);
      // The write went through: not sent twice by mistake.
      expect(tester.widget<TextField>(sheetField()).controller!.text, isEmpty);
    });

    testWidgets('a write failing after the sheet closed is said on the page',
        (tester) async {
      server.status[commentsCall('POST')] = 500;
      await openSheet(tester);
      await write(tester, 'Hello');
      server.hold = Completer();
      await tester.tap(find.text('Send'));
      await tester.pump();
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(find.byType(BottomSheet), findsNothing);
      final reads = threadReads();

      server.hold!.complete();
      server.hold = null;
      await tester.pumpAndSettle();

      expect(find.widgetWithText(SnackBar, serverError), findsOneWidget);
      expect(threadReads(), reads);
    });
  });

  testWidgets('the field stays above the keyboard', (tester) async {
    await tall(tester);
    await startApp(tester, server, '/shared/$occasion');
    await tester.tap(find.widgetWithText(GiftCard, 'Headphones'));
    await tester.pumpAndSettle();
    tester.view.viewInsets = const FakeViewPadding(bottom: 500);
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpAndSettle();

    expect(tester.getBottomLeft(find.text('Send')).dy, lessThanOrEqualTo(1300));
  });

  testWidgets('the thread in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    server
      ..addComment(occasion, gift, 'Le bleu ?', author: 'Carol', edited: true)
      ..addComment(occasion, gift, 'Oui', mine: true)
      ..addComment(occasion, gift, 'Parti');
    await openSheet(tester);

    expect(find.text('Commentaires'), findsOneWidget);
    expect(find.text('Suivre'), findsOneWidget);
    expect(find.text('Utilisateur supprimé'), findsOneWidget);
    expect(find.textContaining('· modifié'), findsOneWidget);
    expect(find.text('Vous'), findsOneWidget);
    expect(find.text('Modifier'), findsOneWidget);
    expect(find.text('Supprimer'), findsOneWidget);
    expect(find.text('Envoyer'), findsOneWidget);
    expect(find.text('Ajouter un commentaire'), findsOneWidget);
    expect(find.text('0 / 2000'), findsOneWidget);

    await tapText(tester, 'Supprimer');
    expect(find.text('Supprimer ce commentaire ?'), findsOneWidget);
  });

  group('when a comment was written', () {
    setUpAll(initializeDateFormatting);

    final now = DateTime(2026, 11, 9, 16);

    String label(String language, String locale, DateTime at) =>
        commentTimeLabel(lookupAppLocalizations(Locale(language)), locale, at, now);

    test('today', () {
      expect(
        label('en', 'en_GB', DateTime(2026, 11, 9, 14, 30)),
        'Today at 14:30',
      );
    });

    test('yesterday, also across a month', () {
      expect(
        label('en', 'en_GB', DateTime(2026, 11, 8, 23, 59)),
        'Yesterday at 23:59',
      );
      expect(
        commentTimeLabel(
          lookupAppLocalizations(const Locale('en')),
          'en_GB',
          DateTime(2026, 10, 31, 8),
          DateTime(2026, 11, 1, 9),
        ),
        'Yesterday at 08:00',
      );
    });

    test('earlier this year, then with its year', () {
      expect(
        label('en', 'en_GB', DateTime(2026, 3, 4, 9, 15)),
        '4 Mar at 09:15',
      );
      expect(
        label('en', 'en_GB', DateTime(2025, 3, 4, 9, 15)),
        '4 Mar 2025 at 09:15',
      );
    });

    test('in French', () {
      expect(
        label('fr', 'fr_FR', DateTime(2026, 11, 9, 14, 30)),
        "Aujourd'hui à 14:30",
      );
      expect(label('fr', 'fr_FR', DateTime(2026, 11, 8, 9)), 'Hier à 09:00');
    });

    test('a server time is shown in the viewer\'s zone', () {
      final local = DateTime(2026, 11, 9, 14, 30);
      expect(label('en', 'en_GB', local.toUtc()), 'Today at 14:30');
    });
  });
}
