/// What the billing tests share.
library;

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/billing/billing_repository.dart';
import 'package:wishlist/src/billing/store.dart';

import '../support/fakes.dart';

/// url_launcher's platform side, recording every option: which tab a page
/// opens in is part of the checkout (PREMIUM_PLAN D18).
class RecordingUrlLauncher extends Fake
    with MockPlatformInterfaceMixin
    implements UrlLauncherPlatform {
  final launched = <({String url, LaunchOptions options})>[];

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    launched.add((url: url, options: options));
    return true;
  }
}

/// Installs a fresh [RecordingUrlLauncher] for the test.
RecordingUrlLauncher installRecordingUrlLauncher() {
  final previous = UrlLauncherPlatform.instance;
  final fake = RecordingUrlLauncher();
  UrlLauncherPlatform.instance = fake;
  addTearDown(() => UrlLauncherPlatform.instance = previous);
  return fake;
}

/// The App Store for the iOS app's tests (Apple IAP plan D3): what it sells,
/// what each step sends, and what the app asked of it.
class FakeStore implements Store {
  final _purchases = StreamController<List<StorePurchase>>.broadcast();

  /// What [product] answers; null as when the App Store cannot be reached.
  StoreProduct? storeProduct =
      const StoreProduct(id: kAppleProductId, price: '€49.99');

  /// What [unfinished] answers.
  List<StorePurchase> unfinishedPurchases = [];

  /// What a purchase sends; a bought transaction unless set.
  List<StorePurchase> Function()? onBuy;

  /// Thrown by [buy], as when StoreKit cannot open its sheet.
  Object? buyError;

  /// What [restore] sends.
  List<StorePurchase> restorable = [];

  /// Every purchase asked for, and every purchase finished.
  final bought = <({String productId, String accountId})>[];
  final finished = <String?>[];

  bool get listening => _purchases.hasListener;

  /// Sends [batch] as the store would, outside any call.
  void send(List<StorePurchase> batch) => _purchases.add(batch);

  @override
  Future<StoreProduct?> product(String id) async =>
      storeProduct?.id == id ? storeProduct : null;

  @override
  Stream<List<StorePurchase>> get purchases => _purchases.stream;

  @override
  Future<List<StorePurchase>> unfinished() async => unfinishedPurchases;

  @override
  Future<void> buy(StoreProduct product, {required String accountId}) async {
    bought.add((productId: product.id, accountId: accountId));
    if (buyError case final error?) throw error;
    _purchases.add(onBuy?.call() ?? [applePurchase()]);
  }

  @override
  Future<void> restore() async {
    if (restorable.isNotEmpty) _purchases.add(restorable);
  }

  @override
  Future<void> finish(StorePurchase purchase) async {
    finished.add(purchase.id);
    unfinishedPurchases.removeWhere((p) => p.id == purchase.id);
  }
}

/// A transaction as StoreKit gives it, its JWS named after its id.
StorePurchase applePurchase({
  String id = '2000001',
  StorePurchaseStatus status = StorePurchaseStatus.purchased,
}) =>
    StorePurchase(
      status: status,
      productId: kAppleProductId,
      id: status == StorePurchaseStatus.purchased ||
              status == StorePurchaseStatus.restored
          ? id
          : null,
      signedTransaction: status == StorePurchaseStatus.purchased ||
              status == StorePurchaseStatus.restored
          ? 'jws-$id'
          : null,
    );

/// The iOS app, buying through a fresh [FakeStore], for the test.
FakeStore installFakeStore() {
  final store = FakeStore();
  debugStore = store;
  debugOnIos = true;
  debugOnTheWeb = false;
  addTearDown(() {
    debugStore = null;
    debugOnIos = null;
    debugOnTheWeb = null;
  });
  return store;
}
