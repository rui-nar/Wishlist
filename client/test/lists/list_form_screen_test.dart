import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/lists/list_form_screen.dart';

import 'support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;

  setUp(() => server = FakeListsServer());

  group('creating', () {
    testWidgets('an empty title is refused, and nothing is sent',
        (tester) async {
      await startApp(tester, server, '/lists/new');

      await tester.enterText(fieldLabelled('List title'), '   ');
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(find.text('Enter a title'), findsOneWidget);
      expect(server.calls, isNot(contains('POST /api/lists')));
    });

    testWidgets('"for me" sends no name, and opens the list', (tester) async {
      await startApp(tester, server, '/lists/new');

      expect(find.text('This cannot be changed later.'), findsOneWidget);
      expect(fieldLabelled('Their name'), findsNothing);
      await tester.enterText(fieldLabelled('List title'), ' Birthday ');
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(server.bodies['POST /api/lists'], {
        'title': 'Birthday',
        'recipient_kind': 'self',
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('"for someone else" needs their name', (tester) async {
      await startApp(tester, server, '/lists/new');

      await tester.enterText(fieldLabelled('List title'), 'Christmas');
      await tester.tap(find.text('For someone else'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(find.text('Enter their name'), findsOneWidget);
      expect(server.calls, isNot(contains('POST /api/lists')));

      await tester.enterText(fieldLabelled('Their name'), 'Léa');
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(server.bodies['POST /api/lists'], {
        'title': 'Christmas',
        'recipient_kind': 'other',
        'recipient_name': 'Léa',
      });
    });

    testWidgets('a failed save says so and stays on the form', (tester) async {
      server.status['POST /api/lists'] = 500;
      await startApp(tester, server, '/lists/new');

      await tester.enterText(fieldLabelled('List title'), 'Birthday');
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(find.text('Your changes could not be saved. Try again.'),
          findsOneWidget);
      expect(find.byType(ListFormScreen), findsOneWidget);
    });

    testWidgets('titles are cut at the server limit', (tester) async {
      await startApp(tester, server, '/lists/new');

      await tester.enterText(fieldLabelled('List title'), 'x' * 150);
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(
        (server.bodies['POST /api/lists']!['title'] as String).length,
        kListTitleMaxLength,
      );
    });
  });

  group('renaming', () {
    testWidgets('loading, then the list as it is, without the kind choice',
        (tester) async {
      final id = server.addList('Christmas', recipientName: 'Léa');
      server.hold = Completer();
      await startApp(tester, server, '/lists/$id/edit', settle: false);

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      server.hold!.complete();
      await tester.pumpAndSettle();

      expect(find.text('Rename list'), findsOneWidget);
      expect(find.text('Christmas'), findsOneWidget);
      expect(find.text('Léa'), findsOneWidget);
      expect(find.text('For me'), findsNothing);
    });

    testWidgets('saves the title and name, and goes back to the list',
        (tester) async {
      final id = server.addList('Christmas', recipientName: 'Léa');
      await startApp(tester, server, '/lists/$id');

      await tester.tap(find.byTooltip('Show menu'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rename'));
      await tester.pumpAndSettle();

      await tester.enterText(fieldLabelled('List title'), 'Noël');
      await tester.enterText(fieldLabelled('Their name'), 'Léa M.');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(server.bodies['PATCH /api/lists/$id'], {
        'title': 'Noël',
        'recipient_name': 'Léa M.',
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(find.text('Noël'), findsOneWidget);
      expect(find.text('For Léa M.'), findsOneWidget);
    });

    testWidgets('a list for me sends no name', (tester) async {
      final id = server.addList('Birthday');
      await startApp(tester, server, '/lists/$id/edit');

      expect(fieldLabelled('Their name'), findsNothing);
      await tester.enterText(fieldLabelled('List title'), 'Birthday 30');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(server.bodies['PATCH /api/lists/$id'], {'title': 'Birthday 30'});
    });

    testWidgets('a list that is gone says so', (tester) async {
      await startApp(tester, server, '/lists/nope/edit');

      expect(find.text('This list no longer exists.'), findsOneWidget);
      await tester.tap(find.text('Back to my lists'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(AppBar, 'My lists'), findsOneWidget);
    });
  });
}
