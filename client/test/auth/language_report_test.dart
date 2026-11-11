import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/auth/auth_controller.dart';

import '../support/fakes.dart';

/// The app reports the language it displays (COMMENTS_NOTIFICATIONS_PLAN D17,
/// D20).
void main() {
  late FakeServer server;

  setUp(() {
    server = FakeServer();
    installFakeGoogleSignIn();
  });

  Future<AuthController> start(
    WidgetTester tester, {
    required bool signedIn,
    String at = '/welcome',
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    final app = buildApp(
      server,
      store: MemoryTokenStore(signedIn ? server.addSession() : null),
    );
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  const fr = [Locale('fr', 'FR')];

  testWidgets('reported once after a session is restored', (tester) async {
    await start(tester, signedIn: true, at: '/account');

    expect(server.preferencePatches, [
      {'language': 'en'},
    ]);

    // Another screen, and a rebuild: nothing more to say.
    await tester.pump();
    await tester.pumpAndSettle();
    expect(server.preferencePatches, hasLength(1));
  });

  testWidgets('reported in the language displayed', (tester) async {
    tester.platformDispatcher.localesTestValue = fr;
    await start(tester, signedIn: true, at: '/account');

    expect(server.preferencePatches, [
      {'language': 'fr'},
    ]);
  });

  testWidgets('a device language the app lacks reports English',
      (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('de', 'DE')];
    await start(tester, signedIn: true, at: '/account');

    expect(server.preferencePatches, [
      {'language': 'en'},
    ]);
  });

  testWidgets('reported again after a locale change', (tester) async {
    await start(tester, signedIn: true, at: '/account');

    tester.platformDispatcher.localesTestValue = fr;
    await tester.pumpAndSettle();

    expect(server.preferencePatches, [
      {'language': 'en'},
      {'language': 'fr'},
    ]);
  });

  testWidgets('never signed out, then once after signing in', (tester) async {
    final auth = await start(tester, signedIn: false);

    expect(server.preferencePatches, isEmpty);
    expect(
      server.calls.where((call) => call.contains('/api/me/preferences')),
      isEmpty,
    );

    await auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(server.preferencePatches, [
      {'language': 'en'},
    ]);
  });

  testWidgets('signing out and in again in the same run says nothing new',
      (tester) async {
    final auth = await start(tester, signedIn: true, at: '/account');

    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();
    expect(server.preferencePatches, hasLength(1));

    await auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(server.preferencePatches, hasLength(1));
  });

  testWidgets('a failure is ignored, and not retried in this run',
      (tester) async {
    server.status['PATCH /api/me/preferences'] = 500;
    await start(tester, signedIn: true, at: '/account');

    expect(find.byType(SnackBar), findsNothing);
    expect(
      server.calls.where((call) => call == 'PATCH /api/me/preferences'),
      hasLength(1),
    );

    await tester.pump();
    await tester.pumpAndSettle();
    expect(
      server.calls.where((call) => call == 'PATCH /api/me/preferences'),
      hasLength(1),
    );
  });
}
