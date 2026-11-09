/// A gift as its occasion's givers see it: who reserved, bought or pledged,
/// and what the user may do about it (RESERVING_PLAN D13).
library;

import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/status_chip.dart';
import '../lists/common.dart';
import '../lists/price.dart';
import 'shared_repository.dart';

/// What a giver can do to a gift, each a button of the sheet.
enum GiftAction {
  reserve,
  startGroup,
  markBought,
  release,
  joinGroup,
  changeAmount,
  leaveGroup,
}

/// The actions [claim] allows the user. Once the occasion has [passed],
/// only marking bought the user's own expired claim, so a gift handed over
/// on the day is not freed for the next occasion (D8, review R3-1).
/// Changing an amount needs a gift with a price ([priced], D9).
List<GiftAction> giftActions(
  GiftClaim? claim, {
  required bool passed,
  required bool priced,
}) {
  if (passed) {
    return claim != null && claim.expired && claim.mine
        ? const [GiftAction.markBought]
        : const [];
  }
  if (claim == null) {
    return const [
      GiftAction.reserve,
      GiftAction.startGroup,
      GiftAction.markBought,
    ];
  }
  if (claim.bought || claim.state == ClaimState.taken) return const [];
  if (!claim.mine) {
    return claim.state == ClaimState.group
        ? const [GiftAction.joinGroup]
        : const [];
  }
  return claim.state == ClaimState.reserved
      ? const [GiftAction.markBought, GiftAction.release]
      : [
          if (priced) GiftAction.changeAmount,
          GiftAction.markBought,
          GiftAction.leaveGroup,
        ];
}

/// The rose chip of [claim]: who reserved or bought it, a group gift and
/// how many are in it, or taken.
StatusChip claimChip(AppLocalizations l10n, GiftClaim claim) {
  final first = claim.participants.firstOrNull;
  final (label, icon) = switch (claim.state) {
    ClaimState.taken => (l10n.claimTaken, Icons.do_not_disturb_on_outlined),
    ClaimState.group => claim.bought
        ? (l10n.claimGroupBought, Icons.check_circle_outline)
        : (l10n.claimGroup(claim.participants.length), Icons.groups_outlined),
    ClaimState.reserved => claim.bought
        ? (
            first == null
                ? l10n.claimBought
                : first.mine
                    ? l10n.claimBoughtByYou
                    : l10n.claimBoughtBy(personName(l10n, first.displayName)),
            Icons.check_circle_outline,
          )
        : (
            first == null
                ? l10n.claimReserved
                : first.mine
                    ? l10n.claimReservedByYou
                    : l10n.claimReservedBy(personName(l10n, first.displayName)),
            Icons.bookmark_outline,
          ),
  };
  return StatusChip(
    label: label,
    icon: icon,
    variant: StatusChipVariant.inviteeActivity,
  );
}

/// The gift's sheet: its title, price and details, its claim with the
/// pledges, and the buttons of [giftActions]. Returns the action tapped,
/// which the caller confirms and sends; null when closed.
Future<GiftAction?> showGiftSheet(
  BuildContext context, {
  required SharedGift gift,
  required GiftClaim? claim,
  required bool passed,
}) =>
    showModalBottomSheet<GiftAction>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) =>
          _GiftSheet(gift: gift, claim: claim, passed: passed),
    );

class _GiftSheet extends StatelessWidget {
  const _GiftSheet({
    required this.gift,
    required this.claim,
    required this.passed,
  });

