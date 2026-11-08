import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/auth/account_screen.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/lists/list_form_screen.dart';

import '../lists/support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;

  setUp(() => server = FakeListsServer());

  testWidgets('loading: progress until the lists arrive', (tester) async {
    server.hold = Completer();
    await startApp(tester, server, '/', settle: false);

    expect(find.text('My lists'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    server.hold!.complete();
    await tester.pumpAndSettle();
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('empty: says so and offers to create a list', (tester) async {
    await startApp(tester, server, '/');

    expect(
      find.text(
        'You have no lists yet. Create one for yourself or for someone else.',
      ),
      findsOneWidget,
    );
    expect(find.widgetWithText(FilledButton, 'New list'), findsOneWidget);
  });

  testWidgets('content: each list with who it is for and its gift count',
      (tester) async {
    final mine = server.addList('Birthday');
    server.addGift(mine, 'Headphones');
    server.addGift(mine, 'Book');
    server.addList('Christmas', recipientName: 'Léa');

    await startApp(tester, server, '/');

    expect(find.text('Birthday'), findsOneWidget);
    expect(find.text('For me · 2 gifts'), findsOneWidget);
    expect(find.text('Christmas'), findsOneWidget);
    expect(find.text('For Léa · No gifts'), findsOneWidget);
  });

  testWidgets('error: says why and retries', (tester) async {
    server.status['GET /api/lists'] = 500;
    await startApp(tester, server, '/');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );

    server.status.remove('GET /api/lists');
    server.addList('Birthday');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(find.text('Birthday'), findsOneWidget);
  });

  testWidgets('a list opens its detail; coming back shows the lists again',
      (tester) async {
    final id = server.addList('Birthday');
    await startApp(tester, server, '/');

    await tester.tap(find.text('Birthday'));
    await tester.pumpAndSettle();
    expect(find.byType(ListDetailScreen), findsOneWidget);

    server.lists[id]!['title'] = 'Renamed';
    await tester.pageBack();
    await tester.pumpAndSettle();

    expect(find.text('Renamed'), findsOneWidget);
  });

  testWidgets('creating a list opens it, and it is in the lists after',
      (tester) async {
    await startApp(tester, server, '/');

    await tester.tap(find.text('New list'));
    await tester.pumpAndSettle();
    expect(find.byType(ListFormScreen), findsOneWidget);

    await tester.enterText(fieldLabelled('List title'), 'Birthday');
    await tester.tap(find.text('Create'));
    await tester.pumpAndSettle();

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(server.lists.values.single['title'], 'Birthday');

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Birthday'), findsOneWidget);
  });

  testWidgets('the app bar opens the account screen', (tester) async {
    await startApp(tester, server, '/');

    await tester.tap(find.byTooltip('Account'));
    await tester.pumpAndSettle();

    expect(find.byType(AccountScreen), findsOneWidget);
  });
}
