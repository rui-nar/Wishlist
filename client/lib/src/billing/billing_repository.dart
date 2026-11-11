/// The user's plan, and the server-made links to Stripe (PREMIUM_PLAN D11).
library;

import 'dart:async';

import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb, visibleForTesting;
import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../lists/gift_links.dart';
import 'android_host_io.dart'
    if (dart.library.js_interop) 'android_host_web.dart';
import 'store.dart';

const kPlanPath = '/account/plan';

const _kPath = '/api/billing';

/// A route that calls Stripe can take this long on the server (PREMIUM_PLAN,
/// Review envelope), well past the API client's default.
const _kStripeTimeout = Duration(seconds: 45);

/// Stands in for [kIsWeb] in tests.
@visibleForTesting
bool? debugOnTheWeb;

/// Stripe's purchases and links exist on the web only (PREMIUM_PLAN D18).
bool get onTheWeb => debugOnTheWeb ?? kIsWeb;

/// Stands in for the platform in tests.
@visibleForTesting
bool? debugOnIos;

/// The iOS app, which sells through Apple (Apple IAP plan D7, D8).
bool get onIos =>
    debugOnIos ?? (!kIsWeb && defaultTargetPlatform == TargetPlatform.iOS);

/// Stands in for the platform in tests.
@visibleForTesting
bool? debugOnAndroid;

/// The Android app, which sells through Google Play (Android release plan
/// D8). The device's system, not [defaultTargetPlatform], which tests set to
/// Android: Play's billing exists on a real Android only.
bool get onAndroid => debugOnAndroid ?? (!kIsWeb && runsOnAndroid);

/// The store that sells in this app: Apple's in the iOS app, Google Play's
/// in the Android app; null on the web.
StoreSource? get appStore => onIos
    ? StoreSource.apple
    : onAndroid
        ? StoreSource.google
        : null;

/// Where an Apple subscription is managed or cancelled; the server cannot
/// (D9).
const kAppleSubscriptionsUrl = 'https://apps.apple.com/account/subscriptions';

/// Play's subscriptions page, where a Google Play subscription is managed or
/// cancelled (Android release plan D8). Play's documented link for all of
/// them: the one for a single subscription needs the app's package name,
/// which the app does not know apart from its build.
const kGoogleSubscriptionsUrl =
    'https://play.google.com/store/account/subscriptions';

/// Apple's standard licence: the terms of a purchase in the iOS app when the
/// server names none (D8).
const kAppleStandardEulaUrl =
    'https://www.apple.com/legal/internet-services/itunes/dev/stdeula/';

/// What the iOS app sells (D7); its price is the App Store's.
class AppleOffer {
  const AppleOffer({required this.productId});

  final String productId;
}

/// What the Android app sells (Android release plan D7); its price is
/// Play's.
class GoogleOffer {
  const GoogleOffer({required this.productId});

  final String productId;
}

/// What is on sale. `amount` is the server's decimal string.
class BillingOffer {
  const BillingOffer({required this.amount, required this.currency});

  factory BillingOffer.fromJson(Map<String, dynamic> json) => BillingOffer(
        amount: json['amount'] as String,
        currency: json['currency'] as String,
      );

  final String amount;
  final String currency;
}

/// Where the legal texts are; null is the app's own placeholder page (D17).
class LegalUrls {
  const LegalUrls({this.terms, this.privacy, this.withdrawal});

  factory LegalUrls.fromJson(Map<String, dynamic> json) => LegalUrls(
        terms: json['terms_url'] as String?,
        privacy: json['privacy_url'] as String?,
        withdrawal: json['withdrawal_url'] as String?,
      );

  final String? terms;
  final String? privacy;
  final String? withdrawal;
}

/// `GET /api/billing`. The client decides nothing from it but what to show.
class BillingStatus {
  const BillingStatus({
    required this.isPremium,
    this.source,
    required this.status,
    required this.renewsAt,
    required this.endsAt,
    required this.maxLists,
    required this.maxGiftsPerList,
    required this.enforced,
    required this.offer,
    this.appleOffer,
    this.appleRenewing = false,
    this.googleOffer,
    this.googleRenewing = false,
    required this.canManage,
    required this.legal,
  });

  factory BillingStatus.fromJson(Map<String, dynamic> json) {
    final limits = json['limits'] as Map<String, dynamic>?;
    final offer = json['offer'] as Map<String, dynamic>?;
    final appleOffer = json['apple_offer'] as Map<String, dynamic>?;
    final googleOffer = json['google_offer'] as Map<String, dynamic>?;
    return BillingStatus(
      isPremium: json['plan'] == 'premium',
      source: json['source'] as String?,
      status: json['status'] as String?,
      renewsAt: _date(json['renews_at']),
      endsAt: _date(json['ends_at']),
      maxLists: (limits?['max_lists'] as num?)?.toInt(),
      maxGiftsPerList: (limits?['max_gifts_per_list'] as num?)?.toInt(),
      enforced: json['enforced'] as bool,
      offer: offer == null ? null : BillingOffer.fromJson(offer),
      appleOffer: appleOffer == null
          ? null
          : AppleOffer(productId: appleOffer['product_id'] as String),
      appleRenewing: json['apple_renewing'] as bool,
      googleOffer: googleOffer == null
          ? null
          : GoogleOffer(productId: googleOffer['product_id'] as String),
      googleRenewing: json['google_renewing'] as bool,
      canManage: json['can_manage'] as bool,
      legal: LegalUrls.fromJson(json['legal'] as Map<String, dynamic>),
    );
  }

  static DateTime? _date(Object? value) =>
      value == null ? null : DateTime.parse(value as String);

