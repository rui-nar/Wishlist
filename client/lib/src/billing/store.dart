/// A phone's app store, as the plan screen buys through it (Apple IAP plan
/// D3): Apple's in the iOS app, Google Play's in the Android app (Android
/// release plan D8), behind the same interface.
library;

import 'package:flutter/foundation.dart' show visibleForTesting;

import 'apple_store.dart';
import 'billing_repository.dart';
import 'google_store.dart';

/// Which store sells: the server checks each one's purchases on its own
/// route.
enum StoreSource { apple, google }

/// The subscription as the store sells it in the buyer's storefront.
class StoreProduct {
  const StoreProduct({required this.id, required this.price});

  final String id;

  /// The store's localised price, currency included (D1): never the server's
  /// amount.
  final String price;
}

enum StorePurchaseStatus { purchased, restored, pending, cancelled, failed }

/// A purchase as the store reports it.
class StorePurchase {
  const StorePurchase({
    required this.status,
    required this.productId,
    this.id,
    this.verificationData,
  });

  final StorePurchaseStatus status;
  final String productId;

  /// The store's transaction or order id; null while pending or cancelled.
  final String? id;

  /// What the server checks with the store: Apple's signed transaction (a
  /// JWS), Google's purchase token. Never logged.
  final String? verificationData;

  /// Bought or restored, with what the server needs to check it.
  bool get reportable =>
      (status == StorePurchaseStatus.purchased ||
          status == StorePurchaseStatus.restored) &&
      (verificationData?.isNotEmpty ?? false);
}

/// What the app asks of a store. The store's own types stay behind it.
abstract interface class Store {
  StoreSource get source;

  /// Null when the store does not sell it here, or cannot be reached.
  Future<StoreProduct?> product(String id);

  /// Purchases as they happen: bought, restored, waiting or given up.
  Stream<List<StorePurchase>> get purchases;

  /// Bought earlier and not yet finished: the server may not have them.
  Future<List<StorePurchase>> unfinished();

  /// Opens the store's purchase sheet for [product], tied to [accountId]
  /// (D2). What happens next comes through [purchases].
  Future<void> buy(StoreProduct product, {required String accountId});

  /// Sends what the store still grants through [purchases], as restored.
  Future<void> restore();

  /// Tells the store the purchase is dealt with, so it stops resending it.
  /// [otherAccount] when the server refused it only because another account
  /// is signed in: that account may still take it.
  Future<void> finish(StorePurchase purchase, {bool otherAccount = false});
}

/// Stands in for the device's store in tests.
@visibleForTesting
Store? debugStore;

Store? _deviceStore;

/// The store this app buys through: Apple's in the iOS app, Google Play's in
/// the Android app, none elsewhere.
Store? get deviceStore =>
    debugStore ??
    (onIos
        ? _deviceStore ??= AppleStore()
        : onAndroid
            ? _deviceStore ??= GoogleStore()
            : null);
