/// Google Play's billing behind [Store] (Android release plan D6, D8). The
/// only file that knows Play Billing's plugin.
library;

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';
import 'package:in_app_purchase_platform_interface/in_app_purchase_platform_interface.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'store.dart';

class GoogleStore implements Store {
  GoogleStore() {
    // What the in_app_purchase facade would do on Android.
    InAppPurchaseAndroidPlatform.registerPlatform();
  }

  @override
  StoreSource get source => StoreSource.google;

  InAppPurchasePlatform get _platform => InAppPurchasePlatform.instance;

  InAppPurchaseAndroidPlatformAddition get _addition =>
      InAppPurchasePlatformAddition.instance!
          as InAppPurchaseAndroidPlatformAddition;

  /// Play's products by id, which a purchase is made with: the base plan,
  /// not one of its offers.
  final _details = <String, GooglePlayProductDetails>{};

  final _dealtWith = DealtWithPurchases();

  /// The subscription's base plan, priced by Play. Play gives one entry per
  /// offer of the subscription; its base plan has no offer id.
  @override
  Future<StoreProduct?> product(String id) async {
    final response = await _platform.queryProductDetails({id});
    final details = response.productDetails
        .whereType<GooglePlayProductDetails>()
        .where((product) => product.id == id && _isBasePlan(product))
        .firstOrNull;
    if (details == null) return null;
    _details[id] = details;
    return StoreProduct(id: id, price: details.price);
  }

  static bool _isBasePlan(GooglePlayProductDetails product) {
    final index = product.subscriptionIndex;
    final offers = product.productDetails.subscriptionOfferDetails;
    return index != null && offers != null && offers[index].offerId == null;
  }

  @override
  Stream<List<StorePurchase>> get purchases => _platform.purchaseStream
      .map((batch) => [for (final details in batch) _purchase(details)]);

  /// The plugin marks every purchase Restore finds as restored, a pending
  /// one too: Play's own state says it is not paid yet.
  static StorePurchase _purchase(
    PurchaseDetails details, {
    StorePurchaseStatus? status,
  }) =>
      StorePurchase(
        status: status ??
            switch (details.status) {
              _ when details is GooglePlayPurchaseDetails &&
                  details.billingClientPurchase.purchaseState ==
                      PurchaseStateWrapper.pending =>
                StorePurchaseStatus.pending,
              PurchaseStatus.purchased => StorePurchaseStatus.purchased,
              PurchaseStatus.restored => StorePurchaseStatus.restored,
              PurchaseStatus.pending => StorePurchaseStatus.pending,
              PurchaseStatus.canceled => StorePurchaseStatus.cancelled,
              PurchaseStatus.error => StorePurchaseStatus.failed,
            },
        productId: details.productID,
        id: details.purchaseID,
        // The purchase token, which the server reads the subscription with.
        verificationData: details.verificationData.serverVerificationData,
      );

  /// Paid, not yet acknowledged, and not refused by the server already. The
  /// server acknowledges what it accepts (D6), so whatever is still
  /// unacknowledged may never have reached it.
  @override
  Future<List<StorePurchase>> unfinished() async {
    final response = await _addition.queryPastPurchases();
    if (response.error case final error?) {
      throw InAppPurchaseException(
        source: error.source,
        code: error.code,
        message: error.message,
      );
    }
    return _dealtWith.leaveOut([
      for (final details in response.pastPurchases)
        if (details.billingClientPurchase.purchaseState ==
                PurchaseStateWrapper.purchased &&
            !details.billingClientPurchase.isAcknowledged)
          _purchase(details, status: StorePurchaseStatus.purchased),
    ]);
  }

  /// Play ties the purchase to [accountId] as its `obfuscatedAccountId`, which
  /// the server checks (D6). Throws when Play does not open its sheet, as
  /// when the Play account already has the subscription.
  @override
  Future<void> buy(StoreProduct product, {required String accountId}) async {
    final launched = await _platform.buyNonConsumable(
      purchaseParam: PurchaseParam(
        productDetails: _details[product.id]!,
        applicationUserName: accountId,
      ),
    );
    if (!launched) throw StateError('Play did not open its purchase sheet');
  }

  @override
  Future<void> restore() => _platform.restorePurchases();

  /// Never acknowledges: the plugin's `completePurchase` would, and the
  /// server acknowledges what it accepts and leaves what it refuses for
  /// Google to refund (D6). A refusal is set aside instead, so it is not
  /// sent again at each start; unless it was only another account's, which
  /// may sign in here and take it.
  @override
  Future<void> finish(
    StorePurchase purchase, {
    bool otherAccount = false,
  }) async {
    final token = purchase.verificationData;
    if (otherAccount || token == null || token.isEmpty) return;
    await _dealtWith.add(token);
  }
}

/// The purchase tokens the server has dealt with that Play still lists as
/// unacknowledged: the refused ones, until Google refunds them. Kept on the
/// device, and forgotten once Play no longer lists them.
@visibleForTesting
class DealtWithPurchases {
  static const key = 'google_play_dealt_with';

  Future<void> add(String token) async {
    final prefs = await SharedPreferences.getInstance();
    final tokens = prefs.getStringList(key) ?? const [];
    if (!tokens.contains(token)) {
      await prefs.setStringList(key, [...tokens, token]);
    }
  }

  /// [waiting] without those dealt with; forgets those Play no longer lists.
  Future<List<StorePurchase>> leaveOut(List<StorePurchase> waiting) async {
    final prefs = await SharedPreferences.getInstance();
    final tokens = prefs.getStringList(key) ?? const [];
    final listed = {for (final purchase in waiting) purchase.verificationData};
    final kept = [
      for (final token in tokens)
        if (listed.contains(token)) token,
    ];
    if (kept.length != tokens.length) await prefs.setStringList(key, kept);
    return [
      for (final purchase in waiting)
        if (!kept.contains(purchase.verificationData)) purchase,
    ];
  }
}
