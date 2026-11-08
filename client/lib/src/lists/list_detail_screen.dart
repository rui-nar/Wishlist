import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../api/config.dart';
import '../design/tokens.dart';
import '../design/widgets/gift_card.dart';
import '../design/widgets/status_chip.dart';
import 'common.dart';
import 'gift_link_action.dart';
import 'lists_repository.dart';
import 'occasions_section.dart';
import 'price.dart';
import 'share_link.dart';

enum _ListAction { rename, delete }

/// A list the user owns: who it is for, its gifts, oldest first, each
/// opening its edit form, and its occasions with their links. The menu
/// renames or deletes the list.
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

  /// Where share links start, once `/api/config` answered: the server's
  /// public base URL, or the web client's origin (D5). Null until then.
  String? _linkBase;

  String get _location => '/lists/${widget.listId}';

  @override
  void initState() {
    super.initState();
    _list = _repository.list(widget.listId);
    fetchClientConfig(context.read<ApiClient>()).then(
      (config) => _setLinkBase(config.publicBaseUrl),
      // The web client's own origin still makes a working link.
      onError: (Object _) => _setLinkBase(null),
    );
  }

  void _setLinkBase(String? publicBaseUrl) {
    final base = shareLinkBase(
      publicBaseUrl: publicBaseUrl,
      webOrigin: currentWebOrigin,
    );
    if (mounted) setState(() => _linkBase = base);
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
            action: giftLinkAction(gift.links),
            onTap: () => context.push('$_location/gifts/${gift.id}/edit'),
          ),
        ],
        const SizedBox(height: Spacing.s32),
        OccasionsSection(
          listId: list.id,
          occasions: list.occasions,
          linkBase: _linkBase,
          onChanged: reload,
        ),
      ],
    );
  }
}
