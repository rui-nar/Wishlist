import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/billing/billing_repository.dart';
import 'package:wishlist/src/billing/plan_screen.dart';
import 'package:wishlist/src/billing/store.dart';
import 'package:wishlist/src/billing/store_purchases.dart';
import 'package:wishlist/src/legal/legal_placeholder_screen.dart';

import '../support/fakes.dart';
import 'support.dart';

// Buying Premium in the iOS app, through a fake App Store (Apple IAP plan
// D3, D8).

const _kSubscribe = 'Subscribe';
const _kRestore = 'Restore purchases';
const _kPrice = '€49.99 per year';
const _kManageApple = 'Manage in the App Store';
const _kUnavailable = 'Subscriptions are not available in the app yet.';
const _kFailed = 'That did not work. Try again in a moment.';
const _kThanks = 'You are on Premium. Thank you.';
const _kUnconfirmed = 'Apple has your purchase, but it could not be '
    'confirmed yet. It will be the next time you open this page.';

void main() {
  late FakeServer server;
  late MemoryTokenStore store;
  late FakeStore appStore;

  setUp(() {
    server = FakeServer()
      ..billing = billingStatus(appleOffer: kAppleOffer, offer: kBillingOffer);
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
    appStore = installFakeStore();
  });

  Future<AuthController> pump(
    WidgetTester tester, {
    String location = kPlanPath,
  }) async {
    tester.platformDispatcher.defaultRouteNameTestValue = location;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  Future<void> tap(WidgetTester tester, String text) async {
    await tester.ensureVisible(find.text(text));
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  group('what the plan page shows', () {
    testWidgets('Apple selling: name, length, price, renewal, Subscribe, '
        'Restore, the terms and privacy', (tester) async {
      await pump(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Premium, yearly subscription'), findsOneWidget);
      expect(find.text(_kPrice), findsOneWidget);
      expect(
        find.textContaining('Renews automatically every year until you '
            "cancel it in your Apple account's subscriptions"),
        findsOneWidget,
      );
      expect(find.text(_kSubscribe), findsOneWidget);
      expect(find.text(_kRestore), findsOneWidget);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      // Apple sells: withdrawal is Apple's, and Stripe's offer is the web's.
      expect(find.text('Right of withdrawal'), findsNothing);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.textContaining('VAT included'), findsNothing);
      expect(find.text(_kUnavailable), findsNothing);
      expect(appStore.listening, isTrue);
    });

    testWidgets('not offered: nothing to buy or restore', (tester) async {
      server.billing = billingStatus(offer: kBillingOffer);
      await pump(tester);

      expect(find.text(_kUnavailable), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
    });

    testWidgets('the App Store gives no price: says so, Restore stays',
        (tester) async {
      appStore.storeProduct = null;
      await pump(tester);

      expect(
        find.text('The App Store cannot be reached right now. Try again '
            'later.'),
        findsOneWidget,
      );
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsOneWidget);
    });

    testWidgets('already Premium through Stripe: no purchase, the portal',
        (tester) async {
      server.billing = billingStatus(
        plan: 'premium',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        appleOffer: kAppleOffer,
        canManage: true,
      );
      await pump(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
      expect(find.text('Manage subscription'), findsOneWidget);
      expect(find.text(_kManageApple), findsNothing);
    });

    testWidgets('already Premium as a grant: no purchase', (tester) async {
      server.billing = billingStatus(
        plan: 'premium',
        source: 'manual',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        appleOffer: kAppleOffer,
      );
      await pump(tester);

      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
    });

    testWidgets('Premium through Apple: Apple manages it, not Stripe',
        (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = {...kAppleSubscribed, 'can_manage': true};
      await pump(tester);

      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text('Manage subscription'), findsNothing);
      await tap(tester, _kManageApple);

      expect(launcher.launched.single.url, kAppleSubscriptionsUrl);
      expect(
        launcher.launched.single.options.mode,
        PreferredLaunchMode.externalApplication,
      );
    });

    testWidgets('free, an Apple subscription in billing retry: Apple manages '
        'it', (tester) async {
      server.billing = billingStatus(
        appleOffer: kAppleOffer,
        appleRenewing: true,
      );
      await pump(tester);

      expect(find.text(_kManageApple), findsOneWidget);
    });

    testWidgets("the terms fall back to Apple's standard licence",
        (tester) async {
      final launcher = installRecordingUrlLauncher();
      await pump(tester);

      await tap(tester, 'Terms of service');

      expect(launcher.launched.single.url, kAppleStandardEulaUrl);
    });

    testWidgets('the terms and privacy the server names', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = billingStatus(
        appleOffer: kAppleOffer,
        legal: const {
          'terms_url': 'https://example.test/terms',
          'privacy_url': null,
          'withdrawal_url': 'https://example.test/withdrawal',
        },
      );
      await pump(tester);

      await tap(tester, 'Terms of service');
      expect(launcher.launched.single.url, 'https://example.test/terms');

      await tap(tester, 'Privacy');
      expect(find.byType(LegalPlaceholderScreen), findsOneWidget);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await pump(tester);

      expect(find.text('Premium, abonnement annuel'), findsOneWidget);
      expect(find.text('€49.99 par an'), findsOneWidget);
      expect(find.text("S'abonner"), findsOneWidget);
      expect(find.text('Restaurer les achats'), findsOneWidget);
    });
  });

  group('buying', () {
    testWidgets('ties the purchase to the account, reports it, finishes it '
        'once accepted', (tester) async {
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(appStore.bought.single, (
        productId: kAppleProductId,
        accountId: kAlice['id']!,
      ));
      expect(server.appleTransactions, ['jws-2000001']);
      expect(appStore.finished, ['2000001']);
      expect(find.text(_kThanks), findsOneWidget);
      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kManageApple), findsOneWidget);
    });

    testWidgets('cancelled: nothing reported or said, Subscribe again',
        (tester) async {
      appStore.onBuy = () =>
          [applePurchase(status: StorePurchaseStatus.cancelled)];
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(server.appleTransactions, isEmpty);
      expect(appStore.finished, isEmpty);
      expect(find.text(_kFailed), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, _kSubscribe))
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('pending: says it waits, reports nothing yet', (tester) async {
      appStore.onBuy = () => [applePurchase(status: StorePurchaseStatus.pending)];
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(
        find.text('Your purchase is waiting for approval. Your plan will '
            'update once it goes through.'),
        findsOneWidget,
      );
      expect(server.appleTransactions, isEmpty);
      expect(appStore.finished, isEmpty);
    });

    testWidgets('approved later, while the page is open: reported then',
        (tester) async {
      appStore.onBuy = () => [applePurchase(status: StorePurchaseStatus.pending)];
      await pump(tester);
      await tap(tester, _kSubscribe);

      appStore.send([applePurchase(id: '2000002')]);
      await tester.pumpAndSettle();

      expect(server.appleTransactions, ['jws-2000002']);
      expect(appStore.finished, ['2000002']);
      expect(find.text(_kThanks), findsOneWidget);
    });

    testWidgets('StoreKit fails to open its sheet: says so', (tester) async {
      appStore.buyError = Exception('storekit');
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(find.text(_kFailed), findsOneWidget);
      expect(server.appleTransactions, isEmpty);
    });

    const refusals = {
      'other_account': 'This App Store purchase belongs to another Wishlist '
          'account. Sign in to that account to use it.',
      'sandbox_refused': 'Test purchases are not accepted here.',
      'invalid_transaction':
          'This App Store purchase could not be confirmed for your account.',
      'other_product':
          'This App Store purchase could not be confirmed for your account.',
      'unknown_transaction':
          'This App Store purchase could not be confirmed for your account.',
    };
    for (final MapEntry(key: code, value: message) in refusals.entries) {
      testWidgets('refused for good ($code): finished, and says so',
          (tester) async {
        server.appleRefusal = code;
        await pump(tester);

        await tap(tester, _kSubscribe);

        expect(server.appleTransactions, ['jws-2000001']);
        expect(appStore.finished, ['2000001']);
        expect(find.text(message), findsOneWidget);
        expect(find.text('Free plan'), findsOneWidget);
      });
    }

    for (final code in [502, 503, 404, 500]) {
      testWidgets('$code: left unfinished for the store to resend',
          (tester) async {
        server.status['POST /api/billing/apple/transactions'] = code;
        await pump(tester);

        await tap(tester, _kSubscribe);

        expect(appStore.finished, isEmpty);
        expect(find.text(_kUnconfirmed), findsOneWidget);
      });
    }

    testWidgets('a 409 with a code the app does not know: left unfinished',
        (tester) async {
      server.appleRefusal = 'something_new';
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(appStore.finished, isEmpty);
      expect(find.text(_kUnconfirmed), findsOneWidget);
    });

    testWidgets('a 401 signs out, and the purchase stays unfinished',
        (tester) async {
      server.status['POST /api/billing/apple/transactions'] = 401;
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(appStore.finished, isEmpty);
      expect(find.text(_kSubscribe), findsNothing);
    });
  });

  group('unfinished purchases', () {
    testWidgets('reported and finished when the page opens', (tester) async {
      appStore.unfinishedPurchases = [applePurchase(id: '2000009')];
      await pump(tester);

      expect(server.appleTransactions, ['jws-2000009']);
      expect(appStore.finished, ['2000009']);
      expect(find.text('Premium'), findsOneWidget);
    });

    testWidgets('still refused by the server: kept for the next time',
        (tester) async {
      appStore.unfinishedPurchases = [applePurchase(id: '2000009')];
      server.status['POST /api/billing/apple/transactions'] = 502;
      await pump(tester);

      expect(appStore.finished, isEmpty);
      expect(appStore.unfinishedPurchases, hasLength(1));
    });
  });

  group('listened to from launch, while signed in', () {
    /// The app's one listener, as the widgets read it.
    StorePurchases? listener(WidgetTester tester) =>
        tester.element(find.byType(Navigator).first).read<StorePurchases?>();

    testWidgets('listens while signed in, on any page; stops at sign-out',
        (tester) async {
      final auth = await pump(tester, location: '/account');

      expect(appStore.listening, isTrue);
      expect(listener(tester)!.isListening, isTrue);

      await auth.signOut();
      await tester.pumpAndSettle();

      expect(appStore.listening, isFalse);
      expect(listener(tester)!.isListening, isFalse);
    });

    testWidgets('not before someone signs in', (tester) async {
      store = MemoryTokenStore();
      final auth = await pump(tester, location: '/');

      expect(appStore.listening, isFalse);

      store.token = server.addSession();
      await auth.restore();
      await tester.pumpAndSettle();

      expect(appStore.listening, isTrue);
    });

    testWidgets('a purchase approved while another page is shown: reported '
        'and finished at once', (tester) async {
      await pump(tester, location: '/account');

      appStore.send([applePurchase(id: '2000003')]);
      await tester.pumpAndSettle();

      expect(server.appleTransactions, ['jws-2000003']);
      expect(appStore.finished, ['2000003']);
    });

    testWidgets('what an earlier run left unfinished: reported at sign-in, '
        'whatever the page', (tester) async {
      appStore.unfinishedPurchases = [applePurchase(id: '2000009')];
      await pump(tester, location: '/account');

      expect(server.appleTransactions, ['jws-2000009']);
      expect(appStore.finished, ['2000009']);
    });

    testWidgets('signed out: left unfinished for the next sign-in',
        (tester) async {
      final auth = await pump(tester, location: '/account');
      await auth.signOut();
      await tester.pumpAndSettle();

      // StoreKit keeps it unfinished, and lists it at the next start.
      final renewal = applePurchase(id: '2000004');
      appStore.unfinishedPurchases = [renewal];
      appStore.send([renewal]);
      await tester.pumpAndSettle();
      expect(server.appleTransactions, isEmpty);

      store.token = server.addSession();
      await auth.restore();
      await tester.pumpAndSettle();

      expect(server.appleTransactions, ['jws-2000004']);
      expect(appStore.finished, ['2000004']);
    });

    testWidgets('the plan page shares the listener: one report a purchase, '
        'and listening goes on once it closes', (tester) async {
      await pump(tester);
      final shared = listener(tester);
      expect(
        tester.element(find.byType(PlanScreen)).read<StorePurchases?>(),
        same(shared),
      );

      appStore.send([applePurchase(id: '2000002')]);
      await tester.pumpAndSettle();
      expect(server.appleTransactions, ['jws-2000002']);
      expect(find.text(_kThanks), findsOneWidget);

      GoRouter.of(tester.element(find.byType(PlanScreen))).go('/account');
      await tester.pumpAndSettle();
      expect(find.byType(PlanScreen), findsNothing);

      appStore.send([applePurchase(id: '2000003')]);
      await tester.pumpAndSettle();
      expect(server.appleTransactions, ['jws-2000002', 'jws-2000003']);
      expect(appStore.finished, ['2000002', '2000003']);
      expect(listener(tester), same(shared));
    });

    testWidgets('no store, as on the web: no listener', (tester) async {
      debugStore = null;
      debugOnIos = false;
      await pump(tester, location: '/account');

      expect(listener(tester), isNull);
      expect(appStore.listening, isFalse);
    });
  });

  group('restoring', () {
    testWidgets('reports what Apple restores, and finishes it',
        (tester) async {
      appStore.restorable = [
        applePurchase(id: '2000005', status: StorePurchaseStatus.restored),
      ];
      await pump(tester);

      await tap(tester, _kRestore);

      expect(server.appleTransactions, ['jws-2000005']);
      expect(appStore.finished, ['2000005']);
      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kThanks), findsOneWidget);
    });

    testWidgets('nothing to restore: says so', (tester) async {
      await pump(tester);

      await tap(tester, _kRestore);

      expect(
        find.text('No subscription to restore was found for your Apple '
            'account.'),
        findsOneWidget,
      );
      expect(server.appleTransactions, isEmpty);
    });

    testWidgets("another account's: says so rather than nothing found",
        (tester) async {
      server.appleRefusal = 'other_account';
      appStore.restorable = [
        applePurchase(id: '2000005', status: StorePurchaseStatus.restored),
      ];
      await pump(tester);

      await tap(tester, _kRestore);

      expect(find.textContaining('belongs to another Wishlist account'),
          findsOneWidget);
      expect(find.textContaining('No subscription to restore'), findsNothing);
    });
  });

  group('the account screen on iOS (review R1-8)', () {
    testWidgets('free with Apple selling: See Premium and the legal links',
        (tester) async {
      await pump(tester, location: '/account');

      expect(find.text('See Premium'), findsOneWidget);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      expect(find.text('Right of withdrawal'), findsNothing);

      await tap(tester, 'See Premium');
      expect(find.text(_kSubscribe), findsOneWidget);
    });

    testWidgets('Premium through Apple: Manage in the App Store',
        (tester) async {
      server.billing = {...kAppleSubscribed, 'can_manage': true};
      await pump(tester, location: '/account');

      expect(find.text(_kManageApple), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text('See Premium'), findsNothing);
    });

    testWidgets('Premium through Stripe: its portal, in the browser',
        (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = billingStatus(
        plan: 'premium',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        canManage: true,
      );
      await pump(tester, location: '/account');

      await tap(tester, 'Manage subscription');

      expect(launcher.launched.single.url, server.portalUrl);
      expect(
        launcher.launched.single.options.mode,
        PreferredLaunchMode.externalApplication,
      );
    });
  });
}
