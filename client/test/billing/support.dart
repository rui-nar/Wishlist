/// What the billing tests share.
library;

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:shushgift/src/billing/billing_repository.dart';
import 'package:shushgift/src/billing/store.dart';

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
/// A phone's store for the tests (Apple IAP plan D3, Android release plan
/// D6): the App Store unless [source] says Google Play; what it sells, what
/// each step sends, and what the app asked of it.
class FakeStore implements Store {
  FakeStore({this.source = StoreSource.apple});

  @override
  final StoreSource source;

  final _purchases = StreamController<List<StorePurchase>>.broadcast();

  /// What [product] answers; null as when the store cannot be reached.
  late StoreProduct? storeProduct = StoreProduct(
    id: source == StoreSource.apple ? kAppleProductId : kGoogleProductId,
    price: '€49.99',
  );

  /// What [unfinished] answers.
  List<StorePurchase> unfinishedPurchases = [];

  /// What a purchase sends; a bought purchase unless set.
  List<StorePurchase> Function()? onBuy;

  /// Thrown by [buy], as when the store cannot open its sheet.
  Object? buyError;

  /// What [restore] sends.
  List<StorePurchase> restorable = [];

  /// Every purchase asked for, and every purchase finished, with those
  /// finished as only another account's.
  final bought = <({String productId, String accountId})>[];
  final finished = <String?>[];
  final finishedForOtherAccount = <String?>[];

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
    _purchases.add(
      onBuy?.call() ??
          [
            source == StoreSource.apple
                ? applePurchase()
                : googlePurchase(),
          ],
    );
  }

  @override
  Future<void> restore() async {
    if (restorable.isNotEmpty) _purchases.add(restorable);
  }

  @override
  Future<void> finish(
    StorePurchase purchase, {
    bool otherAccount = false,
  }) async {
    finished.add(purchase.id);
    if (otherAccount) finishedForOtherAccount.add(purchase.id);
    unfinishedPurchases.removeWhere((p) => p.id == purchase.id);
  }
}

bool _paid(StorePurchaseStatus status) =>
    status == StorePurchaseStatus.purchased ||
    status == StorePurchaseStatus.restored;

/// A transaction as StoreKit gives it, its JWS named after its id.
StorePurchase applePurchase({
  String id = '2000001',
  StorePurchaseStatus status = StorePurchaseStatus.purchased,
}) =>
    StorePurchase(
      status: status,
      productId: kAppleProductId,
      id: _paid(status) ? id : null,
      verificationData: _paid(status) ? 'jws-$id' : null,
    );

/// A purchase as Play Billing gives it: an order id once paid, and a token
/// named after it, which a pending purchase already has.
StorePurchase googlePurchase({
  String id = 'GPA.0001',
  StorePurchaseStatus status = StorePurchaseStatus.purchased,
}) =>
    StorePurchase(
      status: status,
      productId: kGoogleProductId,
      id: _paid(status) ? id : null,
      verificationData: status == StorePurchaseStatus.cancelled ||
              status == StorePurchaseStatus.failed
          ? null
          : 'token-$id',
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

/// The Android app, buying through a fresh Google Play [FakeStore], for the
/// test.
FakeStore installFakeGoogleStore() {
  final store = FakeStore(source: StoreSource.google);
  debugStore = store;
  debugOnAndroid = true;
  debugOnIos = false;
  debugOnTheWeb = false;
  addTearDown(() {
    debugStore = null;
    debugOnAndroid = null;
    debugOnIos = null;
    debugOnTheWeb = null;
  });
  return store;
}
