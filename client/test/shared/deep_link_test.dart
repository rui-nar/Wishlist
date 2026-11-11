import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/lists/list_detail_screen.dart';
import 'package:shushgift/src/shared/occasion_screen.dart';

import '../lists/support/fake_lists_server.dart';
import '../support/fakes.dart';

/// An email's link to a gift: `/shared/<occasion>?gift=<gift>`
/// (COMMENTS_NOTIFICATIONS_PLAN D20). Such links stay in inboxes: they must
/// keep working in every later release.
void main() {
  late FakeListsServer server;

  setUp(() => server = FakeListsServer());

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).first),
      ).routerDelegate.currentConfiguration.uri;

  final sheet = find.byType(BottomSheet);

  /// Any activity an owner of a list for themselves must never ask for.
  List<String> activityCalls() => [
        for (final call in server.calls)
          if (RegExp(r'^\w+ /api/occasions/[^/]+/(claims$|gifts/|hidden-gifts)')
              .hasMatch(call))
            call,
      ];

  group('an invitee', () {
    late String occasion;
    late String gift;

    setUp(() {
      final list = server.addList(
        'Christmas',
        recipientName: 'Léa',
        ownerNames: ['Bob Durand'],
      );
      gift = server.addGift(list, 'Headphones');
      server.addGift(list, 'Book');
      occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
      server.joined.add(occasion);
    });

    testWidgets('opens the occasion and that gift\'s sheet', (tester) async {
      await startApp(tester, server, '/shared/$occasion?gift=$gift');

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(
        find.descendant(of: sheet, matching: find.text('Headphones')),
        findsOneWidget,
      );
      expect(
        server.calls,
        contains('GET /api/occasions/$occasion/claims'),
      );
    });

    testWidgets('without a gift, no sheet', (tester) async {
      await startApp(tester, server, '/shared/$occasion');

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(sheet, findsNothing);
    });

    testWidgets('an unknown gift opens the occasion only', (tester) async {
      await startApp(tester, server, '/shared/$occasion?gift=gone');

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(find.text('Headphones'), findsOneWidget);
      expect(sheet, findsNothing);
    });

    testWidgets('a hidden gift of the occasion opens too', (tester) async {
      final hidden = server.addHidden(occasion, 'Secret', author: 'Carol');

      await startApp(tester, server, '/shared/$occasion?gift=$hidden');

      expect(
        find.descendant(of: sheet, matching: find.text('Secret')),
        findsOneWidget,
      );
    });

    testWidgets('the sheet does not come back after closing', (tester) async {
      await startApp(tester, server, '/shared/$occasion?gift=$gift');

      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(sheet, findsNothing);

      await tester.pump();
      await tester.pumpAndSettle();
      expect(sheet, findsNothing);
    });

    testWidgets('signed out: back to the same gift after signing in',
        (tester) async {
      final app = await startApp(
        tester,
        server,
        '/shared/$occasion?gift=$gift',
        signedIn: false,
      );
      expect(find.byType(SignInScreen), findsOneWidget);

      await app.auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(
        find.descendant(of: sheet, matching: find.text('Headphones')),
        findsOneWidget,
      );
    });
  });

  group('the owner of a list for someone else', () {
    testWidgets('is sent to giver mode, the gift kept, and the sheet opens',
        (tester) async {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final gift = server.addGift(list, 'Headphones');
      final occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');

      await startApp(tester, server, '/shared/$occasion?gift=$gift');

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(location(tester).path, '/lists/$list/occasions/$occasion');
      expect(location(tester).queryParameters, {'gift': gift});
      expect(
        find.descendant(of: sheet, matching: find.text('Headphones')),
        findsOneWidget,
      );
    });

    testWidgets('without a gift, still goes to the list (RESERVING D14)',
        (tester) async {
      final list = server.addList('Christmas', recipientName: 'Léa');
      final occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');

      await startApp(tester, server, '/shared/$occasion');

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(sheet, findsNothing);
    });
  });

  group('the owner of a list for themselves, the recipient', () {
    testWidgets('goes to the list without the sheet or any activity',
        (tester) async {
      final list = server.addList('Birthday');
      final gift = server.addGift(list, 'Headphones');
      final occasion = server.addOccasion(list, 'Birthday 2026', '2026-12-24');

      await startApp(tester, server, '/shared/$occasion?gift=$gift');

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(location(tester).toString(), '/lists/$list');
      expect(sheet, findsNothing);
      expect(activityCalls(), isEmpty);
    });

    testWidgets('under the list as well', (tester) async {
      final list = server.addList('Birthday');
      final gift = server.addGift(list, 'Headphones');
      final occasion = server.addOccasion(list, 'Birthday 2026', '2026-12-24');

      await startApp(
        tester,
        server,
        '/lists/$list/occasions/$occasion?gift=$gift',
      );

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(location(tester).toString(), '/lists/$list');
      expect(sheet, findsNothing);
      expect(activityCalls(), isEmpty);
    });
  });
}
