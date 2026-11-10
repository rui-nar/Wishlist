import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../lists/price.dart';
import 'billing_repository.dart';
import 'legal_links.dart';

/// How many times the status is read again after Stripe's redirect, and how
/// far apart: the webhook can land after it (D18).
const kPaymentRereads = 5;
const kPaymentRereadDelay = Duration(seconds: 2);

/// The value of `?checkout=` when Stripe sends the browser back.
const _kSuccess = 'success';
const _kCancelled = 'cancelled';

/// Free or Premium, the date that matters, and the failed-payment line. The
/// account screen and the plan page say the same thing.
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

/// "Manage subscription": sends this tab to the Customer Portal (D14).
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
      if (!await openInThisTab(await _repository.openPortal())) fail();
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
/// (PREMIUM_PLAN D18). A real route, because Stripe sends the browser back to
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

  @override
  void initState() {
    super.initState();
    _waiting ? _waitForPayment() : _load();
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
      if (onTheWeb && status.canManage) ...[
        const SizedBox(height: Spacing.s12),
        ManageSubscriptionButton(onStale: _load),
      ],
      if (onTheWeb) ...[
        const SizedBox(height: Spacing.s8),
        LegalLinks(legal: status.legal),
      ],
      if (!onTheWeb && !status.isPremium) ...[
        const SizedBox(height: Spacing.s16),
        Text(l10n.planMobileUnavailable),
      ],
    ];
  }
}
