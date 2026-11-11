import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../lists/gift_links.dart';
import '../lists/price.dart';
import 'billing_repository.dart';
import 'legal_links.dart';
import 'store.dart';
import 'store_purchases.dart';

/// How many times the status is read again after Stripe's redirect, and how
/// far apart: the webhook can land after it (D18).
const kPaymentRereads = 5;
const kPaymentRereadDelay = Duration(seconds: 2);

/// The value of `?checkout=` when Stripe sends the browser back.
const _kSuccess = 'success';
const _kCancelled = 'cancelled';

/// Free or Premium, the date that matters, and the failed-payment line, or
/// the end of a Premium the admin granted. The account screen and the plan
/// page say the same thing.
class PlanSummary extends StatelessWidget {
  const PlanSummary({super.key, required this.status});

  final BillingStatus status;

  String _date(BuildContext context, DateTime date) => DateFormat.yMMMMd(
        Localizations.localeOf(context).toString(),
      ).format(date.toLocal());

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final endsAt = status.endsAt;
    // A renewal date beside "your last payment failed" would promise what the
    // line below it doubts.
    final renewsAt = status.isPastDue ? null : status.renewsAt;
    // Granted by the admin (admin panel plan D8): it ends, nothing renews.
    // The Manage button still follows `can_manage` alone (review R1-3).
    if (status.isManual && renewsAt != null) {
      return Text(
        l10n.planGrantedUntil(_date(context, renewsAt)),
        style: theme.textTheme.titleMedium,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          status.isPremium ? l10n.planPremium : l10n.planFree,
          style: theme.textTheme.titleMedium,
        ),
        if (endsAt != null || renewsAt != null) ...[
          const SizedBox(height: Spacing.s4),
          Text(
            endsAt != null
                ? l10n.planEnds(_date(context, endsAt))
                : l10n.planRenews(_date(context, renewsAt!)),
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        if (status.isPastDue) ...[
          const SizedBox(height: Spacing.s8),
          ErrorLine(l10n.planPastDue),
        ],
      ],
    );
  }
}

/// "Manage in the App Store" or "Manage in Google Play": the store's
/// subscriptions page, where the person changes or cancels a subscription
/// bought there (Apple IAP plan D8, Android release plan D8).
class StoreSubscriptionsButton extends StatelessWidget {
  const StoreSubscriptionsButton({super.key, required this.store});

  final StoreSource store;

  Future<void> _open(BuildContext context) async {
    final message = AppLocalizations.of(context).planActionFailed;
    final messenger = ScaffoldMessenger.of(context);
    final url = switch (store) {
      StoreSource.apple => kAppleSubscriptionsUrl,
      StoreSource.google => kGoogleSubscriptionsUrl,
    };
    if (!await openGiftLink(url)) {
      messenger.showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return OutlinedButton(
      onPressed: () => _open(context),
      child: Text(switch (store) {
        StoreSource.apple => l10n.planManageApple,
        StoreSource.google => l10n.planManageGoogle,
      }),
    );
  }
}

/// "Manage subscription": the Customer Portal (D14), in this tab, on the web
/// only: the phone apps link to no payment page outside their store.
class ManageSubscriptionButton extends StatefulWidget {
  const ManageSubscriptionButton({super.key, required this.onStale});

  /// The server says the status on screen is out of date.
  final VoidCallback onStale;

  @override
  State<ManageSubscriptionButton> createState() =>
      _ManageSubscriptionButtonState();
}

class _ManageSubscriptionButtonState extends State<ManageSubscriptionButton> {
  late final _repository = BillingRepository.of(context);
  bool _busy = false;

  Future<void> _manage() async {
    final message = AppLocalizations.of(context).planActionFailed;
    final messenger = ScaffoldMessenger.of(context);
    void fail() => messenger.showSnackBar(SnackBar(content: Text(message)));
    setState(() => _busy = true);
    try {
      final url = await _repository.openPortal();
      if (!await openInThisTab(url)) fail();
    } catch (error) {
      // A 401 signs the user out: the sign-in screen says enough.
      if (error is! UnauthorizedException) fail();
      if (mounted &&
          error is ApiException &&
          (error.statusCode == 404 || error.statusCode == 409)) {
        widget.onStale();
      }
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) => OutlinedButton(
        onPressed: _busy ? null : _manage,
        child: Text(AppLocalizations.of(context).planManage),
      );
}

/// `/account/plan`: the plan, what Premium adds and the way to buy it
/// (PREMIUM_PLAN D18): through Stripe on the web, through Apple in the iOS app
/// (Apple IAP plan D8), through Google Play in the Android app (Android
/// release plan D8). A real route, because Stripe sends the browser back to
/// it with `?checkout=` (kept through the sign-in guard by `from`).
class PlanScreen extends StatefulWidget {
  const PlanScreen({super.key, this.checkout});

