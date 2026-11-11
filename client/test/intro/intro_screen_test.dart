import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shushgift/src/auth/account_screen.dart';
import 'package:shushgift/src/auth/auth_controller.dart';
import 'package:shushgift/src/home/home_screen.dart';
import 'package:shushgift/src/intro/intro_screen.dart';
import 'package:shushgift/src/intro/intro_seen.dart';

import '../support/fakes.dart';

/// The introduction (NEEDS, Constraints, "Introduction"), in the app with its
/// router: shown once per device after sign-in, on a landing on home.
void main() {
  const firstTitle = 'Your wishes, their surprise';
  const secondTitle = 'Hidden actions';
  const thirdTitle = 'Hidden gifts';

  late FakeServer server;

  setUp(() {
    server = FakeServer();
    installFakeGoogleSignIn();
  });

  Uri location(WidgetTester tester) => GoRouter.of(
        tester.element(find.byType(Scaffold).last),
      ).routerDelegate.currentConfiguration.uri;

  /// The app at [at], with [prefs] as the device's stored preferences and a
  /// session stored unless [signedIn] is false.
  Future<AuthController> start(
    WidgetTester tester,
    String at, {
    Map<String, Object> prefs = const {},
    bool signedIn = true,
    Size size = const Size(390, 844),
  }) async {
    SharedPreferences.setMockInitialValues(prefs);
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(
      server,
      store: MemoryTokenStore(signedIn ? server.addSession() : null),
    );
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  Future<bool?> storedSeen() async =>
      (await SharedPreferences.getInstance()).getBool(kIntroSeenKey);

  Future<void> tapText(WidgetTester tester, String text) async {
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  testWidgets('a first landing on home opens the introduction',
      (tester) async {
    await start(tester, '/');

    expect(find.byType(IntroScreen), findsOneWidget);
    expect(find.byType(HomeScreen), findsNothing);
    expect(location(tester).toString(), '/intro');
    expect(find.text(firstTitle), findsOneWidget);
    expect(
      find.text("Make a list of the things you'd love and share it for an "
          'occasion, with a link. The family and friends you invite see it '
          'and choose what to give.'),
      findsOneWidget,
    );
    expect(find.text('Skip'), findsOneWidget);
    expect(find.text('Next'), findsOneWidget);
    expect(find.text('Back'), findsNothing);
    expect(find.bySemanticsLabel('Page 1 of 3'), findsOneWidget);
    expect(await storedSeen(), isNull);
  });

  testWidgets('Next and Back page forward and back', (tester) async {
    await start(tester, '/');

    await tapText(tester, 'Next');
    expect(find.text(secondTitle), findsOneWidget);
    expect(
      find.text('Reservations, purchases, group gifts and comments stay '
          'hidden from the person the list is for. Givers see each '
          "other's, so nobody buys the same gift twice. Nothing hints at "
          'them, not even after the occasion.'),
      findsOneWidget,
    );
    expect(find.bySemanticsLabel('Page 2 of 3'), findsOneWidget);
    expect(find.text('Back'), findsOneWidget);

    await tapText(tester, 'Next');
    expect(find.text(thirdTitle), findsOneWidget);
    expect(
      find.text('Givers can also add gifts that are not on the list, such as '
          'an idea of their own. They stay hidden from the person the list '
          'is for until the occasion has passed. Then only the ones bought '
          'are revealed, without saying who gave them.'),
      findsOneWidget,
    );
    expect(find.text('Next'), findsNothing);
    expect(find.text('Get started'), findsOneWidget);
    // The last page's own button leaves: no Skip beside it.
    expect(find.text('Skip').hitTestable(), findsNothing);

    await tapText(tester, 'Back');
    expect(find.text(secondTitle), findsOneWidget);
    await tapText(tester, 'Back');
    expect(find.text(firstTitle), findsOneWidget);
    expect(find.text('Back'), findsNothing);
    expect(location(tester).toString(), '/intro');
  });

  testWidgets('the arrow keys page, for the web', (tester) async {
    await start(tester, '/', size: const Size(1440, 900));

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await tester.pumpAndSettle();
    expect(find.text(secondTitle), findsOneWidget);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await tester.pumpAndSettle();
    expect(find.text(thirdTitle), findsOneWidget);

    // Past the last page: nothing.
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await tester.pumpAndSettle();
    expect(find.text(thirdTitle), findsOneWidget);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowLeft);
    await tester.pumpAndSettle();
    expect(find.text(secondTitle), findsOneWidget);
  });

  testWidgets('a swipe pages too', (tester) async {
    await start(tester, '/');

    await tester.fling(find.byType(PageView), const Offset(-300, 0), 1000);
    await tester.pumpAndSettle();
    expect(find.text(secondTitle), findsOneWidget);
    expect(find.bySemanticsLabel('Page 2 of 3'), findsOneWidget);
  });

  testWidgets('Skip marks it seen and goes home', (tester) async {
    await start(tester, '/');

    await tapText(tester, 'Skip');

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(location(tester).toString(), '/');
    expect(await storedSeen(), isTrue);
  });

  testWidgets('Get started marks it seen and goes home', (tester) async {
    await start(tester, '/');

    await tapText(tester, 'Next');
    await tapText(tester, 'Next');
    await tapText(tester, 'Get started');

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(location(tester).toString(), '/');
    expect(await storedSeen(), isTrue);
  });

  testWidgets('not shown again, in this run or the next', (tester) async {
    await start(tester, '/');
    await tapText(tester, 'Skip');

    // Away and back home in the same run.
    await tapText(tester, 'Shared with me');
    await tapText(tester, 'My lists');
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(IntroScreen), findsNothing);

    // The next start on this device reads it back.
    await tester.pumpWidget(const SizedBox());
    final app = buildApp(
      server,
      store: MemoryTokenStore(server.addSession()),
    );
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(IntroScreen), findsNothing);
  });

  testWidgets('a device that has seen it goes straight home', (tester) async {
    await start(tester, '/', prefs: {kIntroSeenKey: true});

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(IntroScreen), findsNothing);
    expect(location(tester).toString(), '/');
  });

  testWidgets('a stored value that cannot be read does not trap anyone',
      (tester) async {
    // Not a bool: reading it fails, which counts as seen.
    await start(tester, '/', prefs: {kIntroSeenKey: 'yes'});

    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(IntroScreen), findsNothing);
  });

  testWidgets('signed out, home is the welcome page, not the introduction',
      (tester) async {
    await start(tester, '/', signedIn: false);

    expect(find.byType(IntroScreen), findsNothing);
    expect(location(tester).path, '/welcome');
  });

  testWidgets('a from goes first; the introduction waits for home',
      (tester) async {
    final auth = await start(tester, '/account', signedIn: false);

    await auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();
    expect(find.byType(AccountScreen), findsOneWidget);
    expect(location(tester).toString(), '/account');

    GoRouter.of(tester.element(find.byType(AccountScreen))).go('/');
    await tester.pumpAndSettle();
    expect(find.byType(IntroScreen), findsOneWidget);
    expect(location(tester).toString(), '/intro');
  });

  testWidgets('signing in with nowhere to go opens it', (tester) async {
    final auth = await start(tester, '/sign-in', signedIn: false);

    await auth.signInWithGoogle(kValidIdToken);
    await tester.pumpAndSettle();

    expect(find.byType(IntroScreen), findsOneWidget);
    expect(location(tester).toString(), '/intro');
  });

  testWidgets('in French on a French device', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await start(tester, '/');

    expect(find.text('Vos envies, leur surprise'), findsOneWidget);
    expect(find.text('Passer'), findsOneWidget);
    await tapText(tester, 'Suivant');
    expect(find.text('Des actions cachées'), findsOneWidget);
    expect(find.text('Précédent'), findsOneWidget);
    await tapText(tester, 'Suivant');
    expect(find.text('Des cadeaux cachés'), findsOneWidget);
    expect(find.text('Commencer'), findsOneWidget);
  });
}
