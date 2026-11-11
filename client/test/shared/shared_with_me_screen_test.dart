import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/auth/account_screen.dart';
import 'package:shushgift/src/lists/my_lists_screen.dart';
import 'package:shushgift/src/shared/occasion_screen.dart';
import 'package:shushgift/src/shared/shared_with_me_screen.dart';

import '../lists/support/fake_lists_server.dart';

void main() {
  late FakeListsServer server;

  setUp(() => server = FakeListsServer());

  /// An occasion of someone else's list that Alice joined.
  String joinedOccasion(
    String name,
    String date, {
    String list = 'Christmas',
    String? recipientName = 'Léa',
    List<String> owners = const ['Bob Durand'],
  }) {
    final id = server.addList(list, recipientName: recipientName, ownerNames: owners);
    final occasion = server.addOccasion(id, name, date);
    server.joined.add(occasion);
    return occasion;
  }

  testWidgets('loading: progress until the occasions arrive', (tester) async {
    server.hold = Completer();
    await startApp(tester, server, '/shared', settle: false);

    expect(find.widgetWithText(AppBar, 'Shared with me'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    server.hold!.complete();
    await tester.pumpAndSettle();
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('empty: says how to get something shared', (tester) async {
    await startApp(tester, server, '/shared');

    expect(
      find.text(
        'Nothing is shared with you yet. Open an occasion link someone sent '
        'you to join it.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('content: each occasion, its date, list, recipient and owner',
      (tester) async {
    joinedOccasion('Christmas 2026', '2026-12-24');
    joinedOccasion(
      'Birthday',
      '2027-03-02',
      list: "Sam's birthday",
      recipientName: null,
      owners: ['Sam Lee'],
    );
    // Not joined: not shown.
    final other = server.addList('Secret', ownerNames: ['Eve']);
    server.addOccasion(other, 'Hidden', '2026-01-01');

    await startApp(tester, server, '/shared');

    expect(find.text('Christmas 2026'), findsOneWidget);
    expect(find.text('Dec 24, 2026 · Christmas'), findsOneWidget);
    expect(find.text('For Léa · shared by Bob Durand'), findsOneWidget);
    expect(find.text('Birthday'), findsOneWidget);
    // A list made for oneself names its owner as the recipient.
    expect(find.text('For Sam Lee · shared by Sam Lee'), findsOneWidget);
    expect(find.text('Hidden'), findsNothing);
  });

  testWidgets('error: says why and retries', (tester) async {
    server.status['GET /api/shared'] = 500;
    await startApp(tester, server, '/shared');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );

    server.status.remove('GET /api/shared');
    joinedOccasion('Christmas 2026', '2026-12-24');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('an occasion opens its view; leaving it removes it here',
      (tester) async {
    joinedOccasion('Christmas 2026', '2026-12-24');
    await startApp(tester, server, '/shared');

    await tester.tap(find.text('Christmas 2026'));
    await tester.pumpAndSettle();
    expect(find.byType(OccasionScreen), findsOneWidget);

    await tester.tap(find.byTooltip('Show menu'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Leave the occasion'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Leave'));
    await tester.pumpAndSettle();

    expect(find.byType(SharedWithMeScreen), findsOneWidget);
    expect(find.text('Christmas 2026'), findsNothing);
  });

  testWidgets('the navigation bar switches between the two destinations',
      (tester) async {
    server.addList('Birthday');
    joinedOccasion('Christmas 2026', '2026-12-24');
    await startApp(tester, server, '/');

    expect(find.byType(MyListsScreen), findsOneWidget);
    await tester.tap(
      find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('Shared with me'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(SharedWithMeScreen), findsOneWidget);
    expect(find.text('Christmas 2026'), findsOneWidget);

    await tester.tap(
      find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('My lists'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(MyListsScreen), findsOneWidget);
    expect(find.text('Birthday'), findsOneWidget);
  });

  testWidgets('the app bar opens the account screen', (tester) async {
    await startApp(tester, server, '/shared');

    await tester.tap(find.byTooltip('Account'));
    await tester.pumpAndSettle();

    expect(find.byType(AccountScreen), findsOneWidget);
  });
}
