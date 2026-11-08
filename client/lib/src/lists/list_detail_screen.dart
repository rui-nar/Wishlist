import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/gift_card.dart';
import '../design/widgets/status_chip.dart';
import 'common.dart';
import 'gift_links.dart';
import 'lists_repository.dart';
import 'price.dart';

enum _ListAction { rename, delete }

/// The smallest hit area of a control (DESIGN_SYSTEM_PLAN D6).
const double _minHitArea = 44;

/// A list the user owns: who it is for and its gifts, oldest first, each
/// opening its edit form. The menu renames or deletes the list.
class ListDetailScreen extends StatefulWidget {
  const ListDetailScreen({super.key, required this.listId});

  final String listId;

  @override
  State<ListDetailScreen> createState() => _ListDetailScreenState();
}

class _ListDetailScreenState extends State<ListDetailScreen>
    with ReloadOnReturn<ListDetailScreen> {
  late final _repository = ListsRepository.of(context);
  late Future<ListDetail> _list;
  bool _deleting = false;

  String get _location => '/lists/${widget.listId}';

  @override
  void initState() {
    super.initState();
    _list = _repository.list(widget.listId);
  }

  @override
  void reload() {
    setState(() {
      _list = _repository.list(widget.listId);
    });
  }

  Future<void> _onAction(_ListAction action) async {
    switch (action) {
      case _ListAction.rename:
        await context.push('$_location/edit');
      case _ListAction.delete:
        await _delete();
    }
  }

  Future<void> _delete() async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmDelete(
      context,
      title: l10n.deleteListTitle,
      body: l10n.deleteListBody,
    );
    if (!confirmed || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _deleting = true);
    try {
      await _repository.deleteList(widget.listId);
    } catch (error) {
      // Already gone is what the user asked for.
      if (!isNotFound(error)) {
        messenger.showSnackBar(SnackBar(content: Text(l10n.deleteFailed)));
        if (mounted) setState(() => _deleting = false);
        return;
      }
    }
    // Back to My lists, which the list's route is under.
    if (mounted) context.pop();
  }

  Future<void> _openLink(String link) async {
    final messenger = ScaffoldMessenger.of(context);
    final failed = AppLocalizations.of(context).linkOpenFailed;
    if (!await openGiftLink(link)) {
      messenger.showSnackBar(SnackBar(content: Text(failed)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return FutureBuilder<ListDetail>(
      future: _list,
      builder: (context, snapshot) {
        final list = snapshot.data;
        return Scaffold(
          appBar: AppBar(
            title: Text(list?.title ?? ''),
            actions: [
              if (list != null)
                PopupMenuButton<_ListAction>(
                  enabled: !_deleting,
                  onSelected: _onAction,
                  itemBuilder: (context) => [
                    PopupMenuItem(
                      value: _ListAction.rename,
                      child: Text(l10n.renameList),
                    ),
                    PopupMenuItem(
                      value: _ListAction.delete,
                      child: Text(l10n.deleteList),
                    ),
                  ],
                ),
            ],
          ),
          body: SafeArea(
            child: snapshot.hasError
                ? LoadFailure(
                    error: snapshot.error,
                    onRetry: reload,
                    notFound: l10n.listNotFound,
                  )
                : list == null
                    ? const Center(child: CircularProgressIndicator())
                    : _content(context, list),
          ),
        );
      },
    );
  }

  Widget _content(BuildContext context, ListDetail list) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final locale = Localizations.localeOf(context).toString();
    return ListView(
      padding: const EdgeInsets.all(Spacing.s16),
      children: [
        Text(
          recipientLine(l10n, list.recipientKind, list.recipientName),
          style: theme.textTheme.bodyLarge?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: Spacing.s16),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: () => context.push('$_location/gifts/new'),
            icon: const Icon(Icons.add),
            label: Text(l10n.addGift),
          ),
        ),
        if (list.gifts.isEmpty) ...[
          const SizedBox(height: Spacing.s16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s24),
              child: Text(
                l10n.giftsEmpty,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyLarge,
              ),
            ),
          ),
        ],
        for (final gift in list.gifts) ...[
          const SizedBox(height: Spacing.s12),
          GiftCard(
            title: gift.title,
            metadata: gift.priceAmount == null
                ? null
                : formatPrice(gift.priceAmount!, gift.priceCurrency!, locale),
            chips: [
              if (gift.links.isNotEmpty)
                StatusChip(
                  label: l10n.giftLinkCount(gift.links.length),
                  icon: Icons.link,
                ),
            ],
            action: _linkAction(l10n, gift.links),
            onTap: () => context.push('$_location/gifts/${gift.id}/edit'),
          ),
        ],
      ],
    );
  }

  /// A button opening the gift's link; a menu of them when there are
  /// several. Each is itself at least 44 px, on every platform: desktop
  /// densities shrink icon buttons below that (DESIGN_SYSTEM_PLAN review
  /// R3-1).
  Widget? _linkAction(AppLocalizations l10n, List<String> links) {
    if (links.isEmpty) return null;
    final style = IconButton.styleFrom(
      minimumSize: const Size.square(_minHitArea),
    );
    if (links.length == 1) {
      return IconButton(
        style: style,
        icon: const Icon(Icons.open_in_new),
        tooltip: l10n.openLink,
        onPressed: () => _openLink(links.single),
      );
    }
    return PopupMenuButton<String>(
      style: style,
      icon: const Icon(Icons.open_in_new),
      tooltip: l10n.openLinks,
      onSelected: _openLink,
      itemBuilder: (context) => [
        for (final link in links)
          PopupMenuItem(
            value: link,
            child: Text(link, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
      ],
    );
  }
}