  /// `?checkout=`: `success`, `cancelled`, or null when not coming from Stripe.
  final String? checkout;

  @override
  State<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends State<PlanScreen> {
  late final _repository = BillingRepository.of(context);

  BillingStatus? _status;

  /// The first read failed and nothing is known.
  bool _failed = false;

  /// Back from a payment, and still waiting for the webhook's effect.
  late bool _waiting = widget.checkout == _kSuccess;

  /// A checkout is being opened: no second one starts meanwhile.
  bool _buying = false;

  /// The phone app's purchases through its store (Apple IAP plan D3, Android
  /// release plan D6), the app's one listener: this page buys and restores
  /// through it, and says what they came to while it is open. Null
  /// elsewhere.
  late final StorePurchases? _purchases = context.read<StorePurchases?>();
  StreamSubscription<StoreOutcome>? _outcomes;

  /// Google Play sells here, not Apple: the words name it.
  bool get _google => _purchases?.store.source == StoreSource.google;

  /// The store's product, once the server sells it and the store priced it.
  StoreProduct? _product;
  bool _productAsked = false;
  bool _productFailed = false;

  /// A restore is on its way.
  bool _restoring = false;

  /// What the last purchase or restore came to, to say above the plan.
  StoreOutcome? _outcome;

  /// Restore found nothing to restore.
  bool _nothingRestored = false;

  @override
  void initState() {
    super.initState();
    _outcomes = _purchases?.outcomes.listen(_onOutcome);
    _waiting ? _waitForPayment() : _load();
  }

  @override
  void dispose() {
    _outcomes?.cancel();
    super.dispose();
  }

  /// Reads the plan. A failure when a plan is already on screen leaves it there.
  Future<void> _load() async {
    try {
      final status = await _repository.status();
      if (mounted) {
        setState(() {
          _status = status;
          _failed = false;
        });
        _loadProduct(status);
      }
    } catch (error) {
      if (!mounted || error is UnauthorizedException) return;
      if (_status == null) {
        setState(() => _failed = true);
      } else {
        _say(AppLocalizations.of(context).planActionFailed);
      }
    }
  }

  /// Reads the plan until it says Premium, at most [kPaymentRereads] times
  /// after the first read. A failed read is one less chance, nothing more.
  Future<void> _waitForPayment() async {
    for (var read = 0; read <= kPaymentRereads; read++) {
      if (read > 0) await Future<void>.delayed(kPaymentRereadDelay);
      if (!mounted) return;
      try {
        final status = await _repository.status();
        if (!mounted) return;
        setState(() => _status = status);
        if (status.isPremium) break;
      } on UnauthorizedException {
        return;
      } catch (_) {
        continue;
      }
    }
    if (mounted) setState(() => _waiting = false);
  }

  void _say(String message) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));

  Future<void> _buy() async {
    final l10n = AppLocalizations.of(context);
    setState(() => _buying = true);
    try {
      final url = await _repository.startCheckout();
      if (!await openInThisTab(url) && mounted) _say(l10n.planActionFailed);
    } on ApiException catch (error) {
      if (mounted) await _onCheckoutRefused(error, l10n);
    } catch (error) {
      if (mounted && error is! UnauthorizedException) {
        _say(l10n.planActionFailed);
      }
    }
    if (mounted) setState(() => _buying = false);
  }

  /// 409 `already_premium`: the plan on screen is out of date, and reading
  /// it again is the whole answer. 404: no longer on sale, likewise, and the
  /// tap needs explaining.
  Future<void> _onCheckoutRefused(
    ApiException error,
    AppLocalizations l10n,
  ) async {
    if (error.statusCode != 409) _say(l10n.planActionFailed);
    if (error.statusCode == 404 || error.statusCode == 409) await _load();
  }

