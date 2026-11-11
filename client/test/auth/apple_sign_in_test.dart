import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/apple_sign_in.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';

import '../support/fakes.dart';

void main() {
  const button = 'Continue with Apple';
  const notAvailable = 'Sign-in is not available on this server yet.';
  const incomplete = 'Apple sign-in did not complete. Try again.';
  const refused = 'Apple sign-in could not be verified. Try again.';
  const usual = 'If you usually sign in with Google or Apple, use that button.';
  const onlyGooglePrompt = 'Your Google account is all you need.';
  const choosePrompt = 'Choose how you want to sign up.';

  late FakeServer server;
  late FakeAppleSignIn apple;
  late AuthController auth;

  setUp(() {
    server = FakeServer(
      appleClientId: kAppleClientId,
      appleRedirectUri: kAppleRedirectUri,
    );
    installFakeGoogleSignIn();
    apple = installFakeAppleSignIn();
    auth = AuthController(
      api: ApiClient(server.client, baseUrl: kApiBase),
      store: MemoryTokenStore(),
    );
  });

  Future<void> pumpSignIn(
    WidgetTester tester, {
    bool register = false,
  }) async {
    await auth.restore();
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(
          value: ApiClient(server.client, baseUrl: kApiBase),
        ),
        ChangeNotifierProvider<AuthController>.value(value: auth),
      ],
      child: localizedApp(SignInScreen(register: register)),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> tapApple(WidgetTester tester) async {
    await tester.tap(find.text(button));
    await tester.pumpAndSettle();
  }

  group('offered by the server (D18, D21)', () {
    testWidgets('not offered without a client ID', (tester) async {
      server.appleClientId = null;

      await pumpSignIn(tester);

      expect(find.text(button), findsNothing);
      expect(find.text('Continue with Google'), findsOneWidget);
    });

    testWidgets('not offered without a redirect address', (tester) async {
      server.appleRedirectUri = null;

      await pumpSignIn(tester);

      expect(find.text(button), findsNothing);
    });

    testWidgets('nothing configured: "not available"', (tester) async {
      server
        ..googleClientId = null
        ..appleClientId = null
        ..appleRedirectUri = null;

      await pumpSignIn(tester);

      expect(find.text(notAvailable), findsOneWidget);
      expect(find.text(button), findsNothing);
    });

    testWidgets('Apple alone: its button, no "not available"', (tester) async {
      server.googleClientId = null;

      await pumpSignIn(tester);

      expect(find.text(button), findsOneWidget);
      expect(find.text(notAvailable), findsNothing);
      expect(find.text('Continue with Google'), findsNothing);
    });

    testWidgets('with Google: both', (tester) async {
      await pumpSignIn(tester);

      expect(find.text(button), findsOneWidget);
      expect(find.text('Continue with Google'), findsOneWidget);
      // No form to warn about.
      expect(find.text(usual), findsNothing);
    });

    testWidgets('Apple and email: D21 points at the button', (tester) async {
      server
        ..googleClientId = null
        ..emailSignIn = true;

      await pumpSignIn(tester);

      expect(find.text(button), findsOneWidget);
      expect(find.text(usual), findsOneWidget);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);

      await pumpSignIn(tester);

      expect(find.text('Continuer avec Apple'), findsOneWidget);
    });

    // IOS_APP_PLAN D3, D4: an iOS build without Google's iOS client.
    testWidgets('iOS without Google: Apple and email, and Apple signs in',
        (tester) async {
      server.emailSignIn = true;

      await pumpSignIn(tester);

      expect(find.text('Continue with Google'), findsNothing);
      expect(find.text(button), findsOneWidget);
      expect(find.text(usual), findsOneWidget);

      await tapApple(tester);

      expect(server.calls, contains('POST /api/auth/apple'));
      expect(auth.status, AuthStatus.signedIn);
    }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
  });

  group('the register prompt', () {
    testWidgets('Google alone: a Google account is all you need',
        (tester) async {
      server
        ..appleClientId = null
        ..appleRedirectUri = null;

      await pumpSignIn(tester, register: true);

      expect(find.text(onlyGooglePrompt), findsOneWidget);
      expect(find.text(choosePrompt), findsNothing);
    });

    testWidgets('with Apple: it does not say so', (tester) async {
      await pumpSignIn(tester, register: true);

      expect(find.text(choosePrompt), findsOneWidget);
      expect(find.text(onlyGooglePrompt), findsNothing);
    });

    testWidgets('with email: it does not say so', (tester) async {
      server
        ..appleClientId = null
        ..appleRedirectUri = null
        ..emailSignIn = true;

      await pumpSignIn(tester, register: true);

      expect(find.text(choosePrompt), findsOneWidget);
      expect(find.text(onlyGooglePrompt), findsNothing);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);

      await pumpSignIn(tester, register: true);

      expect(find.text('Choisissez comment vous inscrire.'), findsOneWidget);
      expect(find.text('Votre compte Google suffit.'), findsNothing);
    });
  });

  group('signing in (D15, D16)', () {
    testWidgets('Apple gets the hash, the server the raw nonce',
        (tester) async {
      await pumpSignIn(tester);

      await tapApple(tester);

      final body = server.appleBodies.single;
      final raw = body['nonce'] as String;
      final hashed = apple.nonces.single!;
      expect(hashed, matches(RegExp(r'^[0-9a-f]{64}$')));
      expect(hashed, sha256.convert(utf8.encode(raw)).toString());
      expect(raw, isNot(hashed));
      expect(body['id_token'], kValidAppleIdToken);
      expect(auth.status, AuthStatus.signedIn);
    });

    testWidgets('each attempt has its own nonce', (tester) async {
      await pumpSignIn(tester);

      await tapApple(tester);
      await tapApple(tester);

      expect(apple.nonces.toSet(), hasLength(2));
    });

    testWidgets("asks for the address and name, with the server's values",
        (tester) async {
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(apple.scopes.single, [
        AppleIDAuthorizationScopes.email,
        AppleIDAuthorizationScopes.fullName,
      ]);
      expect(apple.options.single!.clientId, kAppleClientId);
      expect(apple.options.single!.redirectUri.toString(), kAppleRedirectUri);
    });

    testWidgets('the name of the first authorisation reaches the server',
        (tester) async {
      apple.credential = FakeAppleSignIn.appleCredential(
        givenName: ' Alice ',
        familyName: 'Martin',
      );
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(server.appleBodies.single['name'], 'Alice Martin');
    });

    testWidgets('later authorisations send no name', (tester) async {
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(server.appleBodies.single.containsKey('name'), isFalse);
    });
  });

  group('cancelling is not a failure', () {
    final cancellations = <String, Object>{
      'Android or a native sheet': const SignInWithAppleAuthorizationException(
        code: AuthorizationErrorCode.canceled,
        message: 'canceled',
      ),
      'the web popup closed': const SignInWithAppleCredentialsException(
        message: 'Authentication failed with popup_closed_by_user',
      ),
      'the web cancel button': const SignInWithAppleCredentialsException(
        message: 'Authentication failed with user_cancelled_authorize',
      ),
    };
    for (final MapEntry(key: name, value: error) in cancellations.entries) {
      testWidgets(name, (tester) async {
        apple.error = error;
        await pumpSignIn(tester);

        await tapApple(tester);

        expect(find.text(incomplete), findsNothing);
        expect(auth.status, AuthStatus.signedOut);
        expect(server.appleBodies, isEmpty);
        expect(find.text(button), findsOneWidget);
      });
    }
  });

  group('failures', () {
    final failures = <String, Object>{
      "Apple's error": const SignInWithAppleAuthorizationException(
        code: AuthorizationErrorCode.failed,
        message: 'failed',
      ),
      'a popup the browser blocked': const SignInWithAppleCredentialsException(
        message: 'Authentication failed with popup_blocked_by_browser',
      ),
      // What the web plugin ends up with when Apple's script did not load.
      "Apple's script missing": TypeError(),
    };
    for (final MapEntry(key: name, value: error) in failures.entries) {
      testWidgets('$name: says so, and can be tried again', (tester) async {
        apple.error = error;
        await pumpSignIn(tester);

        await tapApple(tester);

        expect(find.text(incomplete), findsOneWidget);
        expect(server.appleBodies, isEmpty);

        apple.error = null;
        await tapApple(tester);

        expect(auth.status, AuthStatus.signedIn);
      });
    }

    testWidgets('an answer without a token says so', (tester) async {
      apple.credential = FakeAppleSignIn.appleCredential(identityToken: null);
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(find.text(incomplete), findsOneWidget);
      expect(server.appleBodies, isEmpty);
    });

    testWidgets('a token the server refuses says so', (tester) async {
      apple.credential =
          FakeAppleSignIn.appleCredential(identityToken: 'forged');
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(find.text(refused), findsOneWidget);
      expect(auth.failure, SignInFailure.appleRejected);
      // Not Google's message.
      expect(find.text('Google sign-in could not be verified. Try again.'),
          findsNothing);
    });

    testWidgets('Apple unreachable from the server is a server error',
        (tester) async {
      server.status['POST /api/auth/apple'] = 502;
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(find.text('The server could not complete the request. Try again.'),
          findsOneWidget);
    });

    testWidgets('too many attempts says so', (tester) async {
      server.status['POST /api/auth/apple'] = 429;
      await pumpSignIn(tester);

      await tapApple(tester);

      expect(find.text('Too many attempts. Try again in a few minutes.'),
          findsOneWidget);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      apple.error = TypeError();
      await pumpSignIn(tester);

      await tester.tap(find.text('Continuer avec Apple'));
      await tester.pumpAndSettle();

      expect(find.text("La connexion Apple n'a pas abouti. Réessayez."),
          findsOneWidget);
    });

    testWidgets("Apple's failure replaces a failed Google initialisation",
        (tester) async {
      installFakeGoogleSignIn().initError = StateError('bad client ID');
      apple.error = TypeError();
      await pumpSignIn(tester);
      expect(find.text('Google sign-in did not complete. Try again.'),
          findsOneWidget);

      await tapApple(tester);

      expect(find.text(incomplete), findsOneWidget);
      expect(find.text('Google sign-in did not complete. Try again.'),
          findsNothing);
      // Retrying must not bring back the spinner of an initialisation that
      // is over.
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });
  });

  // On Android, closing the tab can leave the first request pending for ever.
  testWidgets('the button still works while an attempt is pending',
      (tester) async {
    final abandoned = apple.pending = Completer();
    await pumpSignIn(tester);

    await tester.tap(find.text(button));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsNothing);

    apple.pending = null;
    await tapApple(tester);

    expect(apple.nonces, hasLength(2));
    expect(auth.status, AuthStatus.signedIn);

    // The plugin rejects the abandoned request; nobody is waiting for it.
    abandoned.completeError(
      const SignInWithAppleCredentialsException(message: 'NEW_REQUEST'),
    );
    await tester.pumpAndSettle();
    expect(auth.status, AuthStatus.signedIn);
    expect(server.appleBodies, hasLength(1));
  });

  group('the name the server would refuse is not sent (D13)', () {
    test('control characters', () {
      expect(appleDisplayName('Al\u0007ice', null), isNull);
    });

    test('bidirectional overrides', () {
      for (final override in [0x202e, 0x2066]) {
        final name = 'Al${String.fromCharCode(override)}ice';
        expect(appleDisplayName(name, null), isNull);
      }
    });

    test('more than 100 characters', () {
      expect(appleDisplayName('a' * 101, null), isNull);
      expect(appleDisplayName('a' * 100, null), 'a' * 100);
    });

    test('counted in characters, as the server does', () {
      expect(appleDisplayName('\u{1F381}' * 100, null), '\u{1F381}' * 100);
    });

    test('blank parts', () {
      expect(appleDisplayName(null, null), isNull);
      expect(appleDisplayName('  ', ''), isNull);
      expect(appleDisplayName(null, 'Martin'), 'Martin');
    });

    test('joiners and non-breaking spaces are text', () {
      expect(appleDisplayName('Anne Marie', null), 'Anne Marie');
    });
  });

  // The script loads on demand, from the sign-in screen only: a visitor
  // following a share link sends nothing to Apple, and the page cannot depend
  // on a script that is blocked or not configured.
  test('only the sign-in screen loads Apple\'s script', () {
    expect(File('web/index.html').readAsStringSync(),
        isNot(contains('appleid')));
    final callers = <String>[
      for (final f in Directory('lib').listSync(recursive: true))
        if (f is File &&
            f.path.endsWith('.dart') &&
            !f.path.contains('apple_script_') &&
            f.readAsStringSync().contains('loadAppleScript('))
          f.path.replaceAll(r'\', '/'),
    ];
    expect(callers, ['lib/src/auth/sign_in_screen.dart']);
  });

  test("Android's callback activity is in the manifest", () {
    final manifest =
        File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    expect(
      manifest,
      contains(
        'com.aboutyou.dart_packages.sign_in_with_apple.SignInWithAppleCallback',
      ),
    );
    expect(manifest, contains('android:scheme="signinwithapple"'));
    // The custom tab must be able to return to the running app.
    expect(manifest, contains('android:launchMode="singleTop"'));
  });
}
