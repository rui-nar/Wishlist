import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/auth/account_screen.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';

import '../support/fakes.dart';

void main() {
  late FakeServer server;
  late MemoryTokenStore store;

  setUp(() {
    server = FakeServer();
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
  });

  Future<AuthController> pumpAccount(WidgetTester tester) async {
    tester.platformDispatcher.defaultRouteNameTestValue = '/account';
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  testWidgets('shows the name and email', (tester) async {
    await pumpAccount(tester);

    expect(find.text('Alice Martin'), findsOneWidget);
    expect(find.text('alice@example.com'), findsOneWidget);
  });

  testWidgets('delete asks for confirmation; cancel deletes nothing',
      (tester) async {
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();

    expect(find.text('Delete your account?'), findsOneWidget);
    expect(server.calls, isNot(contains('DELETE /api/me')));

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('Delete your account?'), findsNothing);
    expect(server.calls, isNot(contains('DELETE /api/me')));
    expect(auth.isSignedIn, isTrue);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  testWidgets('confirming deletes the account and signs out', (tester) async {
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(server.deleted, isTrue);
    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
    expect(find.byType(SignInScreen), findsOneWidget);
  });

  testWidgets('a failed deletion says so and stays signed in',
      (tester) async {
    server.status['DELETE /api/me'] = 500;
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(find.text('Your account could not be deleted. Try again.'),
        findsOneWidget);
    expect(auth.isSignedIn, isTrue);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  testWidgets('sign out clears the store and shows sign-in', (tester) async {
    await pumpAccount(tester);

    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();

    expect(store.token, isNull);
    expect(server.sessions, isEmpty);
    expect(find.byType(SignInScreen), findsOneWidget);
  });
}