  /// Asks the store for its price once the server sells through it: the app
  /// never shows the server's amount there (D1).
  Future<void> _loadProduct(BillingStatus status) async {
    final productId = status.storeProductId;
    final purchases = _purchases;
    if (productId == null || purchases == null || _productAsked) return;
    _productAsked = true;
    StoreProduct? product;
    try {
      product = await purchases.store.product(productId);
    } catch (_) {
      product = null;
    }
    if (mounted) {
      setState(() {
        _product = product;
        _productFailed = product == null;
      });
    }
  }

  void _onOutcome(StoreOutcome outcome) {
    if (!mounted) return;
    switch (outcome) {
      case StoreOutcome.cancelled:
        return;
      case StoreOutcome.failed:
        _say(AppLocalizations.of(context).planActionFailed);
        return;
      case StoreOutcome.accepted:
        _load();
      default:
        break;
    }
    setState(() => _outcome = outcome);
  }

  /// The store's purchase sheet, the purchase tied to this account (D2).
  Future<void> _buyFromStore(StoreProduct product) async {
    final accountId = context.read<AuthController>().user?.id;
    if (accountId == null) return;
    final failed = AppLocalizations.of(context).planActionFailed;
    setState(() {
      _buying = true;
      _outcome = null;
      _nothingRestored = false;
    });
    try {
      await _purchases!.buy(product, accountId);
    } catch (_) {
      // The store could not open its sheet: nothing was charged.
      if (mounted) _say(failed);
    }
    if (mounted) setState(() => _buying = false);
  }

  /// Required by Apple, and as useful on Android: finds what this store
  /// account bought earlier.
  Future<void> _restore() async {
    final failed = AppLocalizations.of(context).planActionFailed;
    setState(() {
      _restoring = true;
      _outcome = null;
      _nothingRestored = false;
    });
    try {
      final found = await _purchases!.restore();
      if (mounted && !found) setState(() => _nothingRestored = true);
    } catch (_) {
      if (mounted) _say(failed);
    }
    if (mounted) setState(() => _restoring = false);
  }

