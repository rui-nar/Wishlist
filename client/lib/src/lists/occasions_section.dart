import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import 'common.dart';
import 'lists_repository.dart';
import 'share_link.dart';

enum _OccasionAction {
  createLink,
  regenerateLink,
  revokeLink,
  members,
  gifts,
  edit,
  delete,
}

/// The smallest hit area of a control (DESIGN_SYSTEM_PLAN D6).
const double _minHitArea = 44;

/// A list's occasions, in its detail screen: creating one, and for each its
/// date, its invitee count, its link to copy or share, and its invitees. Its
/// menu creates, regenerates or revokes the link, renames and deletes it (LISTS_GIFTS_SHARING_PLAN D4, D5).
///
/// On a list for someone else, each occasion also opens its gifts and
/// reservations, where the owner gives like an invitee; on a list for the
/// owner, the recipient, nothing leads there (RESERVING_PLAN D4, D14).
class OccasionsSection extends StatelessWidget {
  const OccasionsSection({
    super.key,
    required this.listId,
    required this.recipientKind,
    required this.occasions,
    required this.linkBase,
    required this.onChanged,
  });

  final String listId;

  /// Who the list is for: the owner gives only on a list for someone else.
  final RecipientKind recipientKind;

  /// By date.
  final List<Occasion> occasions;

  /// Where links start ([shareLinkBase]); null when a link would have no
  /// host, and then there is nothing to copy or share.
  final String? linkBase;

  /// Called after an occasion changed, to load the list again.
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(l10n.occasionsTitle, style: theme.textTheme.headlineMedium),
        const SizedBox(height: Spacing.s4),
        Text(
          l10n.occasionsIntro,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: Spacing.s16),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: () => context.push('/lists/$listId/occasions/new'),
            icon: const Icon(Icons.event_outlined),
            label: Text(l10n.newOccasion),
          ),
        ),
        for (final occasion in occasions) ...[
          const SizedBox(height: Spacing.s12),
          _OccasionCard(
            occasion: occasion,
            gives: recipientKind == RecipientKind.other,
            link: occasion.joinToken == null || linkBase == null
                ? null
                : shareLink(linkBase!, occasion.joinToken!),
            onChanged: onChanged,
          ),
        ],
      ],
    );
  }
}

class _OccasionCard extends StatefulWidget {
  const _OccasionCard({
    required this.occasion,
    required this.gives,
    required this.link,
    required this.onChanged,
  });

  final Occasion occasion;

  /// The owner gives on it: the card opens its gifts and reservations.
  final bool gives;

  /// The link to copy or share; null when the occasion has none, or when a
  /// link would have no host.
  final String? link;
  final VoidCallback onChanged;

  @override
  State<_OccasionCard> createState() => _OccasionCardState();
}

class _OccasionCardState extends State<_OccasionCard> {
  late final _repository = ListsRepository.of(context);
  bool _busy = false;

  Occasion get _occasion => widget.occasion;

  String get _location =>
      '/lists/${_occasion.listId}/occasions/${_occasion.id}';

  Future<void> _onAction(_OccasionAction action) async {
    final l10n = AppLocalizations.of(context);
    switch (action) {
      case _OccasionAction.createLink:
        await _change(() => _repository.createLink(_occasion.id));
      case _OccasionAction.regenerateLink:
        if (await confirmAction(
          context,
          title: l10n.regenerateLinkTitle,
          body: l10n.regenerateLinkBody,
          action: l10n.regenerateLinkConfirm,
        )) {
          await _change(() => _repository.createLink(_occasion.id));
        }
      case _OccasionAction.revokeLink:
        if (await confirmAction(
          context,
          title: l10n.revokeLinkTitle,
          body: l10n.revokeLinkBody,
          action: l10n.revokeLinkConfirm,
        )) {
          await _change(() => _repository.revokeLink(_occasion.id));
        }
      case _OccasionAction.members:
        await context.push('$_location/members');
      case _OccasionAction.gifts:
        await context.push(_location);
      case _OccasionAction.edit:
        await context.push('$_location/edit');
      case _OccasionAction.delete:
        if (await confirmDelete(
          context,
          title: l10n.deleteOccasionTitle,
          body: l10n.deleteOccasionBody,
        )) {
          await _change(
            () => _repository.deleteOccasion(_occasion.id),
            goneIsDone: true,
          );
        }
    }
  }

