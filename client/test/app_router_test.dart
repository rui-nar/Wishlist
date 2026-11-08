import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:wishlist/src/app_router.dart';
import 'package:wishlist/src/auth/account_screen.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';
import 'package:wishlist/src/home/home_screen.dart';
import 'package:wishlist/src/version_screen.dart';

import 'support/fakes.dart';

void main() {
  group('authRedirect', () {
    String? redirect(AuthStatus status, String location) =>
        authRedirect(status, Uri.parse(location));

    test('signed out: to sign-in, with where the user was going', () {
      final target = redirect(AuthStatus.signedOut, '/account');
      expect(target, isNotNull);
      final uri = Uri.parse(target!);
      expect(uri.path, '/sign-in');
      expect(uri.queryParameters['from'], '/account');

      expect(
        Uri.parse(redirect(AuthStatus.failed, '/about?x=1')!)
            .queryParameters['from'],
        '/about?x=1',
      );
      // Home needs no return: it is where sign-in goes by default.
      expect(redirect(AuthStatus.signedOut, '/'), '/sign-in');
      expect(redirect(AuthStatus.signedOut, '/sign-in?from=/account'), isNull);
      expect(redirect(AuthStatus.signingIn, '/sign-in'), isNull);
    });

    test('signed in: back to from, or home', () {
      expect(
        redirect(AuthStatus.signedIn, '/sign-in?from=%2Faccount'),
        '/account',
      );
      expect(redirect(AuthStatus.signedIn, '/sign-in'), '/');
      expect(redirect(AuthStatus.signedIn, '/account'), isNull);
    });

    test('while the session is restored or unconfirmed: no decision', () {
      expect(redirect(AuthStatus.restoring, '/account'), isNull);
      expect(redirect(AuthStatus.unavailable, '/account'), isNull);
    });

    test('a from that leaves the app is ignored', () {
      for (final from in [
        'https://evil.example/',
        '//evil.example/account',
        r'/\evil.example',
        '/\t/evil.example',
        'javascript:alert(1)',
        'account',
        '',
        '/sign-in?from=/account',
      ]) {
        final location =
            Uri(path: '/sign-in', queryParameters: {'from': from}).toString();
        expect(redirect(AuthStatus.signedIn, location), '/', reason: from);
      }
    });

    test('a from inside the app is kept, query included', () {
      expect(safeFrom('/join'), '/join');
      expect(safeFrom('/account?tab=1'), '/account?tab=1');
    });
  });

  group('in the app', () {
    late FakeServer server;

    setUp(() {
      server = FakeServer();
      installFakeGoogleSignIn();
    });

    Uri location(WidgetTester tester) => GoRouter.of(
          tester.element(find.byType(Scaffold).last),
        ).routerDelegate.currentConfiguration.uri;

    Future<AuthController> start(
      WidgetTester tester,
      String at, {
      MemoryTokenStore? store,
    }) async {
      tester.platformDispatcher.defaultRouteNameTestValue = at;
      addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
      final app = buildApp(server, store: store);
      await tester.pumpWidget(app.app);
      await app.auth.restore();
      await tester.pumpAndSettle();
      return app.auth;
    }

    testWidgets('signed out, /account goes to sign-in, and back after it',
        (tester) async {
      final auth = await start(tester, '/account');

      expect(find.byType(SignInScreen), findsOneWidget);
      expect(location(tester).path, '/sign-in');
      expect(location(tester).queryParameters['from'], '/account');

      await auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();

      expect(find.byType(AccountScreen), findsOneWidget);
      expect(location(tester).toString(), '/account');
    });

    testWidgets('a crafted from lands on home after sign-in', (tester) async {
      final auth = await start(tester, '/sign-in?from=%2F%2Fevil.example');

      await auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();

      expect(find.byType(HomeScreen), findsOneWidget);
      expect(location(tester).toString(), '/');
    });

    testWidgets('a stored session opens the asked location directly',
        (tester) async {
      await start(
        tester,
        '/account',
        store: MemoryTokenStore(server.addSession()),
      );

      expect(find.byType(AccountScreen), findsOneWidget);
      expect(server.calls, isNot(contains('GET /api/config')));
    });

    testWidgets('home shows My lists and opens the account screen',
        (tester) async {
      await start(tester, '/', store: MemoryTokenStore(server.addSession()));

      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.widgetWithText(AppBar, 'My lists'), findsOneWidget);
      expect(server.calls, contains('GET /api/lists'));
      await tester.tap(find.byTooltip('Account'));
      await tester.pumpAndSettle();
      expect(find.byType(AccountScreen), findsOneWidget);
    });

    testWidgets('the version screen is reachable from the account screen',
        (tester) async {
      await start(
        tester,
        '/account',
        store: MemoryTokenStore(server.addSession()),
      );

      await tester.tap(find.text('About this app'));
      await tester.pumpAndSettle();

      expect(find.byType(VersionScreen), findsOneWidget);
      expect(find.text('App v1.2.3'), findsOneWidget);
      expect(find.text('Server v1.2.0 (validation)'), findsOneWidget);
    });

    testWidgets(
        'signing out shows sign-in; signing in again returns to the account',
        (tester) async {
      final auth = await start(
        tester,
        '/account',
        store: MemoryTokenStore(server.addSession()),
      );

      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();
      expect(find.byType(SignInScreen), findsOneWidget);

      await auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();
      expect(find.byType(AccountScreen), findsOneWidget);
    });

    testWidgets('a server error at start offers a retry, keeping the session',
        (tester) async {
      final store = MemoryTokenStore(server.addSession());
      server.status['GET /api/me'] = 500;
      await start(tester, '/account', store: store);

      expect(find.text('Server unreachable'), findsOneWidget);
      expect(find.byType(SignInScreen), findsNothing);

      server.status.remove('GET /api/me');
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.byType(AccountScreen), findsOneWidget);
    });
  });
}