  void _back() => context.canPop() ? context.pop() : context.go('/account');

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final status = _status;
    final notice = _notice(l10n, status);
    return Scaffold(
      appBar: AppBar(
        // Stripe's redirect is a fresh navigation: nothing to pop (D18).
        leading: BackButton(onPressed: _back),
        title: Text(l10n.planSectionTitle),
      ),
      body: PageFrame(
        child: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.reading),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (notice != null) ...[
                        Text(notice),
                        const SizedBox(height: Spacing.s16),
                      ],
                      if (status != null) ..._plan(l10n, status),
                      if (_failed) ...[
                        ErrorLine(l10n.planLoadFailed),
                        const SizedBox(height: Spacing.s12),
                        OutlinedButton(
                          onPressed: _load,
                          child: Text(l10n.retry),
                        ),
                      ],
                      if (_waiting ||
                          (status == null &&
                              !_failed &&
                              widget.checkout != _kSuccess))
                        const Padding(
                          padding: EdgeInsets.only(top: Spacing.s16),
                          child: Center(child: CircularProgressIndicator()),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// What the return from Stripe has to say, once it is known.
  String? _notice(AppLocalizations l10n, BillingStatus? status) {
    final google = _google;
    if (_nothingRestored && status?.isPremium != true) {
      return google
          ? l10n.planNothingToRestoreGoogle
          : l10n.planNothingToRestore;
    }
    if (_outcome case final outcome?) {
      return switch (outcome) {
        // Once the plan read again says so.
        StoreOutcome.accepted =>
          status?.isPremium == true ? l10n.planThanks : null,
        StoreOutcome.pending => l10n.planPurchasePending,
        StoreOutcome.otherAccount => google
            ? l10n.planPurchaseOtherAccountGoogle
            : l10n.planPurchaseOtherAccount,
        StoreOutcome.sandboxRefused => l10n.planPurchaseSandbox,
        StoreOutcome.realRefused => l10n.planPurchaseRealRefused,
        StoreOutcome.notValid => google
            ? l10n.planPurchaseInvalidGoogle
            : l10n.planPurchaseInvalid,
        StoreOutcome.unconfirmed => google
            ? l10n.planPurchaseUnconfirmedGoogle
            : l10n.planPurchaseUnconfirmed,
        StoreOutcome.cancelled || StoreOutcome.failed => null,
      };
    }
    if (widget.checkout == _kCancelled) return l10n.planCheckoutCancelled;
    if (widget.checkout != _kSuccess || _waiting) return null;
    return status?.isPremium == true
        ? l10n.planThanks
        : l10n.planCheckoutProcessing;
  }

  List<Widget> _plan(AppLocalizations l10n, BillingStatus status) {
    final theme = Theme.of(context);
    final locale = Localizations.localeOf(context).toString();
    final offer = status.offer;
    final maxLists = status.maxLists;
    final maxGifts = status.maxGiftsPerList;
    // Straight after a payment the plan can still read free: buying again
    // would charge twice.
    final canBuy = onTheWeb &&
        !status.isPremium &&
        offer != null &&
        widget.checkout != _kSuccess;
    return [
      PlanSummary(status: status),
      const SizedBox(height: Spacing.s16),
      if (maxLists != null && maxGifts != null) ...[
        Text(l10n.planFreeLimits(maxLists, maxGifts)),
        const SizedBox(height: Spacing.s4),
      ],
      Text(l10n.planPremiumLimits),
      if (canBuy) ...[
        const SizedBox(height: Spacing.s16),
        Text(
          l10n.planPricePerYear(
            formatPrice(offer.amount, offer.currency, locale),
          ),
          style: theme.textTheme.titleMedium,
        ),
        const SizedBox(height: Spacing.s12),
        FilledButton(
          onPressed: _buying ? null : _buy,
          child: Text(l10n.planBuy),
        ),
      ],
      // No purchase while Premium is in force, from any source (D8).
      if (!status.isPremium &&
          status.storeProductId != null &&
          _purchases != null)
        ..._storePurchase(l10n, theme),
      if (status.offersAppleManagement) ...[
        const SizedBox(height: Spacing.s12),
        const StoreSubscriptionsButton(store: StoreSource.apple),
      ],
      if (status.offersGoogleManagement) ...[
        const SizedBox(height: Spacing.s12),
        const StoreSubscriptionsButton(store: StoreSource.google),
      ],
      if (status.offersStripePortal) ...[
        const SizedBox(height: Spacing.s12),
        ManageSubscriptionButton(onStale: _load),
      ],
      if (status.managedOnTheWebsite) ...[
        const SizedBox(height: Spacing.s12),
        Text(l10n.planManagedOnWebsite),
      ],
      if (onTheWeb || appStore != null) ...[
        const SizedBox(height: Spacing.s8),
        LegalLinks(legal: status.legal, store: appStore),
      ],
      if (!onTheWeb && !status.isPremium && !status.offeredHere) ...[
        const SizedBox(height: Spacing.s16),
        Text(l10n.planMobileUnavailable),
      ],
    ];
  }

  /// What a subscription's sale must say, by Apple's guideline 3.1.2 (D8)
  /// and Google Play's subscription policy alike: its name and length, the
  /// store's price, how it renews and is cancelled, then Restore. The terms
  /// and privacy links follow.
  List<Widget> _storePurchase(AppLocalizations l10n, ThemeData theme) {
    final product = _product;
    final busy = _buying || _restoring;
    final google = _google;
    return [
      const SizedBox(height: Spacing.s16),
      if (product != null) ...[
        Text(l10n.planAppleProduct, style: theme.textTheme.titleMedium),
        const SizedBox(height: Spacing.s4),
        Text(l10n.planApplePrice(product.price)),
        const SizedBox(height: Spacing.s8),
        Text(
          google ? l10n.planGoogleRenewal : l10n.planAppleRenewal,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: Spacing.s12),
        FilledButton(
          onPressed: busy ? null : () => _buyFromStore(product),
          child: Text(l10n.planSubscribe),
        ),
      ] else if (_productFailed)
        Text(
          google
              ? l10n.planGoogleStoreUnavailable
              : l10n.planStoreUnavailable,
        )
      else
        const Center(child: CircularProgressIndicator()),
      const SizedBox(height: Spacing.s8),
      TextButton(
        onPressed: busy ? null : _restore,
        child: Text(l10n.planRestore),
      ),
    ];
  }
}
