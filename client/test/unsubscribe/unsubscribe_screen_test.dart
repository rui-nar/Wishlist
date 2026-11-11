import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shushgift/src/auth/account_screen.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/unsubscribe/unsubscribe_screen.dart';

import '../support/fakes.dart';

/// The page an email's link opens, signed out as well as in
/// (COMMENTS_NOTIFICATIONS_PLAN D18, D20).
void main() {
  const link = '/unsubscribe#$kUnsubscribeToken';
  const stop = 'Stop email notifications';
  const invalid = 'This link is not valid. Open it again from your email, or '
      'change your email notifications from your account.';

  late FakeServer server;

  setUp(() {
    server = FakeServer();
    installFakeGoogleSignIn();
  });

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).last),
      ).routerDelegate.currentConfiguration.uri;

  Future<void> start(
    WidgetTester tester,
    String at, {
    bool signedIn = false,
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(
      server,
      store: MemoryTokenStore(signedIn ? server.addSession() : null),
    );
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
  }

  String unsubscribeCall(String token) => 'POST /api/unsubscribe/$token';

  test('the token is the fragment of the unsubscribe link only', () {
    expect(unsubscribeTokenFrom(Uri.parse(link)), kUnsubscribeToken);
    expect(unsubscribeTokenFrom(Uri.parse('/unsubscribe')), isNull);
    expect(unsubscribeTokenFrom(Uri.parse('/unsubscribe#')), isNull);
    expect(unsubscribeTokenFrom(Uri.parse('/join#abc')), isNull);
  });

  testWidgets('reachable signed out, and nothing sent before the button',
      (tester) async {
    await start(tester, link);

    expect(find.byType(UnsubscribeScreen), findsOneWidget);
    expect(find.byType(SignInScreen), findsNothing);
    expect(location(tester).path, '/unsubscribe');
    expect(find.widgetWithText(FilledButton, stop), findsOneWidget);
    // A mail scanner opening the link changes nothing.
    expect(server.calls, isNot(contains(unsubscribeCall(kUnsubscribeToken))));
    expect(server.preferences['email_notifications'], isTrue);
  });

  testWidgets('the button calls the route, then points to the account',
      (tester) async {
    await start(tester, link);

    await tester.tap(find.widgetWithText(FilledButton, stop));
    await tester.pumpAndSettle();

    expect(server.calls, contains(unsubscribeCall(kUnsubscribeToken)));
    expect(server.preferences['email_notifications'], isFalse);
    expect(
      find.text(
        'Email notifications are off. You can turn them back on from your '
        'account.',
      ),
      findsOneWidget,
    );
    expect(find.text(stop), findsNothing);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Go to my account'));
    await tester.pumpAndSettle();

    // Signed out: to sign-in, on the way to the account.
    expect(find.byType(SignInScreen), findsOneWidget);
    expect(location(tester).queryParameters['from'], '/account');
  });

  testWidgets('signed in, it works and sends no session', (tester) async {
    await start(tester, link, signedIn: true);

    await tester.tap(find.widgetWithText(FilledButton, stop));
    await tester.pumpAndSettle();

    expect(server.preferences['email_notifications'], isFalse);
    expect(server.unsubscribeSessions, [null]);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Go to my account'));
    await tester.pumpAndSettle();

    expect(find.byType(AccountScreen), findsOneWidget);
    expect(server.preferences['email_notifications'], isFalse);
  });

  testWidgets('no token: an invalid link, and no call', (tester) async {
    await start(tester, '/unsubscribe');

    expect(find.text(invalid), findsOneWidget);
    expect(find.text(stop), findsNothing);
    expect(
      server.calls.where((call) => call.startsWith('POST /api/unsubscribe')),
      isEmpty,
    );
  });

  testWidgets('a token the server refuses: an invalid link', (tester) async {
    await start(tester, '/unsubscribe#v1.forged.token');

    await tester.tap(find.widgetWithText(FilledButton, stop));
    await tester.pumpAndSettle();

    expect(find.text(invalid), findsOneWidget);
    expect(server.preferences['email_notifications'], isTrue);
  });

  testWidgets('a server error offers a retry, keeping the token',
      (tester) async {
    server.status[unsubscribeCall(kUnsubscribeToken)] = 500;
    await start(tester, link);

    await tester.tap(find.widgetWithText(FilledButton, stop));
    await tester.pumpAndSettle();

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );

    server.status.remove(unsubscribeCall(kUnsubscribeToken));
    await tester.tap(find.widgetWithText(OutlinedButton, 'Try again'));
    await tester.pumpAndSettle();

    expect(server.preferences['email_notifications'], isFalse);
  });

  testWidgets('a token with reserved characters stays one path segment',
      (tester) async {
    await start(tester, '/unsubscribe#a/b');

    await tester.tap(find.widgetWithText(FilledButton, stop));
    await tester.pumpAndSettle();

    expect(server.calls, contains('POST /api/unsubscribe/a%2Fb'));
    expect(find.text(invalid), findsOneWidget);
  });

  testWidgets('in French on a French device', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await start(tester, link);

    expect(find.text('Notifications par e-mail'), findsOneWidget);
    await tester.tap(
      find.widgetWithText(
        FilledButton,
        'Arrêter les notifications par e-mail',
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text(
        'Les notifications par e-mail sont désactivées. Vous pouvez les '
        'réactiver depuis votre compte.',
      ),
      findsOneWidget,
    );
  });
}
