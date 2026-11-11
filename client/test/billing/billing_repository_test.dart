import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/billing/billing_repository.dart';

import '../support/fakes.dart';

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

    test("in the iOS app, Stripe's portal unless Premium is Apple's", () {
      debugOnTheWeb = false;
      debugOnIos = true;
      final stripe = BillingStatus.fromJson(
        billingStatus(plan: 'premium', canManage: true),
      );
      final apple = BillingStatus.fromJson(
        {...kAppleSubscribed, 'can_manage': true},
      );
      expect(stripe.offersStripePortal, isTrue);
      expect(stripe.offersAppleManagement, isFalse);
      expect(apple.offersStripePortal, isFalse);
      expect(apple.offersAppleManagement, isTrue);
      debugOnIos = false;
      expect(stripe.offersStripePortal, isFalse);
      expect(apple.offersAppleManagement, isFalse);
    });
  });
}
