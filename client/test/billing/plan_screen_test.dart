import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/app_router.dart';
import 'package:wishlist/src/auth/account_screen.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/billing/billing_repository.dart';
import 'package:wishlist/src/billing/plan_screen.dart';
import 'package:wishlist/src/legal/legal_placeholder_screen.dart';
import 'package:wishlist/src/lists/price.dart';

import '../support/fakes.dart';
import 'support.dart';

const _kPrice = '€49.00 per year, VAT included';
const _kPaymentProcessing =
    'Your payment is being processed. Your plan will update shortly.';
const _kFailed = 'That did not work. Try again in a moment.';

Map<String, Object?> _premium({bool canManage = true}) => billingStatus(
      plan: 'premium',
      status: 'active',
      renewsAt: '2027-03-12T12:00:00Z',
      limits: const {'max_lists': null, 'max_gifts_per_list': null},
      canManage: canManage,
    );

void main() {
  late FakeServer server;
  late MemoryTokenStore store;

  setUp(() {
    server = FakeServer()..billing = billingStatus(offer: kBillingOffer);
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
    debugOnTheWeb = true;
    addTearDown(() => debugOnTheWeb = null);
  });

  Future<void> open(
    WidgetTester tester, {
    String location = kPlanPath,
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = location;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
  }

  Future<void> pumpPlan(
    WidgetTester tester, {
    String location = kPlanPath,
  }) async {
    await open(tester, location: location);
    await tester.pumpAndSettle();
  }

  int reads() => server.calls.where((c) => c == 'GET /api/billing').length;

  group('what it shows', () {
    testWidgets('free with an offer: limits, price, payment and legal links',
        (tester) async {
      await pumpPlan(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Free: 1 list, up to 20 gifts per list'), findsOneWidget);
      expect(find.text('Premium: unlimited lists and gifts'), findsOneWidget);
      expect(find.text(_kPrice), findsOneWidget);
      expect(find.text('Continue to payment'), findsOneWidget);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      expect(find.text('Right of withdrawal'), findsOneWidget);
    });

    testWidgets('the free line follows the limits the server sends',
        (tester) async {
      server.billing = billingStatus(
        offer: kBillingOffer,
        limits: const {'max_lists': 3, 'max_gifts_per_list': 50},
      );
      await pumpPlan(tester);

      expect(
        find.text('Free: 3 lists, up to 50 gifts per list'),
        findsOneWidget,
      );
    });

    testWidgets('free with no offer: nothing to buy', (tester) async {
      server.billing = billingStatus(enforced: true);
      await pumpPlan(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.textContaining('VAT included'), findsNothing);
    });

    testWidgets('premium: no free line, nothing to buy, a way to manage',
        (tester) async {
      server.billing = _premium();
      await pumpPlan(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text('Renews on March 12, 2027'), findsOneWidget);
      expect(find.textContaining('Free:'), findsNothing);
      expect(find.text('Premium: unlimited lists and gifts'), findsOneWidget);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.text('Manage subscription'), findsOneWidget);
    });

    testWidgets('limits sent as null for premium read the same way',
        (tester) async {
      server.billing = billingStatus(
        plan: 'premium',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: null,
      );
      await pumpPlan(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.textContaining('Free:'), findsNothing);
    });

    testWidgets('on mobile: the plan and limits, no price, purchase or link',
        (tester) async {
      debugOnTheWeb = false;
      server.billing = billingStatus(offer: kBillingOffer, canManage: true);
      await pumpPlan(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Free: 1 list, up to 20 gifts per list'), findsOneWidget);
      expect(
        find.text('Subscriptions are not available in the app yet.'),
        findsOneWidget,
      );
      expect(find.text(_kPrice), findsNothing);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text('Terms of service'), findsNothing);
    });

    testWidgets('on mobile, a premium user is not told subscriptions are '
        'unavailable', (tester) async {
      debugOnTheWeb = false;
      server.billing = _premium();
      await pumpPlan(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(
        find.text('Subscriptions are not available in the app yet.'),
        findsNothing,
      );
    });

    testWidgets('a failed read says so, and trying again loads it',
        (tester) async {
      server.status['GET /api/billing'] = 500;
      await pumpPlan(tester);

      expect(find.text('Could not load your plan.'), findsOneWidget);

      server.status.remove('GET /api/billing');
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Could not load your plan.'), findsNothing);
      expect(find.text('Free plan'), findsOneWidget);
    });

    testWidgets('in French on a French device', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await pumpPlan(tester);

      expect(find.text('Formule gratuite'), findsOneWidget);
      expect(
        find.text('Gratuit : 1 liste, jusqu\'à 20 cadeaux par liste'),
        findsOneWidget,
      );
      expect(
        find.text('${formatPrice('49.00', 'EUR', 'fr')} par an, TVA incluse'),
        findsOneWidget,
      );
      expect(find.text('Continuer vers le paiement'), findsOneWidget);
      expect(find.text('Conditions générales'), findsOneWidget);
    });
  });

  group('checkout', () {
    testWidgets('opens the URL in the same tab', (tester) async {
      final launcher = installRecordingUrlLauncher();
      await pumpPlan(tester);

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('POST /api/billing/checkout'));
      expect(launcher.launched.single.url, server.checkoutUrl);
      expect(launcher.launched.single.options.webOnlyWindowName, '_self');
    });

    testWidgets('409 already_premium reads the plan again, without an error',
        (tester) async {
      final launcher = installRecordingUrlLauncher();
      await pumpPlan(tester);
      server.status['POST /api/billing/checkout'] = 409;
      server.billing = _premium();

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.text(_kFailed), findsNothing);
      expect(launcher.launched, isEmpty);
    });

    for (final code in [502, 503]) {
      testWidgets('$code says the action failed and stays', (tester) async {
        final launcher = installRecordingUrlLauncher();
        await pumpPlan(tester);
        server.status['POST /api/billing/checkout'] = code;

        await tester.tap(find.text('Continue to payment'));
        await tester.pumpAndSettle();

        expect(find.text(_kFailed), findsOneWidget);
        expect(find.text('Continue to payment'), findsOneWidget);
        expect(launcher.launched, isEmpty);
      });
    }

    testWidgets('404: no longer on sale, says so and the offer goes',
        (tester) async {
      await pumpPlan(tester);
      server.status['POST /api/billing/checkout'] = 404;
      server.billing = billingStatus();

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsOneWidget);
      expect(find.text('Continue to payment'), findsNothing);
    });

    testWidgets('a URL that cannot be opened says the action failed',
        (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.checkoutUrl = 'not a link';
      await pumpPlan(tester);

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsOneWidget);
      expect(launcher.launched, isEmpty);
    });

    testWidgets('a server error says the action failed', (tester) async {
      await pumpPlan(tester);
      server.status['POST /api/billing/checkout'] = 500;

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsOneWidget);
    });

    testWidgets('a 401 signs out without a message', (tester) async {
      await pumpPlan(tester);
      server.status['POST /api/billing/checkout'] = 401;

      await tester.tap(find.text('Continue to payment'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsNothing);
      expect(find.byType(PlanScreen), findsNothing);
    });
  });

  group('portal', () {
    testWidgets('opens the URL in the same tab', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = _premium();
      await pumpPlan(tester);

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('POST /api/billing/portal'));
      expect(launcher.launched.single.url, server.portalUrl);
      expect(launcher.launched.single.options.webOnlyWindowName, '_self');
    });

    testWidgets('absent when the server says it would not serve',
        (tester) async {
      server.billing = _premium(canManage: false);
      await pumpPlan(tester);

      expect(find.text('Manage subscription'), findsNothing);
    });

    testWidgets('502 says the action failed', (tester) async {
      server.billing = _premium();
      await pumpPlan(tester);
      server.status['POST /api/billing/portal'] = 502;

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsOneWidget);
    });

    testWidgets('409 no_subscription: says so and reads the plan again',
        (tester) async {
      server.billing = _premium();
      await pumpPlan(tester);
      server.status['POST /api/billing/portal'] = 409;
      server.billing = _premium(canManage: false);

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(find.text(_kFailed), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
    });
  });

  group('back from Stripe', () {
    const success = '$kPlanPath?checkout=success';

    Future<void> elapse(WidgetTester tester) =>
        tester.pump(kPaymentRereadDelay);

    testWidgets('success: the first read already premium, thanks at once',
        (tester) async {
      server.billing = _premium();
      await open(tester, location: success);
      await tester.pumpAndSettle();

      expect(find.text('You are on Premium. Thank you.'), findsOneWidget);
      expect(reads(), 1);
    });

    testWidgets('success: re-reads until premium, then stops', (tester) async {
      server.billing = billingStatus(offer: kBillingOffer);
      await open(tester, location: success);
      await tester.pump();
      await tester.pump();
      expect(reads(), 1);
      expect(find.text('You are on Premium. Thank you.'), findsNothing);

      await elapse(tester);
      expect(reads(), 2);

      server.billing = _premium();
      await elapse(tester);
      await tester.pumpAndSettle();

      expect(reads(), 3);
      expect(find.text('You are on Premium. Thank you.'), findsOneWidget);
      expect(find.text(_kPaymentProcessing), findsNothing);

      await tester.pump(const Duration(seconds: 30));
      expect(reads(), 3);
    });

    testWidgets('success: 5 re-reads at most, then says it is processing',
        (tester) async {
      await open(tester, location: success);
      await tester.pump();
      await tester.pump();
      for (var i = 0; i < kPaymentRereads; i++) {
        await elapse(tester);
      }
      await tester.pumpAndSettle();

      expect(reads(), 1 + kPaymentRereads);
      expect(find.text(_kPaymentProcessing), findsOneWidget);
      expect(find.text('You are on Premium. Thank you.'), findsNothing);

      await tester.pump(const Duration(seconds: 30));
      expect(reads(), 1 + kPaymentRereads);
    });

    testWidgets('success: while the plan still reads free, nothing to buy',
        (tester) async {
      await open(tester, location: success);
      await tester.pump();
      await tester.pump();

      expect(find.text('Continue to payment'), findsNothing);
      expect(find.text(_kPrice), findsNothing);

      for (var i = 0; i < kPaymentRereads; i++) {
        await elapse(tester);
      }
      await tester.pumpAndSettle();

      expect(find.text('Continue to payment'), findsNothing);
      expect(find.text(_kPrice), findsNothing);
    });

    testWidgets('success: failed reads still end in the processing message',
        (tester) async {
      server.status['GET /api/billing'] = 500;
      await open(tester, location: success);
      await tester.pump();
      await tester.pump();
      for (var i = 0; i < kPaymentRereads; i++) {
        await elapse(tester);
      }
      await tester.pumpAndSettle();

      expect(reads(), 1 + kPaymentRereads);
      expect(find.text(_kPaymentProcessing), findsOneWidget);
    });

    testWidgets('cancelled says so and offers it again', (tester) async {
      await pumpPlan(tester, location: '$kPlanPath?checkout=cancelled');

      expect(
        find.text('Payment cancelled. Nothing was charged.'),
        findsOneWidget,
      );
      expect(find.text('Continue to payment'), findsOneWidget);
      expect(reads(), 1);
    });

    testWidgets('back on an empty stack goes to the account screen',
        (tester) async {
      await pumpPlan(tester, location: '$kPlanPath?checkout=cancelled');

      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      expect(find.byType(AccountScreen), findsOneWidget);
    });

    test('the sign-in guard returns to the page with its query', () {
      final target = authRedirect(
        AuthStatus.signedOut,
        Uri.parse(success),
        joinPending: false,
      );
      final signIn = Uri.parse(target!);
      expect(signIn.path, kSignInPath);
      expect(signIn.queryParameters['from'], success);

      expect(
        authRedirect(AuthStatus.signedIn, signIn, joinPending: false),
        success,
      );
    });
  });

  group('legal links', () {
    testWidgets('fall back to the local pages', (tester) async {
      final launcher = installRecordingUrlLauncher();
      await pumpPlan(tester);

      await tester.tap(find.text('Right of withdrawal'));
      await tester.pumpAndSettle();

      expect(
        tester
            .widget<LegalPlaceholderScreen>(
              find.byType(LegalPlaceholderScreen),
            )
            .document,
        LegalDocument.withdrawal,
      );
      expect(launcher.launched, isEmpty);
    });

    testWidgets('open the address the server names', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = billingStatus(
        offer: kBillingOffer,
        legal: const {
          'terms_url': 'https://example.test/terms',
          'privacy_url': 'https://example.test/privacy',
          'withdrawal_url': null,
        },
      );
      await pumpPlan(tester);

      await tester.tap(find.text('Terms of service'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Privacy'));
      await tester.pumpAndSettle();

      expect(launcher.launched.map((call) => call.url), [
        'https://example.test/terms',
        'https://example.test/privacy',
      ]);
      expect(find.byType(LegalPlaceholderScreen), findsNothing);

      await tester.tap(find.text('Right of withdrawal'));
      await tester.pumpAndSettle();

      expect(find.byType(LegalPlaceholderScreen), findsOneWidget);
    });
  });
}
