import 'package:flutter/material.dart';
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
    expect(
      find.text(
        'Your account and the lists you own, with their gifts and '
        'occasions, are deleted. Everyone you shared them with loses '
        'access, and you are signed out on every device. This cannot be '
        'undone.',
      ),
      findsOneWidget,
    );
    expect(server.calls, isNot(contains('DELETE /api/me')));

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('Delete your account?'), findsNothing);
    expect(server.calls, isNot(contains('DELETE /api/me')));
    expect(auth.isSignedIn, isTrue);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  testWidgets('the confirmation is in French on a French device',
      (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await pumpAccount(tester);

    await tester.tap(find.text('Supprimer le compte'));
    await tester.pumpAndSettle();

    expect(find.text('Supprimer votre compte ?'), findsOneWidget);
    expect(
      find.text(
        "Votre compte et les listes que vous possédez, avec leurs cadeaux et "
        "leurs occasions, sont supprimés. Les personnes avec qui vous les "
        "avez partagées n'y ont plus accès, et vous êtes déconnecté sur tous "
        "vos appareils. Cette action est définitive.",
      ),
      findsOneWidget,
    );
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

  group('email notifications (COMMENTS_NOTIFICATIONS D20)', () {
    SwitchListTile emailSwitch(WidgetTester tester) =>
        tester.widget(find.byType(SwitchListTile));

    testWidgets('the switch reads the server', (tester) async {
      server.preferences['email_notifications'] = false;
      await pumpAccount(tester);

      expect(server.calls, contains('GET /api/me/preferences'));
      expect(find.text('Email notifications'), findsOneWidget);
      expect(emailSwitch(tester).value, isFalse);
    });

    testWidgets('turning it off writes the server', (tester) async {
      await pumpAccount(tester);
      expect(emailSwitch(tester).value, isTrue);
      final patches = server.preferencePatches.length;

      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();

      expect(server.preferencePatches.sublist(patches), [
        {'email_notifications': false},
      ]);
      expect(server.preferences['email_notifications'], isFalse);
      expect(emailSwitch(tester).value, isFalse);
    });

    testWidgets('a failed change says so and the switch goes back',
        (tester) async {
      await pumpAccount(tester);
      server.status['PATCH /api/me/preferences'] = 500;

      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();

      expect(
        find.text(
          'Your email notifications setting could not be changed. Try again.',
        ),
        findsOneWidget,
      );
      expect(emailSwitch(tester).value, isTrue);
      expect(emailSwitch(tester).onChanged, isNotNull);
    });

    testWidgets('a failed read says so and the switch stays disabled',
        (tester) async {
      server.status['GET /api/me/preferences'] = 500;
      await pumpAccount(tester);

      expect(
        find.text(
          'Your email notifications setting could not be loaded. '
          'Try again later.',
        ),
        findsOneWidget,
      );
      expect(emailSwitch(tester).value, isFalse);
      expect(emailSwitch(tester).onChanged, isNull);
    });

    testWidgets('in French on a French device', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await pumpAccount(tester);

      expect(find.text('Notifications par e-mail'), findsOneWidget);
    });
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