  final bool isPremium;

  /// Where Premium comes from: `stripe`, `apple`, `google`, or `manual` when
  /// the admin granted it (admin panel plan D8). Null on the free plan.
  final String? source;

  /// Granted by the admin, until [renewsAt]: nothing renews or is paid.
  bool get isManual => source == 'manual';

  /// Null, `active`, `past_due` or `canceling`.
  final String? status;
  final DateTime? renewsAt;
  final DateTime? endsAt;

  /// Null for premium.
  final int? maxLists;
  final int? maxGiftsPerList;
  final bool enforced;

  /// Stripe's, for the web; null unless the server sells through Stripe.
  final BillingOffer? offer;

  /// Apple's, for the iOS app; null unless the server sells through Apple.
  final AppleOffer? appleOffer;

  /// An Apple subscription of the account is set to renew, whatever the plan
  /// says: deleting the account does not stop it (Apple IAP plan D9).
  final bool appleRenewing;

  /// Google Play's, for the Android app; null unless the server sells through
  /// Google (Android release plan D7).
  final GoogleOffer? googleOffer;

  /// A Google subscription of the account may still charge. Deleting the
  /// account cancels it first (Android release plan D6).
  final bool googleRenewing;

  /// A Stripe customer exists and the portal would serve.
  final bool canManage;
  final LegalUrls legal;

  bool get isPastDue => status == 'past_due';

  /// Premium through Apple, or an Apple subscription that may still charge:
  /// Apple's page manages it (D8).
  bool get managedAtApple => source == 'apple' || appleRenewing;

  /// Premium through Google Play, or a Google subscription that may still
  /// charge: Play's page manages it (Android release plan D8).
  bool get managedAtGoogle => source == 'google' || googleRenewing;

  /// The product the phone's store sells here: Apple's in the iOS app,
  /// Google Play's in the Android app; null elsewhere, or when not on sale.
  String? get storeProductId => switch (appStore) {
        StoreSource.apple => appleOffer?.productId,
        StoreSource.google => googleOffer?.productId,
        null => null,
      };

  /// Something is on sale on this platform: Stripe's on the web, Apple's in
  /// the iOS app (D7), Google Play's in the Android app.
  bool get offeredHere => appStore != null
      ? storeProductId != null
      : onTheWeb && offer != null;

  /// Stripe's portal is offered: on the web only. Apple's and Google Play's
  /// rules forbid steering to a payment page outside the store, so the phone
  /// apps link to none.
  bool get offersStripePortal => canManage && onTheWeb;

  /// Premium bought through Stripe, seen in a phone app: one plain line says
  /// it is managed on the website, with no link and no address.
  bool get managedOnTheWebsite => !onTheWeb && source == 'stripe';

  /// Apple's subscriptions page is offered: in the iOS app (D8).
  bool get offersAppleManagement => onIos && managedAtApple;

  /// Play's subscriptions page is offered: in the Android app.
  bool get offersGoogleManagement => onAndroid && managedAtGoogle;

  /// Free, nothing on sale, no limit applied and nothing at a store to
  /// manage: the account screen stays as it was before plans existed (D18).
  bool get nothingToShow =>
      !isPremium &&
      offer == null &&
      appleOffer == null &&
      googleOffer == null &&
      !enforced &&
      !appleRenewing &&
      !googleRenewing;
}

class BillingRepository {
  BillingRepository(this._api);

  factory BillingRepository.of(BuildContext context) =>
      BillingRepository(context.read<ApiClient>());

  final ApiClient _api;

  Future<BillingStatus> status() async =>
      BillingStatus.fromJson(await _api.getJson(_kPath));

  /// A Stripe Checkout page for this user.
  Future<String> startCheckout() => _stripeUrl('$_kPath/checkout');

  /// A Stripe Customer Portal page for this user.
  Future<String> openPortal() => _stripeUrl('$_kPath/portal');

  /// Reports a purchase or a restore made in the iOS app (Apple IAP plan D3):
  /// completes on the server's 204, and throws the [ApiClient] errors, a
  /// refusal's `code` in [ApiException.body].
  Future<void> reportAppleTransaction(String signedTransaction) => _api.post(
        '$_kPath/apple/transactions',
        body: {'signed_transaction': signedTransaction},
        // The server asks Apple: as long as a call to Stripe.
        timeout: _kStripeTimeout,
      );

  /// Reports a purchase or a restore made in the Android app (Android release
  /// plan D6), by its purchase token: as [reportAppleTransaction]. The server
  /// acknowledges the purchase before its 204.
  Future<void> reportGooglePurchase(String purchaseToken) => _api.post(
        '$_kPath/google/purchases',
        body: {'purchase_token': purchaseToken},
        // The server reads and acknowledges it at Google.
        timeout: _kStripeTimeout,
      );

  /// What reports [store]'s purchases: each store's on its own route.
  Future<void> Function(String) reporterFor(Store store) =>
      switch (store.source) {
        StoreSource.apple => reportAppleTransaction,
        StoreSource.google => reportGooglePurchase,
      };

  Future<String> _stripeUrl(String path) async =>
      (await _api.postJson(path, const {}, timeout: _kStripeTimeout))['url']
          as String;
}

/// Sends this tab to [url], one of Stripe's pages, which comes back by
/// redirecting the browser (D18). False when it could not be opened.
Future<bool> openInThisTab(String url) async {
  final uri = webLink(url);
  if (uri == null) return false;
  try {
    return await launchUrl(uri, webOnlyWindowName: '_self');
  } catch (_) {
    return false;
  }
}
