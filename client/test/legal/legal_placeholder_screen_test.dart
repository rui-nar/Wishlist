import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/legal/legal_placeholder_screen.dart';

import '../support/fakes.dart';

/// The three legal pages: public placeholders, signed out as well as in
/// (PREMIUM_PLAN D17).
void main() {
  const english =
      'This page is a placeholder. Its text has not been supplied yet, and '
      'nothing here is binding.';
  const french =
      "Cette page est provisoire. Son texte n'a pas encore été fourni et "
      "rien ici n'engage.";

  // path, English title, French title.
  const pages = [
    ('/legal/terms', 'Terms of service', 'Conditions générales'),
    ('/legal/privacy', 'Privacy', 'Confidentialité'),
    ('/legal/withdrawal', 'Right of withdrawal', 'Droit de rétractation'),
  ];

  late FakeServer server;

  setUp(() {
    server = FakeServer();
    installFakeGoogleSignIn();
  });

  Future<void> start(
    WidgetTester tester,
    String at, {
    bool signedIn = false,
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = at;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(
      server,
      store: MemoryTokenStore(signedIn ? server.addSession() : null),
    );
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
  }

  for (final (path, title, _) in pages) {
    for (final signedIn in [false, true]) {
      testWidgets('$path, ${signedIn ? 'signed in' : 'signed out'}',
          (tester) async {
        await start(tester, path, signedIn: signedIn);

        expect(find.byType(LegalPlaceholderScreen), findsOneWidget);
        expect(find.byType(SignInScreen), findsNothing);
        expect(
          find.descendant(
            of: find.byType(AppBar),
            matching: find.text(title),
          ),
          findsOneWidget,
        );
        expect(find.text(english), findsOneWidget);
      });
    }
  }

  for (final (path, _, title) in pages) {
    testWidgets('$path in French on a French device', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await start(tester, path);

      expect(
        find.descendant(of: find.byType(AppBar), matching: find.text(title)),
        findsOneWidget,
      );
      expect(find.text(french), findsOneWidget);
    });
  }
}