  /// Runs [call], then has the list loaded again, whatever the outcome: a
  /// 404 means the occasion is gone, which the list then shows. [goneIsDone]
  /// when a 404 is what the user asked for (deleting).
  Future<void> _change(
    Future<void> Function() call, {
    bool goneIsDone = false,
  }) async {
    if (!mounted) return;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await call();
    } catch (error) {
      if (!(goneIsDone && isNotFound(error))) {
        messenger.showSnackBar(SnackBar(
          content: Text(
            isNotFound(error) ? l10n.occasionNotFound : l10n.saveFailed,
          ),
        ));
      }
    }
    if (!mounted) return;
    setState(() => _busy = false);
    widget.onChanged();
  }

  Future<void> _copy() async {
    final messenger = ScaffoldMessenger.of(context);
    final copied = AppLocalizations.of(context).linkCopied;
    await copyLink(widget.link!);
    messenger.showSnackBar(SnackBar(content: Text(copied)));
  }

  Future<void> _share() async {
    if (!await shareLinkWithSheet(widget.link!, subject: _occasion.name)) {
      // No share sheet here: the link is copied instead, and said so.
      if (mounted) await _copy();
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final hasLink = _occasion.joinToken != null;
    final metadata = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          Spacing.s16,
          Spacing.s12,
          Spacing.s4,
          Spacing.s16,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: Spacing.s4),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _occasion.name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.titleMedium,
                        ),
                        const SizedBox(height: Spacing.s4),
                        Text(
                          l10n.occasionLine(
                            formatOccasionDate(context, _occasion.date),
                            l10n.inviteeCount(_occasion.memberCount),
                          ),
                          style: metadata,
                        ),
                        Text(
                          hasLink ? l10n.linkActive : l10n.linkNone,
                          style: metadata,
                        ),
                      ],
                    ),
                  ),
                ),
                PopupMenuButton<_OccasionAction>(
                  enabled: !_busy,
                  style: IconButton.styleFrom(
                    minimumSize: const Size.square(_minHitArea),
                  ),
                  tooltip: l10n.occasionActions,
                  onSelected: _onAction,
                  itemBuilder: (context) => [
                    if (hasLink) ...[
                      PopupMenuItem(
                        value: _OccasionAction.regenerateLink,
                        child: Text(l10n.regenerateLink),
                      ),
                      PopupMenuItem(
                        value: _OccasionAction.revokeLink,
                        child: Text(l10n.revokeLink),
                      ),
                    ] else
                      PopupMenuItem(
                        value: _OccasionAction.createLink,
                        child: Text(l10n.createLink),
                      ),
                    PopupMenuItem(
                      value: _OccasionAction.edit,
                      child: Text(l10n.editOccasion),
                    ),
                    PopupMenuItem(
                      value: _OccasionAction.delete,
                      child: Text(l10n.deleteOccasion),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: Spacing.s12),
            Wrap(
              spacing: Spacing.s8,
              runSpacing: Spacing.s8,
              children: [
                if (!hasLink)
                  FilledButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _onAction(_OccasionAction.createLink),
                    icon: const Icon(Icons.add_link),
                    label: Text(l10n.createLink),
                  )
                else if (widget.link != null) ...[
                  FilledButton.icon(
                    onPressed: _busy ? null : _copy,
                    icon: const Icon(Icons.content_copy_outlined),
                    label: Text(l10n.copyLink),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _share,
                    icon: const Icon(Icons.share_outlined),
                    label: Text(l10n.shareLink),
                  ),
                ],
                OutlinedButton.icon(
                  onPressed: () => _onAction(_OccasionAction.members),
                  icon: const Icon(Icons.group_outlined),
                  label: Text(l10n.seeInvitees),
                ),
                if (widget.gives)
                  OutlinedButton.icon(
                    onPressed: () => _onAction(_OccasionAction.gifts),
                    icon: const Icon(Icons.redeem_outlined),
                    label: Text(l10n.occasionGiftsAndReservations),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
