import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/email_sign_up_screen.dart';
import 'package:wishlist/src/auth/google_sign_in_init.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';

import '../support/fakes.dart';

void main() {
  late FakeServer server;
  late FakeGoogleSignIn google;
  late ApiClient api;
  late AuthController auth;

  setUp(() {
    server = FakeServer();
    google = installFakeGoogleSignIn();
    api = ApiClient(server.client, baseUrl: kApiBase);
    auth = AuthController(api: api, store: MemoryTokenStore());
  });

  Future<void> pumpSignIn(WidgetTester tester) async {
    await auth.restore();
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthController>.value(value: auth),
      ],
      child: localizedApp(const SignInScreen()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('says sign-in is not available when the server has no client ID',
      (tester) async {
    server.googleClientId = null;

    await pumpSignIn(tester);

    expect(find.text('Sign-in is not available on this server yet.'),
        findsOneWidget);
    expect(find.text('Continue with Google'), findsNothing);
    // Nothing is sent to Google without a client ID.
    expect(google.initCalls, isEmpty);
  });

  group('email sign-in (sign-in plan D18, D21)', () {
    const email = 'Email address';
    const usual = 'If you usually sign in with Google or Apple, use that button.';

    Finder field(String label) => find.widgetWithText(TextFormField, label);

    Future<void> signIn(
      WidgetTester tester,
      String address,
      String password,
    ) async {
      await tester.enterText(field(email), address);
      await tester.enterText(field('Password'), password);
      await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
      await tester.pumpAndSettle();
    }

    testWidgets('only Google: no form, as before', (tester) async {
      await pumpSignIn(tester);

      expect(find.text('Continue with Google'), findsOneWidget);
      expect(field(email), findsNothing);
      expect(find.text('Forgot your password?'), findsNothing);
      expect(find.text(usual), findsNothing);
    });

    testWidgets('Google and email: both, and D21 says which to use',
        (tester) async {
      server.emailSignIn = true;

      await pumpSignIn(tester);

      expect(find.text('Continue with Google'), findsOneWidget);
      expect(field(email), findsOneWidget);
      expect(field('Password'), findsOneWidget);
      expect(find.text(usual), findsOneWidget);
      expect(find.text('Forgot your password?'), findsOneWidget);
      expect(find.text('Create an account with your email'), findsOneWidget);
      expect(find.text('Sign-in is not available on this server yet.'),
          findsNothing);
    });

    testWidgets('email alone: the form, no Google, no "not available"',
        (tester) async {
      server.googleClientId = null;
      server.emailSignIn = true;

      await pumpSignIn(tester);

      expect(field(email), findsOneWidget);
      expect(find.text('Continue with Google'), findsNothing);
      expect(find.text('Sign-in is not available on this server yet.'),
          findsNothing);
      // D21's line has no button to point at.
      expect(find.text(usual), findsNothing);
      expect(google.initCalls, isEmpty);
    });

    testWidgets('the fields carry the autofill hints', (tester) async {
      server.emailSignIn = true;
      await pumpSignIn(tester);

      List<String>? hints(String label) => tester
          .widget<TextField>(find.descendant(
            of: field(label),
            matching: find.byType(TextField),
          ))
          .autofillHints
          ?.toList();

      expect(hints(email), [AutofillHints.email]);
      expect(hints('Password'), [AutofillHints.password]);
      expect(
        tester
            .widget<TextField>(find.descendant(
              of: field('Password'),
              matching: find.byType(TextField),
            ))
            .obscureText,
        isTrue,
      );
    });

    testWidgets('the right password signs in', (tester) async {
      server.emailSignIn = true;
      await pumpSignIn(tester);

      await signIn(tester, '  alice@example.com ', kEmailPassword);

      expect(auth.status, AuthStatus.signedIn);
      expect(server.emailBodies['POST /api/auth/email/sign-in'], {
        'email': 'alice@example.com',
        'password': kEmailPassword,
      });
    });

    testWidgets('a wrong password says so, keeping what was typed',
        (tester) async {
      server.emailSignIn = true;
      await pumpSignIn(tester);

      await signIn(tester, 'alice@example.com', 'wrong password');

      expect(find.text('Wrong email or password.'), findsOneWidget);
      expect(find.text('alice@example.com'), findsOneWidget);
      expect(auth.status, AuthStatus.failed);
    });

    testWidgets('too many attempts says so', (tester) async {
      server.emailSignIn = true;
      server.status['POST /api/auth/email/sign-in'] = 429;
      await pumpSignIn(tester);

      await signIn(tester, 'alice@example.com', kEmailPassword);

      expect(find.text('Too many attempts. Try again in a few minutes.'),
          findsOneWidget);
    });

    testWidgets('a malformed address is not sent', (tester) async {
      server.emailSignIn = true;
      await pumpSignIn(tester);

      await signIn(tester, 'not an address', kEmailPassword);

      expect(find.text('Enter a valid email address.'), findsOneWidget);
      expect(server.calls, isNot(contains('POST /api/auth/email/sign-in')));
    });

    testWidgets('an empty password is not sent', (tester) async {
      server.emailSignIn = true;
      await pumpSignIn(tester);

      await signIn(tester, 'alice@example.com', '');

      expect(find.text('Enter your password.'), findsOneWidget);
      expect(server.calls, isNot(contains('POST /api/auth/email/sign-in')));
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.emailSignIn = true;

      await pumpSignIn(tester);

      expect(find.text('Mot de passe oublié ?'), findsOneWidget);
      expect(
        find.text(
            "Si vous vous connectez d'habitude avec Google ou Apple, utilisez ce bouton."),
        findsOneWidget,
      );
    });
  });

  testWidgets('initialises Google with the client ID from /api/config',
      (tester) async {
    await pumpSignIn(tester);

    expect(server.calls, contains('GET /api/config'));
    expect(google.initCalls, hasLength(1));
    // Not a web run: Android's server client ID, so Google returns an ID
    // token for the server.
    expect(google.initCalls.single.serverClientId, 'test-client-id');
    expect(google.initCalls.single.clientId, isNull);
    expect(find.text('Wishlist'), findsOneWidget);
    expect(find.text('Continue with Google'), findsOneWidget);
  });

  testWidgets('the Google account picker signs the user in', (tester) async {
    await pumpSignIn(tester);

    await tester.tap(find.text('Continue with Google'));
    await tester.pumpAndSettle();

    expect(google.authenticateCalls, 1);
    expect(server.calls, contains('POST /api/auth/google'));
    expect(auth.status, AuthStatus.signedIn);
  });

  testWidgets('a refused Google sign-in says so', (tester) async {
    await pumpSignIn(tester);

    google.signIn('forged');
    await tester.pumpAndSettle();

    expect(auth.status, AuthStatus.failed);
    expect(find.text('Google sign-in could not be verified. Try again.'),
        findsOneWidget);
    expect(find.text('Continue with Google'), findsOneWidget);
  });

  testWidgets("a failure in Google's flow says so", (tester) async {
    await pumpSignIn(tester);

    google.fail();
    await tester.pumpAndSettle();

    expect(find.text('Google sign-in did not complete. Try again.'),
        findsOneWidget);
    expect(server.calls, isNot(contains('POST /api/auth/google')));
  });

  testWidgets('a failed Google initialisation shows no button',
      (tester) async {
    google.initError = StateError('bad client ID');

    await pumpSignIn(tester);

    expect(tester.takeException(), isNull);
    expect(find.text('Continue with Google'), findsNothing);
    expect(find.text('Google sign-in did not complete. Try again.'),
        findsOneWidget);
  });

  group('on iOS (IOS_APP_PLAN D3)', () {
    final iOS = TargetPlatformVariant.only(TargetPlatform.iOS);
    const email = 'Email address';

    testWidgets('with its own client: that client, and the web one for the '
        'server', (tester) async {
      setGoogleIosClientIdForTesting('ios-client-id');

      await pumpSignIn(tester);

      expect(google.initCalls, hasLength(1));
      expect(google.initCalls.single.clientId, 'ios-client-id');
      // The ID token's audience stays the web client the server knows.
      expect(google.initCalls.single.serverClientId, 'test-client-id');

      await tester.tap(find.text('Continue with Google'));
      await tester.pumpAndSettle();

      expect(google.authenticateCalls, 1);
      expect(auth.status, AuthStatus.signedIn);
    }, variant: iOS);

    testWidgets('built without one: no Google, and nothing sent to Google',
        (tester) async {
      server.emailSignIn = true;

      await pumpSignIn(tester);

      expect(find.text('Continue with Google'), findsNothing);
      expect(google.initCalls, isEmpty);
      expect(find.widgetWithText(TextFormField, email), findsOneWidget);
      // No Google button for D21's line to point at.
      expect(
        find.text('If you usually sign in with Google or Apple, use that button.'),
        findsNothing,
      );
    }, variant: iOS);

    testWidgets('built without one, against a server with Google only: '
        '"not available"', (tester) async {
      await pumpSignIn(tester);

      expect(find.text('Sign-in is not available on this server yet.'),
          findsOneWidget);
      expect(find.text('Continue with Google'), findsNothing);
      expect(google.initCalls, isEmpty);
    }, variant: iOS);

    testWidgets('Android ignores the iOS client', (tester) async {
      setGoogleIosClientIdForTesting('ios-client-id');

      await pumpSignIn(tester);

      expect(google.initCalls.single.clientId, isNull);
      expect(google.initCalls.single.serverClientId, 'test-client-id');
    });
  });

  testWidgets('a server error reading the configuration can be retried', (tester) async {
    server.status['GET /api/config'] = 502;

    await pumpSignIn(tester);

    expect(find.text('The server could not complete the request. Try again.'),
        findsOneWidget);
    expect(google.initCalls, isEmpty);

    server.status.remove('GET /api/config');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(find.text('Continue with Google'), findsOneWidget);
  });

  testWidgets('in French on a French device', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);

    await pumpSignIn(tester);

    expect(
      find.text(
          "Connectez-vous pour voir vos listes et celles qu'on partage avec vous."),
      findsOneWidget,
    );
    expect(find.text('Continuer avec Google'), findsOneWidget);
  });

  testWidgets('"not available" in French too', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    server.googleClientId = null;

    await pumpSignIn(tester);

    expect(
      find.text("La connexion n'est pas encore disponible sur ce serveur."),
      findsOneWidget,
    );
  });

  group('opened by the router (WEB_LAYOUT D7)', () {
    Future<void> open(WidgetTester tester, String at) async {
      tester.platformDispatcher.defaultRouteNameTestValue = at;
      addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
      final app = buildApp(server);
      await tester.pumpWidget(app.app);
      await app.auth.restore();
      await tester.pumpAndSettle();
    }

    Uri location(WidgetTester tester) => GoRouter.of(
          tester.element(find.byType(Scaffold).last),
        ).routerDelegate.currentConfiguration.uri;

    const signInPrompt =
        'Sign in to see your lists and the lists shared with you.';

    testWidgets('mode=register: the register heading and prompt',
        (tester) async {
      await open(tester, '/sign-in?mode=register');

      expect(find.text('Create your account'), findsOneWidget);
      expect(find.text('Your Google account is all you need.'),
          findsOneWidget);
      expect(find.text(signInPrompt), findsNothing);
      // The same Google sign-in, which creates the account the first time.
      expect(find.text('Continue with Google'), findsOneWidget);
    });

    for (final at in ['/sign-in', '/sign-in?mode=other', '/sign-in?mode=']) {
      testWidgets('$at: the normal heading and prompt', (tester) async {
        await open(tester, at);

        expect(find.text('Wishlist'), findsOneWidget);
        expect(find.text(signInPrompt), findsOneWidget);
        expect(find.text('Create your account'), findsNothing);
      });
    }

    testWidgets('without from: a link to the welcome page', (tester) async {
      await open(tester, '/sign-in');

      expect(find.text('What is Wishlist?'), findsOneWidget);
    });

    testWidgets('with from: no link, the visitor is mid-flow',
        (tester) async {
      await open(tester, '/sign-in?from=%2Faccount');

      expect(find.text('What is Wishlist?'), findsNothing);
    });

    for (final link in [
      'Forgot your password?',
      'Create an account with your email',
    ]) {
      testWidgets('$link opens the email page, keeping from', (tester) async {
        server.emailSignIn = true;
        await open(tester, '/sign-in?from=%2Faccount');

        await tester.tap(find.text(link));
        await tester.pumpAndSettle();

        expect(find.byType(EmailSignUpScreen), findsOneWidget);
        expect(location(tester).path, '/email-sign-up');
        expect(location(tester).queryParameters, {'from': '/account'});
      });
    }

    testWidgets('a share link goes to sign-in, with no welcome link',
        (tester) async {
      await open(tester, '/join');

      expect(find.byType(SignInScreen), findsOneWidget);
      expect(location(tester).path, '/sign-in');
      expect(location(tester).queryParameters, {'from': '/join'});
      expect(find.text('What is Wishlist?'), findsNothing);
    });
  });

  testWidgets('register mode in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await auth.restore();
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthController>.value(value: auth),
      ],
      child: localizedApp(
        const SignInScreen(register: true, offerWelcome: true),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Créez votre compte'), findsOneWidget);
    expect(find.text('Votre compte Google suffit.'), findsOneWidget);
    expect(find.text("Qu'est-ce que Wishlist ?"), findsOneWidget);
  });

  // Anything else that initialised Google sign-in, such as main(), would load
  // Google's script on every page of the web app (D11).
  test('only the sign-in screen initialises Google sign-in', () {
    final initializers = <String>[];
    final callers = <String>[];
    for (final f in Directory('lib').listSync(recursive: true)) {
      if (f is! File || !f.path.endsWith('.dart')) continue;
      final src = f.readAsStringSync();
      final path = f.path.replaceAll(r'\', '/');
      if (src.contains('GoogleSignIn.instance.initialize(')) {
        initializers.add(path);
      }
      if (src.contains('ensureGoogleSignInInitialized(') &&
          !path.endsWith('google_sign_in_init.dart')) {
        callers.add(path);
      }
    }
    expect(initializers, ['lib/src/auth/google_sign_in_init.dart']);
    expect(callers, ['lib/src/auth/sign_in_screen.dart']);
  });
}
