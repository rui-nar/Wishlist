/// Apple's App Store behind [Store], with StoreKit 2 (Apple IAP plan D3).
/// The only file that knows StoreKit's plugin.
library;

import 'package:in_app_purchase_platform_interface/in_app_purchase_platform_interface.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';
import 'package:in_app_purchase_storekit/store_kit_2_wrappers.dart';

import 'store.dart';

class AppleStore implements Store {
  AppleStore() {
    // What the in_app_purchase facade would do on iOS; StoreKit 2 is the
    // plugin's default.
    InAppPurchaseStoreKitPlatform.registerPlatform();
  }

  @override
  StoreSource get source => StoreSource.apple;

  InAppPurchasePlatform get _platform => InAppPurchasePlatform.instance;

  /// StoreKit's products by id, which a purchase is made with.
  final _details = <String, ProductDetails>{};

  @override
  Future<StoreProduct?> product(String id) async {
    final response = await _platform.queryProductDetails({id});
    final details =
        response.productDetails.where((product) => product.id == id).firstOrNull;
    if (details == null) return null;
    _details[id] = details;
    return StoreProduct(id: id, price: details.price);
  }

  @override
  Stream<List<StorePurchase>> get purchases => _platform.purchaseStream
      .map((batch) => [for (final details in batch) _purchase(details)]);

  static StorePurchase _purchase(PurchaseDetails details) => StorePurchase(
        status: switch (details.status) {
          PurchaseStatus.purchased => StorePurchaseStatus.purchased,
          PurchaseStatus.restored => StorePurchaseStatus.restored,
          PurchaseStatus.pending => StorePurchaseStatus.pending,
          PurchaseStatus.canceled => StorePurchaseStatus.cancelled,
          PurchaseStatus.error => StorePurchaseStatus.failed,
        },
        productId: details.productID,
        id: details.purchaseID,
        // The transaction's JWS under StoreKit 2.
        verificationData: details.verificationData.serverVerificationData,
      );

  @override
  Future<List<StorePurchase>> unfinished() async => [
        for (final transaction in await SK2Transaction.unfinishedTransactions())
          StorePurchase(
            status: StorePurchaseStatus.purchased,
            productId: transaction.productId,
            id: transaction.id,
            verificationData: transaction.receiptData,
          ),
      ];

  /// The plugin hands [accountId] to StoreKit as the `appAccountToken`
  /// (D2), and drops it silently unless it is a UUID, which an account id is.
  @override
  Future<void> buy(StoreProduct product, {required String accountId}) =>
      _platform.buyNonConsumable(
        purchaseParam: PurchaseParam(
          productDetails: _details[product.id]!,
          applicationUserName: accountId,
        ),
      );

  @override
  Future<void> restore() => _platform.restorePurchases();

  /// Finished whatever the server said, as StoreKit would resend it
  /// otherwise; another account takes it through Restore.
  @override
  Future<void> finish(
    StorePurchase purchase, {
    bool otherAccount = false,
  }) async {
    final id = int.tryParse(purchase.id ?? '');
    if (id != null) await SK2Transaction.finish(id);
  }
}
