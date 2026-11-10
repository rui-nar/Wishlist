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
  });
}
