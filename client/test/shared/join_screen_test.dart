import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/shared/join_screen.dart';
import 'package:wishlist/src/shared/occasion_screen.dart';
import 'package:wishlist/src/shared/pending_join.dart';

import '../lists/support/fake_lists_server.dart';
import '../support/fakes.dart';

const _invalid =
    'This link is no longer valid. Ask the person who shared it for a new one.';

void main() {
  late FakeListsServer server;
  late String bobsList;
  late String occasion;
  late MemoryJoinBrowser browser;

  setUp(() {
    server = FakeListsServer();
    bobsList = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    occasion = server.addOccasion(
      bobsList,
      'Christmas 2026',
      '2026-12-24',
      token: 'tok',
    );
    browser = MemoryJoinBrowser();
  });

  /// The app opened with [url], as main() captures it.
  PendingJoin opened(String url) =>
      PendingJoin.capture(Uri.parse(url), browser);

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).last),
      ).routerDelegate.currentConfiguration.uri;

  /// What the router tells the browser's history: (location, replace).
  List<(String, bool)> historyUpdates(WidgetTester tester) {
    final updates = <(String, bool)>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.navigation,
      (call) async {
        if (call.method == 'routeInformationUpdated') {
          final arguments = call.arguments as Map<Object?, Object?>;
          updates.add((arguments['uri'] as String, arguments['replace'] as bool));
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.navigation, null),
    );
    return updates;
  }

  /// The browser going back to the history entry at [location].
  Future<void> browserBack(WidgetTester tester, String location) async {
    await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
      SystemChannels.navigation.name,
      SystemChannels.navigation.codec.encodeMethodCall(
        MethodCall(
          'pushRouteInformation',
          {'location': location, 'state': null},
        ),
      ),
      (_) {},
    );
    await tester.pumpAndSettle();
  }

  testWidgets('signed out: through sign-in, back to the confirmation',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    final app = await startApp(
      tester,
      server,
      '/join',
      signedIn: false,
      pendingJoin: pending,
    );

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(location(tester).queryParameters['from'], '/join');
    expect(server.calls, isEmpty);

    await app.auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(find.byType(JoinScreen), findsOneWidget);
    expect(find.text('Christmas 2026'), findsOneWidget);
    expect(server.bodies['POST /api/join/preview'], {'token': 'tok'});
    expect(server.calls, isNot(contains('POST /api/join')));
  });

  testWidgets('signed out, joined: back to sign-in goes home, not invalid',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    final updates = historyUpdates(tester);
    final app = await startApp(
      tester,
      server,
      '/join',
      signedIn: false,
      pendingJoin: pending,
    );
    await app.auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();
    expect(find.byType(OccasionScreen), findsOneWidget);

    // The browser's history: the sign-in entry, then the occasion in place
    // of /join. Back returns to the sign-in entry.
    expect(
      [for (final (uri, replace) in updates) if (!replace) uri],
      ['/join'],
    );
    expect(updates.first, ('/sign-in?from=%2Fjoin', true));
    await browserBack(tester, updates.first.$1);

    expect(find.text(_invalid), findsNothing);
    expect(find.byType(JoinScreen), findsNothing);
    expect(location(tester).path, '/');
    expect(updates.last, ('/', true));
    expect(
      server.calls.where((call) => call == 'POST /api/join/preview'),
      hasLength(1),
    );
  });

  testWidgets('a reload during sign-in keeps the pending token',
      (tester) async {
    opened('https://app.example/join#tok');
    // The tab reloads on the sign-in screen: a new start, with no fragment.
    final reloaded = opened('https://app.example/sign-in?from=%2Fjoin');
    final app = await startApp(
      tester,
      server,
      '/sign-in?from=%2Fjoin',
      signedIn: false,
      pendingJoin: reloaded,
    );

    await app.auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(find.byType(JoinScreen), findsOneWidget);
    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('the confirmation says what is joined, and joins nothing yet',
      (tester) async {
    await startApp(
      tester,
      server,
      '/join',
      pendingJoin: opened('https://app.example/join#tok'),
    );

    expect(find.text('You are invited to'), findsOneWidget);
    expect(find.text('Christmas 2026'), findsOneWidget);
    expect(find.text('Dec 24, 2026'), findsOneWidget);
    expect(find.text('List  Christmas', findRichText: true), findsOneWidget);
    expect(find.text('For  Léa', findRichText: true), findsOneWidget);
    expect(
      find.text('Shared by  Bob Durand', findRichText: true),
      findsOneWidget,
    );
    expect(find.widgetWithText(FilledButton, 'Join'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Cancel'), findsOneWidget);
    expect(server.calls, ['POST /api/join/preview']);
    expect(server.joined, isEmpty);
  });

  testWidgets('Cancel joins nothing, clears the link and goes home',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);
    final updates = historyUpdates(tester);

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(server.calls, isNot(contains('POST /api/join')));
    expect(server.joined, isEmpty);
    expect(pending.token, isNull);
    expect(browser.stored, isNull);
    expect(location(tester).path, '/');
    expect(updates.last, ('/', true));
  });

  testWidgets('Join joins, clears the link and opens the occasion in its place',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);
    final updates = historyUpdates(tester);

    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();

    expect(server.bodies['POST /api/join'], {'token': 'tok'});
    expect(server.joined, {occasion});
    expect(pending.token, isNull);
    expect(browser.stored, isNull);
    expect(find.byType(OccasionScreen), findsOneWidget);
    expect(location(tester).path, '/shared/$occasion');
    // The browser's back button does not return to /join (review R3-2).
    expect(updates.last, ('/shared/$occasion', true));

    // Back in the app goes to Shared with me, not to the link.
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(JoinScreen), findsNothing);
    expect(location(tester).path, '/shared');
  });

  testWidgets('after joining, /join again without a fragment is invalid',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);
    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();

    // A second load of /join in the same tab: nothing pending any more.
    await tester.pumpWidget(const SizedBox());
    await startApp(
      tester,
      server,
      '/join',
      pendingJoin: opened('https://app.example/join'),
    );

    expect(find.text(_invalid), findsOneWidget);
    expect(
      server.calls.where((call) => call == 'POST /api/join/preview'),
      hasLength(1),
    );
  });

  testWidgets('a member goes straight to the occasion', (tester) async {
    server.joined.add(occasion);
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);

    expect(find.byType(OccasionScreen), findsOneWidget);
    expect(location(tester).path, '/shared/$occasion');
    expect(server.calls, isNot(contains('POST /api/join')));
    expect(pending.token, isNull);
  });

  testWidgets('an owner opens the list, without being offered to join',
      (tester) async {
    final mine = server.addList('Birthday');
    server.addOccasion(mine, 'Birthday 2026', '2026-06-01', token: 'mine');
    final pending = opened('https://app.example/join#mine');
    await startApp(tester, server, '/join', pendingJoin: pending);

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(location(tester).path, '/lists/$mine');
    expect(find.text('Join'), findsNothing);
    expect(server.calls, isNot(contains('POST /api/join')));
    expect(pending.token, isNull);
  });

  testWidgets('a 409 on join opens the list as its owner', (tester) async {
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);
    // Alice became an owner of the list since the preview.
    server.lists[bobsList] = server.otherLists.remove(bobsList)!;

    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(location(tester).path, '/lists/$bobsList');
    expect(pending.token, isNull);
  });

  testWidgets('an unknown, replaced or revoked link says it is no longer valid',
      (tester) async {
    final pending = opened('https://app.example/join#gone');
    await startApp(tester, server, '/join', pendingJoin: pending);

    expect(find.text(_invalid), findsOneWidget);
    expect(find.text('Join'), findsNothing);
    expect(pending.token, isNull);

    await tester.tap(find.text('Back to my lists'));
    await tester.pumpAndSettle();
    expect(location(tester).path, '/');
  });

  testWidgets('a removed person is told the link is no longer valid',
      (tester) async {
    server.aliceRemoved.add(occasion);
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);

    expect(find.text(_invalid), findsOneWidget);
    expect(server.calls, isNot(contains('POST /api/join')));
    expect(pending.token, isNull);
  });

  testWidgets('a link revoked between preview and join is no longer valid',
      (tester) async {
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);
    server.occasions[occasion]!['join_token'] = null;

    await tester.tap(find.text('Join'));
    await tester.pumpAndSettle();

    expect(find.text(_invalid), findsOneWidget);
    expect(server.joined, isEmpty);
    expect(pending.token, isNull);
  });

  testWidgets('/join with nothing pending is invalid, and calls nothing',
      (tester) async {
    await startApp(
      tester,
      server,
      '/join',
      pendingJoin: opened('https://app.example/join'),
    );

    expect(find.text(_invalid), findsOneWidget);
    expect(server.calls, isEmpty);
  });

  testWidgets('a server error keeps the link, to try again', (tester) async {
    server.status['POST /api/join/preview'] = 500;
    final pending = opened('https://app.example/join#tok');
    await startApp(tester, server, '/join', pendingJoin: pending);

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );
    expect(pending.token, 'tok');

    server.status.remove('POST /api/join/preview');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Christmas 2026'), findsOneWidget);
  });

  testWidgets('while joining, the buttons wait', (tester) async {
    await startApp(
      tester,
      server,
      '/join',
      pendingJoin: opened('https://app.example/join#tok'),
    );
    server.hold = Completer();

    await tester.tap(find.text('Join'));
    await tester.pump();

    expect(
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Join'))
          .onPressed,
      isNull,
    );
    expect(
      tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Cancel'))
          .onPressed,
      isNull,
    );

    server.hold!.complete();
    await tester.pumpAndSettle();
    expect(find.byType(OccasionScreen), findsOneWidget);
  });

  testWidgets('in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await startApp(
      tester,
      server,
      '/join',
      pendingJoin: opened('https://app.example/join#tok'),
    );

    expect(find.text('Rejoindre une occasion'), findsOneWidget);
    expect(find.text('24 déc. 2026'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Rejoindre'), findsOneWidget);
  });
}