  final SharedGift gift;
  final GiftClaim? claim;
  final bool passed;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final locale = Localizations.localeOf(context).toString();
    final claim = this.claim;
    final actions = giftActions(
      claim,
      passed: passed,
      priced: gift.priceCurrency != null,
    );
    final total = claim == null ? null : _total(claim, locale, l10n);
    final metadata = theme.textTheme.bodyLarge?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          Spacing.s24,
          0,
          Spacing.s24,
          Spacing.s24,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(gift.title, style: theme.textTheme.titleLarge),
            if (gift.priceAmount != null)
              Text(
                formatPrice(gift.priceAmount!, gift.priceCurrency!, locale),
                style: metadata,
              ),
            if (gift.description.isNotEmpty) ...[
              const SizedBox(height: Spacing.s12),
              Text(gift.description, style: theme.textTheme.bodyLarge),
            ],
            if (claim != null) ...[
              const SizedBox(height: Spacing.s16),
              Align(
                alignment: Alignment.centerLeft,
                child: claimChip(l10n, claim),
              ),
              if (claim.state == ClaimState.taken) ...[
                const SizedBox(height: Spacing.s8),
                Text(l10n.claimTakenExplanation, style: metadata),
              ],
              if (claim.state == ClaimState.group)
                for (final participant in claim.participants)
                  Padding(
                    padding: const EdgeInsets.only(top: Spacing.s8),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            participant.mine
                                ? l10n.claimYou
                                : personName(l10n, participant.displayName),
                            style: theme.textTheme.bodyLarge,
                          ),
                        ),
                        if (participant.pledgeAmount != null)
                          Text(
                            formatPrice(
                              participant.pledgeAmount!,
                              participant.pledgeCurrency!,
                              locale,
                            ),
                            style: theme.textTheme.bodyLarge,
                          ),
                      ],
                    ),
                  ),
              if (total != null) ...[
                const SizedBox(height: Spacing.s8),
                Text(total, style: metadata),
              ],
            ],
            if (passed) ...[
              const SizedBox(height: Spacing.s16),
              Text(
                actions.isEmpty
                    ? l10n.occasionPassed
                    : l10n.claimExpiredExplanation,
                style: metadata,
              ),
            ],
            if (actions.isNotEmpty) const SizedBox(height: Spacing.s16),
            for (final (index, action) in actions.indexed) ...[
              if (index > 0) const SizedBox(height: Spacing.s8),
              index == 0
                  ? FilledButton(
                      onPressed: () => Navigator.of(context).pop(action),
                      child: Text(_label(l10n, action)),
                    )
                  : OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(action),
                      child: Text(_label(l10n, action)),
                    ),
            ],
          ],
        ),
      ),
    );
  }

  /// The pledges added up against the price, when the gift has one and
  /// every pledge with an amount is in its currency (D9: an owner may have
  /// changed the currency since); pledges without an amount add nothing.
  String? _total(GiftClaim claim, String locale, AppLocalizations l10n) {
    final price = gift.priceAmount;
    final currency = gift.priceCurrency;
    final pledges = [
      for (final participant in claim.participants)
        if (participant.pledgeAmount != null) participant,
    ];
    if (claim.state != ClaimState.group ||
        price == null ||
        pledges.isEmpty ||
        pledges.any((pledge) => pledge.pledgeCurrency != currency)) {
      return null;
    }
    final cents = pledges.fold<int>(
      0,
      (sum, pledge) => sum + (num.parse(pledge.pledgeAmount!) * 100).round(),
    );
    return l10n.pledgeTotal(
      formatPrice((cents / 100).toStringAsFixed(2), currency!, locale),
      formatPrice(price, currency, locale),
    );
  }
}

String _label(AppLocalizations l10n, GiftAction action) => switch (action) {
      GiftAction.reserve => l10n.claimReserve,
      GiftAction.startGroup => l10n.claimStartGroup,
      GiftAction.markBought => l10n.claimMarkBought,
      GiftAction.release => l10n.claimRelease,
      GiftAction.joinGroup => l10n.claimJoinGroup,
      GiftAction.changeAmount => l10n.claimChangeAmount,
      GiftAction.leaveGroup => l10n.claimLeaveGroup,
    };

/// What the pledge dialog gives back: the amount, a decimal string in the
/// gift's currency, or null for none.
typedef Pledge = ({String? amount});

/// Asks for an optional amount in the gift's [currency] before starting or
/// joining a group gift, or changing one's amount ([action]); no field when
/// the gift has no price ([currency] null, D9). [current] fills the field.
/// Null when cancelled.
Future<Pledge?> showPledgeDialog(
  BuildContext context, {
  required GiftAction action,
  required String? currency,
  String? current,
}) =>
    showDialog<Pledge>(
      context: context,
      builder: (_) =>
          _PledgeDialog(action: action, currency: currency, current: current),
    );

class _PledgeDialog extends StatefulWidget {
  const _PledgeDialog({
    required this.action,
    required this.currency,
    required this.current,
  });

  final GiftAction action;
  final String? currency;
  final String? current;

  @override
  State<_PledgeDialog> createState() => _PledgeDialogState();
}

class _PledgeDialogState extends State<_PledgeDialog> {
  final _form = GlobalKey<FormState>();
  late final _amount = TextEditingController(text: widget.current ?? '');

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  /// The typed amount as the server takes it; null when empty. Zero is no
  /// pledge: the server takes amounts above it only.
  static String? _parse(String text) {
    final amount = parseAmount(text);
    return amount != null && num.parse(amount) > 0 ? amount : null;
  }

  void _submit() {
    if (!_form.currentState!.validate()) return;
    final text = _amount.text.trim();
    Navigator.of(context).pop<Pledge>(
      (amount: widget.currency == null || text.isEmpty ? null : _parse(text)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final currency = widget.currency;
    return AlertDialog(
      title: Text(_label(l10n, widget.action)),
      content: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              currency == null
                  ? l10n.pledgeExplanationNoPrice
                  : l10n.pledgeExplanation,
            ),
            if (currency != null) ...[
              const SizedBox(height: Spacing.s16),
              TextFormField(
                controller: _amount,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: l10n.pledgeAmountLabel,
                  suffixText: currency,
                  errorMaxLines: 2,
                ),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                validator: (value) {
                  final text = (value ?? '').trim();
                  return text.isEmpty || _parse(text) != null
                      ? null
                      : l10n.pledgeInvalid;
                },
                onFieldSubmitted: (_) => _submit(),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.cancel),
        ),
        TextButton(
          onPressed: _submit,
          child: Text(switch (widget.action) {
            GiftAction.startGroup => l10n.pledgeStart,
            GiftAction.joinGroup => l10n.pledgeJoin,
            _ => l10n.save,
          }),
        ),
      ],
    );
  }
}
