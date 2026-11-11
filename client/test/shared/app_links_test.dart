import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shushgift/src/api/api_client.dart';
import 'package:shushgift/src/auth/auth_controller.dart';
import 'package:shushgift/src/auth/email_link_screen.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/home/home_screen.dart';
import 'package:shushgift/src/lists/list_detail_screen.dart';
import 'package:shushgift/src/shared/app_links.dart';
import 'package:shushgift/src/shared/join_screen.dart';
import 'package:shushgift/src/shared/occasion_screen.dart';

import '../lists/support/fake_lists_server.dart';
import '../support/fakes.dart';

/// Links that open the app on Android and iOS (Shush Gift plan D7): the
/// whole link reaches the app, at start (Android's initial route) or while it
/// runs (pushed, as iOS does at start too), and lands where the same address
/// lands on the web.
void main() {
  const host = 'https://val.shushgift.com';

  late FakeListsServer server;
  late String bobsList;
  late String occasion;
  late String gift;

  setUp(() {
    server = FakeListsServer();
    bobsList = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    gift = server.addGift(bobsList, 'Headphones');
    occasion = server.addOccasion(
      bobsList,
      'Christmas 2026',
      '2026-12-24',
      token: 'tok',
    );
  });

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).first),
      ).routerDelegate.currentConfiguration.uri;

  final sheet = find.byType(BottomSheet);

  /// The app started by [link], as Android starts it.
  Future<({ApiClient api, AuthController auth})> coldStart(
    WidgetTester tester,
    String link, {
    bool signedIn = true,
  }) =>
      startApp(tester, server, link, signedIn: signedIn, openAppLinks: true);

  /// [link] opened while the app runs, as the engine pushes it; whether the
  /// app answered it as handled (iOS gives an unhandled one back to Safari).
  Future<bool> openLink(WidgetTester tester, String link) async {
    bool? handled;
    await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
      SystemChannels.navigation.name,
      SystemChannels.navigation.codec.encodeMethodCall(
        MethodCall('pushRouteInformation', {'location': link}),
      ),
      (reply) => handled =
          SystemChannels.navigation.codec.decodeEnvelope(reply!) as bool,
    );
    await tester.pumpAndSettle();
    return handled!;
  }

  EmailLinkScreen emailLinkScreen(WidgetTester tester) =>
      tester.widget<EmailLinkScreen>(find.byType(EmailLinkScreen));

  group('appLocationOf', () {
    test('the path and query, without the host or the fragment', () {
      expect(appLocationOf(Uri.parse('$host/join#tok')), '/join');
      expect(
        appLocationOf(Uri.parse('$host/shared/o-1?gift=g-1')),
        '/shared/o-1?gift=g-1',
      );
      expect(
        appLocationOf(Uri.parse('$host/reset-password?x=1#t')),
        '/reset-password?x=1',
      );
      expect(appLocationOf(Uri.parse(host)), '/');
      expect(appLocationOf(Uri.parse('/account')), '/account');
    });
  });

  group('/join#<token>', () {
    testWidgets('cold: the confirmation for that token', (tester) async {
      await coldStart(tester, '$host/join#tok');

      expect(find.byType(JoinScreen), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
      expect(server.bodies['POST /api/join/preview'], {'token': 'tok'});
      expect(location(tester).toString(), '/join');
    });

    testWidgets('cold, signed out: through sign-in, back to the confirmation',
        (tester) async {
      final app = await coldStart(tester, '$host/join#tok', signedIn: false);

      expect(find.byType(SignInScreen), findsOneWidget);
      // The location a browser shows: the token is in no location.
      expect(location(tester).toString(), '/sign-in?from=%2Fjoin');
      expect(server.calls, isEmpty);

      await app.auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();

      expect(find.byType(JoinScreen), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
      expect(server.bodies['POST /api/join/preview'], {'token': 'tok'});
    });

    testWidgets('warm: the confirmation for that token', (tester) async {
      await coldStart(tester, '/');
      expect(find.byType(HomeScreen), findsOneWidget);

      expect(await openLink(tester, '$host/join#tok'), isTrue);

      expect(find.byType(JoinScreen), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
      expect(server.bodies['POST /api/join/preview'], {'token': 'tok'});
      expect(location(tester).toString(), '/join');
    });

    testWidgets('warm, over another confirmation: the new one replaces it',
        (tester) async {
      final other = server.addList('Birthday', ownerNames: ['Carol']);
      server.addOccasion(other, 'Birthday 2026', '2026-06-01', token: 'tok2');
      await coldStart(tester, '$host/join#tok');
      expect(find.text('Christmas 2026'), findsOneWidget);

      await openLink(tester, '$host/join#tok2');

      expect(find.text('Birthday 2026'), findsOneWidget);
      expect(find.text('Christmas 2026'), findsNothing);
      expect(server.bodies['POST /api/join/preview'], {'token': 'tok2'});

      // Joining joins what is shown.
      await tester.tap(find.text('Join'));
      await tester.pumpAndSettle();
      expect(server.bodies['POST /api/join'], {'token': 'tok2'});
    });
  });

  group('/shared/<occasion>?gift=<gift>', () {
    setUp(() => server.joined.add(occasion));

    testWidgets('cold: the occasion and that gift\'s sheet', (tester) async {
      await coldStart(tester, '$host/shared/$occasion?gift=$gift');

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(
        find.descendant(of: sheet, matching: find.text('Headphones')),
        findsOneWidget,
      );
      expect(location(tester).toString(), '/shared/$occasion?gift=$gift');
    });

    testWidgets('warm: the occasion and that gift\'s sheet', (tester) async {
      await coldStart(tester, '/');

      expect(await openLink(tester, '$host/shared/$occasion?gift=$gift'), isTrue);

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(
        find.descendant(of: sheet, matching: find.text('Headphones')),
        findsOneWidget,
      );
      expect(location(tester).toString(), '/shared/$occasion?gift=$gift');
    });

    testWidgets('the recipient: the list, with no sheet and no activity',
        (tester) async {
      final list = server.addList('Birthday');
      final own = server.addGift(list, 'Bike');
      final mine = server.addOccasion(list, 'Birthday 2026', '2026-12-24');
      await coldStart(tester, '/');

      await openLink(tester, '$host/shared/$mine?gift=$own');

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(location(tester).toString(), '/lists/$list');
      expect(sheet, findsNothing);
      expect(
        server.calls.where(
          (call) => RegExp(r'/api/occasions/[^/]+/(claims$|gifts/|hidden-gifts)')
              .hasMatch(call),
        ),
        isEmpty,
      );
    });
  });

  group('/reset-password#<token>', () {
    testWidgets('cold: the reset page for that token', (tester) async {
      await coldStart(tester, '$host/reset-password#t1', signedIn: false);

      expect(emailLinkScreen(tester).kind, EmailLinkKind.reset);
      expect(emailLinkScreen(tester).token, 't1');
      expect(location(tester).toString(), '/reset-password');
    });

    testWidgets('warm: the reset page for that token', (tester) async {
      await coldStart(tester, '/', signedIn: false);

      expect(await openLink(tester, '$host/reset-password#t1'), isTrue);

      expect(emailLinkScreen(tester).kind, EmailLinkKind.reset);
      expect(emailLinkScreen(tester).token, 't1');
      expect(location(tester).toString(), '/reset-password');
    });

    testWidgets('warm, over an earlier one: the newer token', (tester) async {
      await coldStart(tester, '$host/reset-password#t1', signedIn: false);

      await openLink(tester, '$host/reset-password#t2');

      expect(emailLinkScreen(tester).token, 't2');
    });
  });

  testWidgets('without app links, a pushed location goes to the router as is',
      (tester) async {
    // The web: its browser pushes its history this way.
    await startApp(tester, server, '/');

    await openLink(tester, '/account');

    expect(location(tester).toString(), '/account');
  });
}
