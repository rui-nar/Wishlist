import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/billing/billing_repository.dart';
import 'package:wishlist/src/billing/store.dart';
import 'package:wishlist/src/legal/legal_placeholder_screen.dart';

import '../support/fakes.dart';
import 'support.dart';

// Buying Premium in the Android app, through a fake Google Play (Android
// release plan D6, D8). The listener itself is the iOS app's, tested in
// apple_purchase_test.dart.

const _kSubscribe = 'Subscribe';
const _kRestore = 'Restore purchases';
const _kPrice = '€49.99 per year';
const _kManageGoogle = 'Manage in Google Play';
const _kUnavailable = 'Subscriptions are not available in the app yet.';
const _kFailed = 'That did not work. Try again in a moment.';
const _kManagedOnWebsite =
    'Your Premium was bought on the website and is managed there.';
const _kThanks = 'You are on Premium. Thank you.';
const _kUnconfirmed = 'Google Play has your purchase, but it could not be '
    'confirmed yet. It will be the next time you open this page.';

void main() {
  late FakeServer server;
  late MemoryTokenStore store;
  late FakeStore play;

  setUp(() {
    server = FakeServer()
      ..billing = billingStatus(googleOffer: kGoogleOffer, offer: kBillingOffer);
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
    play = installFakeGoogleStore();
  });

  Future<void> pump(WidgetTester tester, {String location = kPlanPath}) async {
    tester.platformDispatcher.defaultRouteNameTestValue = location;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
  }

  Future<void> tap(WidgetTester tester, String text) async {
    await tester.ensureVisible(find.text(text));
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  group('what the plan page shows', () {
    testWidgets("Google selling: name, length, Play's price, renewal, "
        'Subscribe, Restore, the terms and privacy', (tester) async {
      await pump(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Premium, yearly subscription'), findsOneWidget);
      expect(find.text(_kPrice), findsOneWidget);
      expect(
        find.text('Renews automatically every year until you cancel it in '
            'your Google Play subscriptions. Payment is charged to your '
            'Google Play account.'),
        findsOneWidget,
      );
      expect(find.text(_kSubscribe), findsOneWidget);
      expect(find.text(_kRestore), findsOneWidget);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      // Google sells: refunds are Play's, and Stripe's offer is the web's.
      expect(find.text('Right of withdrawal'), findsNothing);
      expect(find.text('Continue to payment'), findsNothing);
      expect(find.textContaining('Apple'), findsNothing);
      expect(find.text(_kUnavailable), findsNothing);
      expect(play.listening, isTrue);
    });

    testWidgets('not offered: nothing to buy or restore', (tester) async {
      server.billing = billingStatus(
        offer: kBillingOffer,
        appleOffer: kAppleOffer,
      );
      await pump(tester);

      expect(find.text(_kUnavailable), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
    });

    testWidgets('Play gives no price: says so, Restore stays', (tester) async {
      play.storeProduct = null;
      await pump(tester);

      expect(
        find.text('Google Play cannot be reached right now. Try again later.'),
        findsOneWidget,
      );
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsOneWidget);
    });

    testWidgets('already Premium through Stripe: no purchase, no link to '
        'Stripe, a plain line', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = billingStatus(
        plan: 'premium',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        googleOffer: kGoogleOffer,
        canManage: true,
      );
      await pump(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text(_kManageGoogle), findsNothing);
      expect(find.text(_kManagedOnWebsite), findsOneWidget);
      expect(find.byType(OutlinedButton), findsNothing);
      await tester.tap(find.text(_kManagedOnWebsite));
      await tester.pumpAndSettle();
      expect(launcher.launched, isEmpty);
      expect(server.calls, isNot(contains('POST /api/billing/portal')));
    });

    testWidgets('already Premium as a grant: no purchase',
        (tester) async {
      server.billing = billingStatus(
        plan: 'premium',
        source: 'manual',
        status: 'active',
        renewsAt: '2027-03-12T12:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        googleOffer: kGoogleOffer,
      );
      await pump(tester);

      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kRestore), findsNothing);
    });

    testWidgets('Premium through Apple: no purchase, nothing to manage here',
        (tester) async {
      server.billing = {...kAppleSubscribed, 'google_offer': kGoogleOffer};
      await pump(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kManageGoogle), findsNothing);
      expect(find.text('Manage in the App Store'), findsNothing);
    });

    testWidgets("Premium through Google: Play's subscriptions page, not "
        "Stripe's portal", (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = {...kGoogleSubscribed, 'can_manage': true};
      await pump(tester);

      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text('Manage subscription'), findsNothing);
      await tap(tester, _kManageGoogle);

      expect(launcher.launched.single.url, kGoogleSubscriptionsUrl);
      expect(
        launcher.launched.single.options.mode,
        PreferredLaunchMode.externalApplication,
      );
    });

    testWidgets('free, a Google subscription on hold: Play manages it',
        (tester) async {
      server.billing = billingStatus(
        googleOffer: kGoogleOffer,
        googleRenewing: true,
      );
      await pump(tester);

      expect(find.text(_kManageGoogle), findsOneWidget);
    });

    testWidgets("the terms: the app's page when the server names none, no "
        "Apple licence", (tester) async {
      final launcher = installRecordingUrlLauncher();
      await pump(tester);

      await tap(tester, 'Terms of service');

      expect(launcher.launched, isEmpty);
      expect(find.byType(LegalPlaceholderScreen), findsOneWidget);
    });

    testWidgets('the terms the server names', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = billingStatus(
        googleOffer: kGoogleOffer,
        legal: const {
          'terms_url': 'https://example.test/terms',
          'privacy_url': 'https://example.test/privacy',
          'withdrawal_url': 'https://example.test/withdrawal',
        },
      );
      await pump(tester);

      await tap(tester, 'Terms of service');
      await tap(tester, 'Privacy');

      expect(launcher.launched.map((launch) => launch.url), [
        'https://example.test/terms',
        'https://example.test/privacy',
      ]);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await pump(tester);

      expect(find.text('€49.99 par an'), findsOneWidget);
      expect(
        find.textContaining('dans vos abonnements Google Play'),
        findsOneWidget,
      );
      expect(find.text("S'abonner"), findsOneWidget);
    });
  });

  group('buying', () {
    testWidgets('ties the purchase to the account, posts its token, Premium '
        'once accepted', (tester) async {
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(play.bought.single, (
        productId: kGoogleProductId,
        accountId: kAlice['id']!,
      ));
      expect(server.googlePurchases, ['token-GPA.0001']);
      expect(server.appleTransactions, isEmpty);
      expect(play.finished, ['GPA.0001']);
      expect(find.text(_kThanks), findsOneWidget);
      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kSubscribe), findsNothing);
      expect(find.text(_kManageGoogle), findsOneWidget);
    });

    testWidgets('cancelled: nothing posted or said, Subscribe again',
        (tester) async {
      play.onBuy = () =>
          [googlePurchase(status: StorePurchaseStatus.cancelled)];
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(server.googlePurchases, isEmpty);
      expect(play.finished, isEmpty);
      expect(find.text(_kFailed), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, _kSubscribe))
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('pending: says it waits, posts nothing until paid',
        (tester) async {
      play.onBuy = () => [googlePurchase(status: StorePurchaseStatus.pending)];
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(
        find.text('Your purchase is waiting for approval. Your plan will '
            'update once it goes through.'),
        findsOneWidget,
      );
      expect(server.googlePurchases, isEmpty);
      expect(play.finished, isEmpty);

      play.send([googlePurchase(id: 'GPA.0002')]);
      await tester.pumpAndSettle();

      expect(server.googlePurchases, ['token-GPA.0002']);
      expect(find.text(_kThanks), findsOneWidget);
    });

    testWidgets('Play does not open its sheet: says so', (tester) async {
      play.buyError = StateError('no sheet');
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(find.text(_kFailed), findsOneWidget);
      expect(server.googlePurchases, isEmpty);
    });

    const invalid =
        'This Google Play purchase could not be confirmed for your account.';
    const refusals = {
      'invalid_purchase': invalid,
      'unknown_purchase': invalid,
      'other_product': invalid,
      'test_refused': 'Test purchases are not accepted here.',
      'real_refused': 'This test version of Wishlist only accepts test '
          'purchases. Google Play refunds this one within three days.',
    };
    for (final MapEntry(key: code, value: message) in refusals.entries) {
      testWidgets('refused for good ($code): set aside, and says so',
          (tester) async {
        server.googleRefusal = code;
        await pump(tester);

        await tap(tester, _kSubscribe);

        expect(server.googlePurchases, ['token-GPA.0001']);
        expect(play.finished, ['GPA.0001']);
        expect(play.finishedForOtherAccount, isEmpty);
        expect(find.text(message), findsOneWidget);
        expect(find.text('Free plan'), findsOneWidget);
      });
    }

    testWidgets("another account's: says so, and keeps it for that account",
        (tester) async {
      server.googleRefusal = 'other_account';
      await pump(tester);

      await tap(tester, _kSubscribe);

      expect(play.finishedForOtherAccount, ['GPA.0001']);
      expect(
        find.text('This Google Play purchase belongs to another Wishlist '
            'account. Sign in to that account to use it.'),
        findsOneWidget,
      );
    });

    for (final code in [502, 503, 404, 500]) {
      testWidgets('$code: left for Play to list again', (tester) async {
        server.status['POST /api/billing/google/purchases'] = code;
        await pump(tester);

        await tap(tester, _kSubscribe);

        expect(play.finished, isEmpty);
        expect(find.text(_kUnconfirmed), findsOneWidget);
      });
    }
  });

  group('unfinished purchases', () {
    testWidgets('posted at launch, whatever the page', (tester) async {
      play.unfinishedPurchases = [googlePurchase(id: 'GPA.0009')];
      await pump(tester, location: '/account');

      expect(server.googlePurchases, ['token-GPA.0009']);
      expect(play.finished, ['GPA.0009']);
    });

    testWidgets('still not taken by the server: kept for the next time',
        (tester) async {
      play.unfinishedPurchases = [googlePurchase(id: 'GPA.0009')];
      server.status['POST /api/billing/google/purchases'] = 502;
      await pump(tester);

      expect(play.finished, isEmpty);
      expect(play.unfinishedPurchases, hasLength(1));
    });
  });

  group('restoring', () {
    testWidgets('posts what Play restores', (tester) async {
      play.restorable = [
        googlePurchase(id: 'GPA.0005', status: StorePurchaseStatus.restored),
      ];
      await pump(tester);

      await tap(tester, _kRestore);

      expect(server.googlePurchases, ['token-GPA.0005']);
      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(_kThanks), findsOneWidget);
    });

    testWidgets('nothing to restore: says so', (tester) async {
      await pump(tester);

      await tap(tester, _kRestore);

      expect(
        find.text('No subscription to restore was found for your Google Play '
            'account.'),
        findsOneWidget,
      );
      expect(server.googlePurchases, isEmpty);
    });
  });

  group('the account screen on Android', () {
    testWidgets('free with Google selling: See Premium and the legal links',
        (tester) async {
      await pump(tester, location: '/account');

      expect(find.text('See Premium'), findsOneWidget);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      expect(find.text('Right of withdrawal'), findsNothing);

      await tap(tester, 'See Premium');
      expect(find.text(_kSubscribe), findsOneWidget);
    });

    testWidgets('Premium through Google: Manage in Google Play',
        (tester) async {
      server.billing = {...kGoogleSubscribed, 'can_manage': true};
      await pump(tester, location: '/account');

      expect(find.text(_kManageGoogle), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text('See Premium'), findsNothing);
      expect(find.text(_kManagedOnWebsite), findsNothing);
    });

    testWidgets('Premium through Stripe: a plain line, no link to Stripe',
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

      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text(_kManageGoogle), findsNothing);
      expect(find.text(_kManagedOnWebsite), findsOneWidget);
      await tester.tap(find.text(_kManagedOnWebsite));
      await tester.pumpAndSettle();
      expect(launcher.launched, isEmpty);
      expect(server.calls, isNot(contains('POST /api/billing/portal')));
    });

    testWidgets('deleting with a renewing Google subscription: says the '
        'deletion cancels it, asks nothing more of the person',
        (tester) async {
      server.billing = kGoogleSubscribed;
      await pump(tester, location: '/account');

      await tap(tester, 'Delete account');

      expect(
        find.text('Your Google Play subscription will be cancelled along '
            'with your account.'),
        findsOneWidget,
      );
      expect(find.textContaining('Apple'), findsNothing);
    });
  });
}
