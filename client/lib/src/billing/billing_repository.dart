/// The user's plan, and the server-made links to Stripe (PREMIUM_PLAN D11).
library;

import 'package:flutter/foundation.dart' show kIsWeb, visibleForTesting;
import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../lists/gift_links.dart';

const kPlanPath = '/account/plan';

const _kPath = '/api/billing';

/// A route that calls Stripe can take this long on the server (PREMIUM_PLAN,
/// Review envelope), well past the API client's default.
const _kStripeTimeout = Duration(seconds: 45);

/// Stands in for [kIsWeb] in tests.
@visibleForTesting
bool? debugOnTheWeb;

/// Purchases and their links exist on the web only (PREMIUM_PLAN D18).
bool get onTheWeb => debugOnTheWeb ?? kIsWeb;

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
    required this.status,
    required this.renewsAt,
    required this.endsAt,
    required this.maxLists,
    required this.maxGiftsPerList,
    required this.enforced,
    required this.offer,
    required this.canManage,
    required this.legal,
  });

  factory BillingStatus.fromJson(Map<String, dynamic> json) {
    final limits = json['limits'] as Map<String, dynamic>?;
    final offer = json['offer'] as Map<String, dynamic>?;
    return BillingStatus(
      isPremium: json['plan'] == 'premium',
      status: json['status'] as String?,
      renewsAt: _date(json['renews_at']),
      endsAt: _date(json['ends_at']),
      maxLists: (limits?['max_lists'] as num?)?.toInt(),
      maxGiftsPerList: (limits?['max_gifts_per_list'] as num?)?.toInt(),
      enforced: json['enforced'] as bool,
      offer: offer == null ? null : BillingOffer.fromJson(offer),
      canManage: json['can_manage'] as bool,
      legal: LegalUrls.fromJson(json['legal'] as Map<String, dynamic>),
    );
  }

  static DateTime? _date(Object? value) =>
      value == null ? null : DateTime.parse(value as String);

  final bool isPremium;

  /// Null, `active`, `past_due` or `canceling`.
  final String? status;
  final DateTime? renewsAt;
  final DateTime? endsAt;

  /// Null for premium.
  final int? maxLists;
  final int? maxGiftsPerList;
  final bool enforced;

  /// Null unless the server is selling.
  final BillingOffer? offer;

  /// A Stripe customer exists and the portal would serve.
  final bool canManage;
  final LegalUrls legal;

  bool get isPastDue => status == 'past_due';

  /// Free, nothing on sale and no limit applied: the account screen stays as
  /// it was before plans existed (D18).
  bool get nothingToShow => !isPremium && offer == null && !enforced;
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
