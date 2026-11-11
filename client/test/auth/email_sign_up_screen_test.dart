import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shushgift/main.dart';
import 'package:shushgift/src/api/api_client.dart';
import 'package:shushgift/src/auth/auth_controller.dart';
import 'package:shushgift/src/auth/email_sign_up_screen.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/intro/intro_seen.dart';
import 'package:shushgift/src/shared/pending_join.dart';

import '../support/fakes.dart';

void main() {
  const address = 'Email address';
  const send = 'Send the link';
  const startCall = 'POST /api/auth/email/start';

  late FakeServer server;

  setUp(() {
    server = FakeServer(emailSignIn: true);
    installFakeGoogleSignIn();
    // This device has seen the introduction: these tests are about the
    // pages before home.
    SharedPreferences.setMockInitialValues({kIntroSeenKey: true});
  });

  Finder field() => find.widgetWithText(TextFormField, address);

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).last),
      ).routerDelegate.currentConfiguration.uri;

  Future<void> open(WidgetTester tester, {String at = '/email-sign-up'}) async {
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
  }

  Future<void> sendTo(WidgetTester tester, String email) async {
    await tester.enterText(field(), email);
    await tester.tap(find.widgetWithText(FilledButton, send));
    await tester.pumpAndSettle();
  }

  testWidgets('open signed out; asks for the address and sends nothing yet',
      (tester) async {
    await open(tester);

    expect(find.byType(EmailSignUpScreen), findsOneWidget);
    expect(find.byType(SignInScreen), findsNothing);
    expect(field(), findsOneWidget);
    expect(server.calls, isNot(contains(startCall)));
    expect(
      tester
          .widget<TextField>(
            find.descendant(of: field(), matching: find.byType(TextField)),
          )
          .autofillHints,
      [AutofillHints.email],
    );
  });

  testWidgets('sends the trimmed address and language; says to check the inbox',
      (tester) async {
    await open(tester);

    await sendTo(tester, ' alice@example.com ');

    expect(server.emailBodies[startCall], {
      'email': 'alice@example.com',
      'language': 'en',
    });
    expect(find.text('Check your inbox'), findsOneWidget);
    expect(
      find.text(
        'A link is on its way to alice@example.com. It should arrive within '
        'about a minute and works for one hour. If you cannot find it, look '
        'in your spam folder.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('the language is the device\'s', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await open(tester);

    await tester.enterText(
      find.widgetWithText(TextFormField, 'Adresse e-mail'),
      'alice@example.com',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Envoyer le lien'));
    await tester.pumpAndSettle();

    expect(server.emailBodies[startCall]!['language'], 'fr');
    expect(find.text('Consultez votre boîte de réception'), findsOneWidget);
    expect(find.textContaining("d'ici environ une minute"), findsOneWidget);
    expect(find.textContaining('courriers indésirables'), findsOneWidget);
  });

  testWidgets('a malformed address is not sent', (tester) async {
    await open(tester);

    await sendTo(tester, 'not an address');

    expect(find.text('Enter a valid email address.'), findsOneWidget);
    expect(server.calls, isNot(contains(startCall)));
  });

  for (final (code, message) in [
    (429, 'Too many attempts. Try again in a few minutes.'),
    (503, 'Sign-in is not available on this server yet.'),
    (422, 'Enter a valid email address.'),
    (500, 'The server could not complete the request. Try again.'),
  ]) {
    testWidgets('a $code stays on the form and says why', (tester) async {
      server.status[startCall] = code;
      await open(tester);

      await sendTo(tester, 'alice@example.com');

      expect(find.text(message), findsOneWidget);
      expect(find.text('Check your inbox'), findsNothing);
      expect(field(), findsOneWidget);
    });
  }

  testWidgets('a different address returns to the form', (tester) async {
    await open(tester);
    await sendTo(tester, 'alice@example.com');

    await tester.tap(find.text('Use a different address'));
    await tester.pumpAndSettle();

    expect(field(), findsOneWidget);
    expect(find.text('Check your inbox'), findsNothing);
  });

  testWidgets('back to sign-in keeps where the user was going', (tester) async {
    await open(tester, at: '/email-sign-up?from=%2Faccount');

    await tester.tap(find.text('Back to sign-in'));
    await tester.pumpAndSettle();

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(location(tester).path, '/sign-in');
    expect(location(tester).queryParameters, {'from': '/account'});
  });

  testWidgets('signed in, the page goes home', (tester) async {
    tester.platformDispatcher.defaultRouteNameTestValue = '/email-sign-up';
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: MemoryTokenStore(server.addSession()));
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();

    expect(location(tester).toString(), '/');
  });

  testWidgets('hands a pending occasion link over for the mailed link (D19)',
      (tester) async {
    tester.platformDispatcher.defaultRouteNameTestValue = '/email-sign-up';
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final api = ApiClient(server.client, baseUrl: kApiBase);
    final auth = AuthController(api: api, store: MemoryTokenStore());
    final pendingJoin = PendingJoin(MemoryJoinBrowser('share'), 'share');
    await tester.pumpWidget(ShushGiftApp(
      api: api,
      auth: auth,
      appVersion: 'v1.2.3',
      pendingJoin: pendingJoin,
    ));
    await auth.restore();
    await tester.pumpAndSettle();

    await sendTo(tester, 'alice@example.com');

    final otherTab = PendingJoin(MemoryJoinBrowser());
    await otherTab.resumeAfterEmailLink();
    expect(otherTab.token, 'share');
  });
}
