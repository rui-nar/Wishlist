import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../api/api_image.dart';
import '../api/config.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../design/widgets/gift_card.dart';
import '../design/widgets/image_viewer.dart';
import '../design/widgets/status_chip.dart';
import 'common.dart';
import 'gift_link_action.dart';
import 'lists_repository.dart';
import 'occasions_section.dart';
import 'price.dart';
import 'share_link.dart';

enum _ListAction { rename, delete }

/// A list the user owns: who it is for, its gifts, oldest first, each
/// opening its edit form, the gifts revealed from its occasions (received,
/// keep, dismiss), its received gifts (put back, delete), and its occasions
/// with their links (HIDDEN_GIFTS_PLAN D13). The menu renames or deletes the
/// list.
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

  /// A received or revealed gift's action is running.
  bool _acting = false;

  /// The Received section is open; closed until the owner opens it, and
  /// kept across reloads.
  bool _receivedOpen = false;

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
          body: PageFrame(
            child: SafeArea(
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
          ),
        );
      },
    );
  }

  Widget _content(BuildContext context, ListDetail list) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return ListView(
      padding: PageFrame.paddingOf(context, ContentWidths.reading),
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
          _giftCard(
            context,
            gift,
            chips: [
              if (gift.links.isNotEmpty)
                StatusChip(
                  label: l10n.giftLinkCount(gift.links.length),
                  icon: Icons.link,
                ),
            ],
            onTap: () => context.push('$_location/gifts/${gift.id}/edit'),
          ),
        ],
        if (list.revealed.isNotEmpty) ...[
          const SizedBox(height: Spacing.s32),
          Text(l10n.revealedTitle, style: theme.textTheme.headlineMedium),
          for (final gift in list.revealed) ...[
            const SizedBox(height: Spacing.s12),
            _giftCard(
              context,
              gift,
              chips: _actions([
                (l10n.revealedReceived, () => _markReceived(gift)),
                (l10n.revealedKeep, () => _keep(gift)),
                (l10n.revealedDismiss, () => _dismiss(gift)),
              ]),
            ),
          ],
        ],
        if (list.received.isNotEmpty) ...[
          const SizedBox(height: Spacing.s24),
          ExpansionTile(
            key: const ValueKey('received-section'),
            title: Text(
              l10n.receivedTitle(list.received.length),
              style: theme.textTheme.titleLarge,
            ),
            initiallyExpanded: _receivedOpen,
            onExpansionChanged: (open) => _receivedOpen = open,
            tilePadding: EdgeInsets.zero,
            shape: const Border(),
            collapsedShape: const Border(),
            children: [
              for (final gift in list.received)
                Padding(
                  padding: const EdgeInsets.only(bottom: Spacing.s12),
                  child: _giftCard(
                    context,
                    gift,
                    chips: _actions([
                      (l10n.putBack, () => _putBack(gift)),
                      (l10n.delete, () => _deleteReceived(gift)),
                    ]),
                  ),
                ),
            ],
          ),
        ],
        const SizedBox(height: Spacing.s32),
        OccasionsSection(
          listId: list.id,
          recipientKind: list.recipientKind,
          occasions: list.occasions,
          linkBase: _linkBase,
          onChanged: reload,
        ),
      ],
    );
  }

  /// [gift]'s card: its image, price and links, with [chips].
  Widget _giftCard(
    BuildContext context,
    Gift gift, {
    required List<Widget> chips,
    VoidCallback? onTap,
  }) {
    final api = context.read<ApiClient>();
    final locale = Localizations.localeOf(context).toString();
    return GiftCard(
      title: gift.title,
      image: gift.image == null ? null : ApiImage(api, gift.image!.thumbUrl),
      onImageTap: gift.image == null
          ? null
          : () => showImageViewer(
                context,
                ApiImage(api, gift.image!.url),
                semanticLabel: gift.title,
              ),
      metadata: gift.priceAmount == null
          ? null
          : formatPrice(gift.priceAmount!, gift.priceCurrency!, locale),
      chips: chips,
      action: giftLinkAction(gift.links),
      onTap: onTap,
    );
  }

  /// The buttons of a received or revealed gift, under its title. Teal like
  /// any button: nothing on an owner's list is rose (DESIGN.md, Invitee
  /// colour).
  List<Widget> _actions(List<(String, Future<void> Function())> actions) => [
        for (final (label, onPressed) in actions)
          TextButton(
            onPressed: _acting ? null : onPressed,
            child: Text(label),
          ),
      ];

  Future<void> _markReceived(Gift gift) =>
      _act(() => _repository.markReceived(gift.id));

  Future<void> _keep(Gift gift) => _act(() => _repository.keep(gift.id));

  Future<void> _dismiss(Gift gift) async {
    final l10n = AppLocalizations.of(context);
    if (await confirmAction(
      context,
      title: l10n.dismissGiftTitle,
      body: l10n.dismissGiftBody,
      action: l10n.revealedDismiss,
    )) {
      await _act(() => _repository.deleteGift(gift.id), deleting: true);
    }
  }

  Future<void> _putBack(Gift gift) =>
      _act(() => _repository.putBack(gift.id));

  Future<void> _deleteReceived(Gift gift) async {
    final l10n = AppLocalizations.of(context);
    if (await confirmDelete(
      context,
      title: l10n.deleteGiftTitle,
      body: l10n.deleteReceivedBody,
    )) {
      await _act(() => _repository.deleteGift(gift.id), deleting: true);
    }
  }

  /// Runs [call], then loads the list again whatever the outcome: a gift
  /// that is gone (404), or not revealed any more, shows as it now is.
  /// [deleting] when a 404 is what the user asked for.
  Future<void> _act(
    Future<Object?> Function() call, {
    bool deleting = false,
  }) async {
    if (!mounted) return;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _acting = true);
    try {
      await call();
    } on NotRevealed {
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.putBackNotRevealed)),
      );
    } catch (error) {
      if (!(deleting && isNotFound(error))) {
        messenger.showSnackBar(SnackBar(
          content: Text(
            isNotFound(error)
                ? l10n.giftNotFound
                : deleting
                    ? l10n.deleteFailed
                    : l10n.saveFailed,
          ),
        ));
      }
    }
    if (!mounted) return;
    setState(() => _acting = false);
    reload();
  }
}
