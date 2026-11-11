import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/billing/billing_repository.dart';
import 'package:wishlist/src/billing/store.dart';

import '../support/fakes.dart';
import 'support.dart';

void main() {
  test('reads a premium status, its dates in UTC', () {
    final status = BillingStatus.fromJson(
      billingStatus(
        plan: 'premium',
        status: 'past_due',
        renewsAt: '2027-03-12T10:00:00Z',
        limits: const {'max_lists': null, 'max_gifts_per_list': null},
        canManage: true,
      ),
    );

    expect(status.isPremium, isTrue);
    expect(status.isPastDue, isTrue);
    expect(status.renewsAt, DateTime.utc(2027, 3, 12, 10));
    expect(status.endsAt, isNull);
    expect(status.maxLists, isNull);
    expect(status.maxGiftsPerList, isNull);
    expect(status.canManage, isTrue);
    expect(status.nothingToShow, isFalse);
  });

  test('reads an offer, limits and legal addresses', () {
    final status = BillingStatus.fromJson(
      billingStatus(
        enforced: true,
        offer: kBillingOffer,
        legal: const {
          'terms_url': 'https://example.test/terms',
          'privacy_url': null,
          'withdrawal_url': null,
        },
      ),
    );

    expect(status.isPremium, isFalse);
    expect(status.maxLists, 1);
    expect(status.maxGiftsPerList, 20);
    expect(status.enforced, isTrue);
    expect(status.offer!.amount, '49.00');
    expect(status.offer!.currency, 'EUR');
    expect(status.legal.terms, 'https://example.test/terms');
    expect(status.legal.privacy, isNull);
  });

  group('nothingToShow (D18)', () {
    BillingStatus free({bool enforced = false, Object? offer}) =>
        BillingStatus.fromJson(
          billingStatus(
            enforced: enforced,
            offer: offer as Map<String, Object?>?,
          ),
        );

    test('free, no offer, not enforced', () {
      expect(free().nothingToShow, isTrue);
    });

    test('an offer, or enforcement, is something to show', () {
      expect(free(offer: kBillingOffer).nothingToShow, isFalse);
      expect(free(enforced: true).nothingToShow, isFalse);
    });

    test("Apple's offer, or an Apple subscription that renews, too", () {
      expect(
        BillingStatus.fromJson(billingStatus(appleOffer: kAppleOffer))
            .nothingToShow,
        isFalse,
      );
      expect(
        BillingStatus.fromJson(billingStatus(appleRenewing: true))
            .nothingToShow,
        isFalse,
      );
    });
  });

  test("reads Apple's offer and renewal (Apple IAP plan D7, D9)", () {
    final status = BillingStatus.fromJson(kAppleSubscribed);

    expect(status.appleOffer!.productId, kAppleProductId);
    expect(status.appleRenewing, isTrue);
    expect(status.source, 'apple');
    expect(status.managedAtApple, isTrue);
    expect(BillingStatus.fromJson(billingStatus()).appleOffer, isNull);
    expect(BillingStatus.fromJson(billingStatus()).managedAtApple, isFalse);
  });

  test('reads the answer of a server one release older (review IAP-R3-2)',
      () {
    // GET /api/billing before the store releases: no apple_* or google_*.
    final status = BillingStatus.fromJson(const {
      'plan': 'premium',
      'source': 'stripe',
      'status': 'active',
      'renews_at': '2027-03-12T10:00:00Z',
      'ends_at': null,
      'limits': {'max_lists': null, 'max_gifts_per_list': null},
      'enforced': true,
      'offer': {'amount': '49.00', 'currency': 'EUR', 'interval': 'year'},
      'can_manage': true,
      'legal': {'terms_url': null, 'privacy_url': null, 'withdrawal_url': null},
    });

    expect(status.isPremium, isTrue);
    expect(status.offer!.amount, '49.00');
    expect(status.appleOffer, isNull);
    expect(status.appleRenewing, isFalse);
    expect(status.googleOffer, isNull);
    expect(status.googleRenewing, isFalse);
    expect(status.canManage, isTrue);
  });

  group('what each platform offers (D7, D8)', () {
    tearDown(() {
      debugOnTheWeb = null;
      debugOnIos = null;
    });
    final both = BillingStatus.fromJson(
      billingStatus(offer: kBillingOffer, appleOffer: kAppleOffer),
    );

    test("the web sells Stripe's offer, the iOS app Apple's, Android none",
        () {
      debugOnTheWeb = true;
      debugOnIos = false;
      expect(both.offeredHere, isTrue);
      expect(
        BillingStatus.fromJson(billingStatus(appleOffer: kAppleOffer))
            .offeredHere,
        isFalse,
      );
      debugOnTheWeb = false;
      debugOnIos = true;
      expect(both.offeredHere, isTrue);
      expect(
        BillingStatus.fromJson(billingStatus(offer: kBillingOffer))
            .offeredHere,
        isFalse,
      );
      debugOnIos = false;
      expect(both.offeredHere, isFalse);
    });

    test("Stripe's portal on the web only; the iOS app says where Stripe's "
        'Premium is managed', () {
      final stripe = BillingStatus.fromJson(
        billingStatus(plan: 'premium', canManage: true),
      );
      final apple = BillingStatus.fromJson(
        {...kAppleSubscribed, 'can_manage': true},
      );
      final granted = BillingStatus.fromJson(
        billingStatus(plan: 'premium', source: 'manual', canManage: true),
      );
      debugOnTheWeb = true;
      debugOnIos = false;
      expect(stripe.offersStripePortal, isTrue);
      expect(stripe.managedOnTheWebsite, isFalse);

      debugOnTheWeb = false;
      debugOnIos = true;
      expect(stripe.offersStripePortal, isFalse);
      expect(stripe.managedOnTheWebsite, isTrue);
      expect(stripe.offersAppleManagement, isFalse);
      expect(apple.offersStripePortal, isFalse);
      expect(apple.managedOnTheWebsite, isFalse);
      expect(apple.offersAppleManagement, isTrue);
      expect(granted.offersStripePortal, isFalse);
      expect(granted.managedOnTheWebsite, isFalse);
      debugOnIos = false;
      expect(stripe.offersStripePortal, isFalse);
      expect(apple.offersAppleManagement, isFalse);
    });

    test("in the Android app, Google Play's offer, and never Stripe's portal "
        '(Android release plan D8)', () {
      debugOnTheWeb = false;
      debugOnIos = false;
      debugOnAndroid = true;
      addTearDown(() => debugOnAndroid = null);
      final selling = BillingStatus.fromJson(
        billingStatus(offer: kBillingOffer, googleOffer: kGoogleOffer),
      );
      expect(selling.offeredHere, isTrue);
      expect(selling.storeProductId, kGoogleProductId);
      expect(both.offeredHere, isFalse);
      expect(both.storeProductId, isNull);

      final stripe = BillingStatus.fromJson(
        billingStatus(plan: 'premium', canManage: true),
      );
      final google = BillingStatus.fromJson(
        {...kGoogleSubscribed, 'can_manage': true},
      );
      expect(stripe.offersStripePortal, isFalse);
      expect(stripe.managedOnTheWebsite, isTrue);
      expect(stripe.offersGoogleManagement, isFalse);
      expect(google.offersStripePortal, isFalse);
      expect(google.managedOnTheWebsite, isFalse);
      expect(google.offersGoogleManagement, isTrue);
      expect(google.offersAppleManagement, isFalse);

      debugOnAndroid = false;
      expect(selling.offeredHere, isFalse);
      expect(google.offersGoogleManagement, isFalse);
    });
  });

  test("reads Google Play's offer and renewal (Android release plan D7)", () {
    final status = BillingStatus.fromJson(kGoogleSubscribed);

    expect(status.googleOffer!.productId, kGoogleProductId);
    expect(status.googleRenewing, isTrue);
    expect(status.source, 'google');
    expect(status.managedAtGoogle, isTrue);
    expect(BillingStatus.fromJson(billingStatus()).googleOffer, isNull);
    expect(BillingStatus.fromJson(billingStatus()).managedAtGoogle, isFalse);
    expect(
      BillingStatus.fromJson(billingStatus(googleRenewing: true))
          .managedAtGoogle,
      isTrue,
    );
  });

  test("Google's offer, or a Google subscription that renews, is something "
      'to show', () {
    expect(
      BillingStatus.fromJson(billingStatus(googleOffer: kGoogleOffer))
          .nothingToShow,
      isFalse,
    );
    expect(
      BillingStatus.fromJson(billingStatus(googleRenewing: true))
          .nothingToShow,
      isFalse,
    );
  });

  group('reporting a store purchase', () {
    late FakeServer server;
    late BillingRepository repository;

    setUp(() {
      server = FakeServer();
      final api = ApiClient(server.client, baseUrl: kApiBase)
        ..token = server.addSession();
      repository = BillingRepository(api);
    });

    test("Apple's to Apple's route, Google's to Google's", () async {
      await repository.reporterFor(FakeStore())('jws-1');
      await repository.reporterFor(
        FakeStore(source: StoreSource.google),
      )('token-1');

      expect(server.appleTransactions, ['jws-1']);
      expect(server.googlePurchases, ['token-1']);
    });
  });
}
