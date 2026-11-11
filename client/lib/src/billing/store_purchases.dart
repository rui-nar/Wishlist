/// Reports what a store sold to the server, and finishes it there only once
/// the server has it (Apple IAP plan D3, Android release plan D6).
library;

import 'dart:async';

import '../api/api_client.dart';
import 'store.dart';

/// What came of a purchase, for the screen to say.
enum StoreOutcome {
  /// The server recorded it.
  accepted,

  /// Waiting for someone's approval (Ask to Buy) or the bank's.
  pending,
  cancelled,

  /// The store failed before charging.
  failed,

  /// The server refused it for good: it belongs to another account.
  otherAccount,

  /// The server refused it for good: a test purchase on the real server.
  sandboxRefused,

  /// The server refused it for good: a real purchase on the test server,
  /// which Google refunds.
  realRefused,

  /// The server refused it for good: not something it sells or knows.
  notValid,

  /// The server could not take it now. It stays unfinished, so the store
  /// sends it again.
  unconfirmed,
}

/// The server's refusals that no retry changes (`billing/router.py`), Apple's
/// and Google's, and what each means here.
const _kDefinitive = {
  'invalid_transaction': StoreOutcome.notValid,
  'invalid_purchase': StoreOutcome.notValid,
  'other_product': StoreOutcome.notValid,
  'unknown_transaction': StoreOutcome.notValid,
  'unknown_purchase': StoreOutcome.notValid,
  'other_account': StoreOutcome.otherAccount,
  'sandbox_refused': StoreOutcome.sandboxRefused,
  'test_refused': StoreOutcome.sandboxRefused,
  'real_refused': StoreOutcome.realRefused,
};

/// Listens to [store] while started, one purchase at a time, in order.
///
/// One for the app, started while someone is signed in, whatever page is
/// shown: a purchase approved later, a renewal or a refund is reported and
/// finished as it comes. The plan page buys and restores through it.
class StorePurchases {
  StorePurchases({required this.store, required this.report});

  final Store store;

  /// Sends a purchase's verification data to the server, on the route of
  /// [store]'s source: completes on its 204, throws as [ApiClient] does
  /// otherwise.
  final Future<void> Function(String verificationData) report;

  /// What each purchase came to, for the plan page while it is open. Sync,
  /// so an outcome is out by the time [buy] or [restore] completes.
  Stream<StoreOutcome> get outcomes => _outcomes.stream;
  final _outcomes = StreamController<StoreOutcome>.broadcast(sync: true);

  StreamSubscription<List<StorePurchase>>? _subscription;
  Future<void> _queue = Future.value();

  /// Restored purchases seen since [restore] began.
  int _restored = 0;

  bool get isListening => _subscription != null;

  /// Listens first, so nothing the store sends is missed, then picks up what
  /// an earlier run left unfinished. Nothing when already listening.
  void start() {
    if (_subscription != null) return;
    _subscription = store.purchases.listen(_enqueue);
    _enqueue(null);
  }

  /// Stops listening, at sign-out: what the store sends meanwhile stays
  /// unfinished, and comes back with the next [start].
  Future<void> stop() async {
    final subscription = _subscription;
    _subscription = null;
    await subscription?.cancel();
  }

  Future<void> dispose() async {
    await stop();
    await _outcomes.close();
  }

  void _onOutcome(StoreOutcome outcome) {
    if (!_outcomes.isClosed) _outcomes.add(outcome);
  }

  /// Buys [product] for [accountId]; done once its outcome is out. Throws
  /// when the store could not open its sheet.
  Future<void> buy(StoreProduct product, String accountId) async {
    await store.buy(product, accountId: accountId);
    await _settled();
  }

  /// Restores; true when the store had anything to restore.
  Future<bool> restore() async {
    _restored = 0;
    await store.restore();
    await _settled();
    return _restored > 0;
  }

  /// Once what the store has sent so far is dealt with: its events may
  /// arrive just after its call returns.
  Future<void> _settled() async {
    await Future<void>.delayed(Duration.zero);
    await _queue;
  }

  /// [batch], or the unfinished purchases when null, after those before.
  void _enqueue(List<StorePurchase>? batch) {
    _queue = _queue.then((_) async {
      try {
        for (final purchase in batch ?? await store.unfinished()) {
          await _handle(purchase);
        }
      } catch (_) {
        // The store could not list them: they come back with the next start.
      }
    });
  }

  Future<void> _handle(StorePurchase purchase) async {
    switch (purchase.status) {
      case StorePurchaseStatus.pending:
        _onOutcome(StoreOutcome.pending);
        return;
      case StorePurchaseStatus.cancelled:
        _onOutcome(StoreOutcome.cancelled);
        return;
      case StorePurchaseStatus.failed:
        _onOutcome(StoreOutcome.failed);
        return;
      case StorePurchaseStatus.restored:
        _restored++;
      case StorePurchaseStatus.purchased:
        break;
    }
    if (!purchase.reportable) return;
    final outcome = await _report(purchase);
    if (outcome == null) return;
    if (outcome == StoreOutcome.unconfirmed) {
      // Left unfinished: the store sends it again.
      _onOutcome(outcome);
      return;
    }
    try {
      await store.finish(
        purchase,
        otherAccount: outcome == StoreOutcome.otherAccount,
      );
    } catch (_) {
      // Sent again later, and the server takes it again as it is.
    }
    _onOutcome(outcome);
  }

  /// The server's answer: accepted, refused for good, or [StoreOutcome.unconfirmed] for
  /// anything a retry may change. Null when signed out, which says enough.
  Future<StoreOutcome?> _report(StorePurchase purchase) async {
    try {
      await report(purchase.verificationData!);
      return StoreOutcome.accepted;
    } on UnauthorizedException {
      // Signed out, which stops the listener: reported at the next sign-in.
      return null;
    } on ApiException catch (error) {
      final definitive = error.statusCode == 400 || error.statusCode == 409;
      return (definitive ? _kDefinitive[error.body?['code']] : null) ??
          StoreOutcome.unconfirmed;
    } catch (_) {
      return StoreOutcome.unconfirmed;
    }
  }
}
