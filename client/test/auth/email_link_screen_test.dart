import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/email_link_screen.dart';
import 'package:wishlist/src/auth/email_sign_up_screen.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';
import 'package:wishlist/src/home/home_screen.dart';
import 'package:wishlist/src/intro/intro_seen.dart';
import 'package:wishlist/src/shared/join_screen.dart';
import 'package:wishlist/src/shared/pending_join.dart';

import '../support/fakes.dart';

void main() {
  const completeCall = 'POST /api/auth/email/complete';
  const createLink = '/create-account#$kEmailLinkToken';
  const resetLink = '/reset-password#$kEmailLinkToken';
  const name = 'Your name';
  const create = 'Create my account';
  const reset = 'Save my password';
  const expired =
      'This link has expired or has already been used. You can ask for a new one.';

  late FakeServer server;

  setUp(() {
    server = FakeServer(emailSignIn: true);
    installFakeGoogleSignIn();
    // This device has seen the introduction: these tests are about the
    // pages before home.
    SharedPreferences.setMockInitialValues({kIntroSeenKey: true});
  });

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).last),
      ).routerDelegate.currentConfiguration.uri;

  Finder field(String label) => find.widgetWithText(TextFormField, label);

  Future<AuthController> open(
    WidgetTester tester,
    String at, {
    MemoryTokenStore? store,
    PendingJoin? pendingJoin,
    String? emailLinkToken,
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final api = ApiClient(server.client, baseUrl: kApiBase);
    final auth = AuthController(api: api, store: store ?? MemoryTokenStore());
    await tester.pumpWidget(WishlistApp(
      api: api,
      auth: auth,
      appVersion: 'v1.2.3',
      pendingJoin: pendingJoin,
      emailLinkToken: emailLinkToken,
    ));
    await auth.restore();
    await tester.pumpAndSettle();
    return auth;
  }

  Future<void> fillAndSend(
    WidgetTester tester, {
    String? displayName,
    required String passwordLabel,
    required String password,
    required String button,
  }) async {
    if (displayName != null) {
      await tester.enterText(field(name), displayName);
    }
    await tester.enterText(field(passwordLabel), password);
    await tester.tap(find.widgetWithText(FilledButton, button));
    await tester.pumpAndSettle();
  }

  group('/create-account', () {
    testWidgets('open signed out; nothing sent before the button',
        (tester) async {
      await open(tester, createLink);

      expect(find.byType(EmailLinkScreen), findsOneWidget);
      expect(find.byType(SignInScreen), findsNothing);
      expect(field(name), findsOneWidget);
      expect(server.calls, isNot(contains(completeCall)));
    });

    testWidgets('the token captured at start is used when the address has none',
        (tester) async {
      await open(tester, '/create-account', emailLinkToken: kEmailLinkToken);

      await fillAndSend(
        tester,
        displayName: 'Alice',
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      expect(server.emailBodies[completeCall]!['token'], kEmailLinkToken);
    });

    testWidgets('sends the name and password, signs in, and goes home',
        (tester) async {
      final auth = await open(tester, createLink);

      await fillAndSend(
        tester,
        displayName: '  Alice  ',
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      expect(server.emailBodies[completeCall], {
        'token': kEmailLinkToken,
        'password': kEmailPassword,
        'display_name': 'Alice',
      });
      expect(auth.status, AuthStatus.signedIn);
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(location(tester).toString(), '/');
    });

    testWidgets('the name is required', (tester) async {
      await open(tester, createLink);

      await fillAndSend(
        tester,
        displayName: '   ',
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      expect(find.text('Enter your name.'), findsOneWidget);
      expect(server.calls, isNot(contains(completeCall)));
    });

    testWidgets('a name over 100 characters is refused here', (tester) async {
      await open(tester, createLink);

      await fillAndSend(
        tester,
        displayName: 'a' * 101,
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      expect(find.text('Use at most 100 characters.'), findsOneWidget);
      expect(server.calls, isNot(contains(completeCall)));
    });

    for (final (what, password) in [
      ('short', 'a' * 9),
      ('long', 'a' * 129),
    ]) {
      testWidgets('a password too $what is refused here', (tester) async {
        await open(tester, createLink);

        await fillAndSend(
          tester,
          displayName: 'Alice',
          passwordLabel: 'Choose a password',
          password: password,
          button: create,
        );

        expect(find.text('Use 10 to 128 characters.'), findsOneWidget);
        expect(server.calls, isNot(contains(completeCall)));
      });
    }

    testWidgets('the fields carry the autofill hints for a new password',
        (tester) async {
      await open(tester, createLink);

      TextField text(String label) => tester.widget<TextField>(
            find.descendant(
              of: field(label),
              matching: find.byType(TextField),
            ),
          );

      expect(text(name).autofillHints, [AutofillHints.name]);
      expect(
        text('Choose a password').autofillHints,
        [AutofillHints.newPassword],
      );
      expect(text('Choose a password').obscureText, isTrue);
    });
  });

  group('/reset-password', () {
    testWidgets('asks for no name, sends none, signs in', (tester) async {
      final auth = await open(tester, resetLink);

      expect(field(name), findsNothing);
      await fillAndSend(
        tester,
        passwordLabel: 'New password',
        password: kEmailPassword,
        button: reset,
      );

      expect(server.emailBodies[completeCall], {
        'token': kEmailLinkToken,
        'password': kEmailPassword,
      });
      expect(auth.status, AuthStatus.signedIn);
      expect(find.byType(HomeScreen), findsOneWidget);
    });

    testWidgets('a password too short is refused here', (tester) async {
      await open(tester, resetLink);

      await fillAndSend(
        tester,
        passwordLabel: 'New password',
        password: 'short',
        button: reset,
      );

      expect(find.text('Use 10 to 128 characters.'), findsOneWidget);
    });
  });

  group('failures', () {
    testWidgets('no token: says the link cannot be used, offers a new one',
        (tester) async {
      await open(tester, '/create-account');

      expect(find.text(expired), findsOneWidget);

      await tester.tap(find.text('Get a new link'));
      await tester.pumpAndSettle();

      expect(find.byType(EmailSignUpScreen), findsOneWidget);
    });

    testWidgets('410: says the link expired and offers a new one',
        (tester) async {
      await open(tester, '/reset-password#forged');

      await fillAndSend(
        tester,
        passwordLabel: 'New password',
        password: kEmailPassword,
        button: reset,
      );

      expect(find.text(expired), findsOneWidget);
      expect(find.text('Get a new link'), findsOneWidget);
      expect(field('New password'), findsNothing);
    });

    for (final (code, message) in [
      (429, 'Too many attempts. Try again in a few minutes.'),
      (422, 'Check your name and password, then try again.'),
      (500, 'The server could not complete the request. Try again.'),
    ]) {
      testWidgets('a $code stays on the form and says why', (tester) async {
        server.status[completeCall] = code;
        final auth = await open(tester, resetLink);

        await fillAndSend(
          tester,
          passwordLabel: 'New password',
          password: kEmailPassword,
          button: reset,
        );

        expect(find.text(message), findsOneWidget);
        expect(field('New password'), findsOneWidget);
        expect(auth.status, AuthStatus.signedOut);
      });
    }

    testWidgets('a used link leaves the session of whoever is signed in',
        (tester) async {
      final store = MemoryTokenStore(server.addSession());
      final session = store.token;
      final auth = await open(tester, '/reset-password#forged', store: store);

      await fillAndSend(
        tester,
        passwordLabel: 'New password',
        password: kEmailPassword,
        button: reset,
      );

      expect(find.text(expired), findsOneWidget);
      expect(auth.status, AuthStatus.signedIn);
      expect(store.token, session);
    });
  });

  group('a pending occasion link (D19)', () {
    testWidgets('after the link, the occasion from the other tab opens',
        (tester) async {
      await PendingJoin(MemoryJoinBrowser('share'), 'share')
          .handOverForEmailLink();
      // The new tab: nothing pending of its own.
      final pendingJoin = PendingJoin(MemoryJoinBrowser());
      await open(tester, createLink, pendingJoin: pendingJoin);

      await fillAndSend(
        tester,
        displayName: 'Alice',
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      // The join screen found the token and asked what it joins.
      expect(server.calls, contains('POST /api/join/preview'));
      expect(find.byType(JoinScreen), findsOneWidget);
      expect(location(tester).toString(), '/join');
    });

    testWidgets('nothing handed over: home', (tester) async {
      await open(tester, createLink);

      await fillAndSend(
        tester,
        displayName: 'Alice',
        passwordLabel: 'Choose a password',
        password: kEmailPassword,
        button: create,
      );

      expect(find.byType(HomeScreen), findsOneWidget);
    });
  });

  testWidgets('in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await open(tester, createLink);

    expect(field('Votre nom'), findsOneWidget);
    expect(field('Choisissez un mot de passe'), findsOneWidget);
    expect(find.text('Créer mon compte'), findsOneWidget);
  });
}
