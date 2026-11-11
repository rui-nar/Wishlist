import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shushgift/src/auth/auth_controller.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/home/home_screen.dart';
import 'package:shushgift/src/version_screen.dart';
import 'package:shushgift/src/welcome/welcome_screen.dart';

import '../support/fakes.dart';

/// The welcome page (WEB_LAYOUT_PLAN D6–D8), in the app with its router.
void main() {
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
    Size size = const Size(390, 844),
    MemoryTokenStore? store,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  testWidgets('a signed-out visit to / shows the welcome page', (tester) async {
    await start(tester, '/');

    expect(find.byType(WelcomeScreen), findsOneWidget);
    expect(location(tester).path, '/welcome');
    expect(find.text('Wish lists for every occasion'), findsOneWidget);
    expect(
      find.text("Keep the things you'd love to receive in one place, share "
          'them with family and friends for each occasion, and let them '
          'choose without spoiling the surprise.'),
      findsOneWidget,
    );
    expect(find.text('Lists for everything you wish for'), findsOneWidget);
    expect(find.text('Shared for each occasion'), findsOneWidget);
    expect(find.text('The surprise stays a surprise'), findsOneWidget);
    expect(find.text('You stay in control'), findsNothing);
    expect(
      find.text('Whoever a list is for never sees what was reserved, bought '
          'or said. The people you invite see who is giving what, talk it '
          'over under each gift, team up on a bigger gift, and can add '
          'hidden gifts of their own: the ones bought are revealed once the '
          'occasion has passed.'),
      findsOneWidget,
    );
    expect(find.byType(AppBar), findsNothing);
    // Nothing is asked of the server or of Google before sign-in.
    expect(server.calls, isNot(contains('GET /api/config')));
  });

  testWidgets('Register opens the sign-in screen in register mode',
      (tester) async {
    await start(tester, '/welcome');

    await tester.tap(find.widgetWithText(FilledButton, 'Register'));
    await tester.pumpAndSettle();

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(location(tester).path, '/sign-in');
    expect(location(tester).queryParameters, {'mode': 'register'});
    expect(find.text('Create your account'), findsOneWidget);
    expect(find.text('Your Google account is all you need.'), findsOneWidget);
  });

  testWidgets('Log in opens the sign-in screen, which links back',
      (tester) async {
    await start(tester, '/welcome');

    await tester.tap(find.widgetWithText(OutlinedButton, 'Log in'));
    await tester.pumpAndSettle();

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(location(tester).toString(), '/sign-in');
    expect(
      find.text('Sign in to see your lists and the lists shared with you.'),
      findsOneWidget,
    );

    await tester.tap(find.text('What is Shush Gift?'));
    await tester.pumpAndSettle();

    expect(find.byType(WelcomeScreen), findsOneWidget);
    expect(location(tester).path, '/welcome');
  });

  testWidgets('signing in from Register lands on home', (tester) async {
    final auth = await start(tester, '/welcome');

    await tester.tap(find.widgetWithText(FilledButton, 'Register'));
    await tester.pumpAndSettle();
    await auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(location(tester).toString(), '/');
  });

  testWidgets('the footer opens the version screen, signed out',
      (tester) async {
    await start(tester, '/welcome');

    final about = find.text('About this app');
    await tester.scrollUntilVisible(about, 200);
    await tester.tap(about);
    await tester.pumpAndSettle();

    expect(find.byType(VersionScreen), findsOneWidget);
    expect(find.text('App v1.2.3'), findsOneWidget);
    expect(find.text('Server v1.2.0 (validation)'), findsOneWidget);

    // Back to the welcome page.
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(find.byType(WelcomeScreen), findsOneWidget);
  });

  testWidgets('signed in, /welcome goes home', (tester) async {
    await start(
      tester,
      '/welcome',
      store: MemoryTokenStore(server.addSession()),
    );

    expect(find.byType(WelcomeScreen), findsNothing);
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(location(tester).toString(), '/');
  });

  testWidgets('in French on a French device', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);

    await start(tester, '/');

    expect(find.text("Des listes d'envies pour chaque occasion"),
        findsOneWidget);
    expect(find.widgetWithText(FilledButton, "S'inscrire"), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Se connecter'),
        findsOneWidget);
    expect(find.text('La surprise reste entière'), findsOneWidget);
    expect(find.text('Vous gardez la main'), findsNothing);
    expect(
      find.text('Rassemblez les choses que vous aimeriez recevoir, '
          'partagez-les avec votre famille et vos amis pour chaque '
          'occasion, et laissez-les choisir sans gâcher la surprise.'),
      findsOneWidget,
    );
    expect(
      find.text('La personne à qui la liste est destinée ne voit jamais ce '
          'qui a été réservé, acheté ou dit. Les personnes invitées voient '
          'qui offre quoi, en discutent sous chaque cadeau, se regroupent '
          'pour un cadeau plus important et peuvent ajouter leurs propres '
          'cadeaux cachés : ceux qui ont été achetés sont dévoilés une fois '
          "l'occasion passée."),
      findsOneWidget,
    );
  });

  group('layout', () {
    Rect rectOf(WidgetTester tester, String text) =>
        tester.getRect(find.text(text));

    testWidgets('expanded: the hero beside the cards, capped', (tester) async {
      await start(tester, '/welcome', size: const Size(1440, 900));

      final headline = rectOf(tester, 'Wish lists for every occasion');
      final card = tester.getRect(find.ancestor(
        of: find.text('Lists for everything you wish for'),
        matching: find.byType(Card),
      ));
      expect(card.left, greaterThan(headline.right));
      // Side by side: the first card starts above the headline's bottom.
      expect(card.top, lessThan(headline.bottom));
      // The content is the welcome width, centred: (1440 - 1120) / 2.
      expect(card.right, closeTo(1440 - 160, 0.01));
      expect(headline.left, closeTo(160, 0.01));
    });

    testWidgets('compact: the cards under the hero', (tester) async {
      await start(tester, '/welcome');

      final register =
          tester.getRect(find.widgetWithText(FilledButton, 'Register'));
      final card = tester.getRect(find.ancestor(
        of: find.text('Lists for everything you wish for'),
        matching: find.byType(Card),
      ));
      expect(card.top, greaterThan(register.bottom));
      // Full width, with the compact padding.
      expect(card.left, 16);
      expect(card.right, 390 - 16);
    });
  });
}
