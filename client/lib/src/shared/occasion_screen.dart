import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../api/api_image.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../design/widgets/gift_card.dart';
import '../design/widgets/image_viewer.dart';
import '../design/widgets/privacy_banner.dart';
import '../design/widgets/status_chip.dart';
import '../lists/common.dart';
import '../lists/gift_link_action.dart';
import '../lists/price.dart';
import 'shared_repository.dart';

enum _OccasionAction { leave }

/// An occasion shared with the user, read-only: its list, who the gifts are
/// for, the privacy banner, and the gifts with their links and prices; a
/// gift with details shows them when tapped. The menu leaves the occasion. Nothing here edits anything
/// (LISTS_GIFTS_SHARING_PLAN D8, D11).
///
/// An owner who opens it is sent to the list, where they manage it.
class OccasionScreen extends StatefulWidget {
  const OccasionScreen({super.key, required this.occasionId});

  final String occasionId;

  @override
  State<OccasionScreen> createState() => _OccasionScreenState();
}

class _OccasionScreenState extends State<OccasionScreen>
    with ReloadOnReturn<OccasionScreen> {
  late final _repository = SharedRepository.of(context);
  late Future<OccasionView> _occasion;
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void reload() => setState(_load);

  void _load() {
    _occasion = _repository.occasion(widget.occasionId);
    _occasion.then((view) {
      if (view is OwnedOccasion && mounted) {
        // In place of this page, so going back does not come here again.
        Router.neglect(context, () => context.go('/lists/${view.listId}'));
      }
    }, onError: (_) {});
  }

  Future<void> _leave() async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmAction(
      context,
      title: l10n.leaveOccasionTitle,
      body: l10n.leaveOccasionBody,
      action: l10n.leaveOccasionConfirm,
    );
    if (!confirmed || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _leaving = true);
    try {
      await _repository.leave(widget.occasionId);
    } catch (error) {
      // No longer a member is what the user asked for.
      if (!isNotFound(error)) {
        messenger.showSnackBar(SnackBar(content: Text(l10n.leaveFailed)));
        if (mounted) setState(() => _leaving = false);
        return;
      }
    }
    if (!mounted) return;
    // Back to Shared with me, which the occasion's route is under: popping
    // has it load the occasions again.
    context.canPop() ? context.pop() : context.go('/shared');
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return FutureBuilder<OccasionView>(
      future: _occasion,
      builder: (context, snapshot) {
        final view = snapshot.data;
        final occasion = view is InviteeOccasion ? view : null;
        return Scaffold(
          appBar: AppBar(
            title: Text(occasion?.occasion.listTitle ?? ''),
            actions: [
              if (occasion != null)
                PopupMenuButton<_OccasionAction>(
                  enabled: !_leaving,
                  onSelected: (_) => _leave(),
                  itemBuilder: (context) => [
                    PopupMenuItem(
                      value: _OccasionAction.leave,
                      child: Text(l10n.leaveOccasion),
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
                      notFound: l10n.occasionNoLongerShared,
                      backLocation: '/shared',
                      backLabel: l10n.backToSharedWithMe,
                    )
                  : occasion == null
                      // Loading, or an owner on their way to the list.
                      ? const Center(child: CircularProgressIndicator())
                      : _content(context, occasion),
            ),
          ),
        );
      },
    );
  }

  Widget _content(BuildContext context, InviteeOccasion view) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final locale = Localizations.localeOf(context).toString();
    final occasion = view.occasion;
    final recipient = personName(l10n, occasion.recipientName);
    final metadata = theme.textTheme.bodyLarge?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return ListView(
      padding: PageFrame.paddingOf(context, ContentWidths.reading),
      children: [
        Text(occasion.name, style: theme.textTheme.headlineMedium),
        const SizedBox(height: Spacing.s4),
        Text(formatOccasionDate(context, occasion.date), style: metadata),
        Text(
          l10n.sharedForBy(recipient, peopleNames(l10n, occasion.ownerNames)),
          style: metadata,
        ),
        const SizedBox(height: Spacing.s16),
        PrivacyBanner(message: l10n.recipientDoesNotSee(recipient)),
        if (view.gifts.isEmpty) ...[
          const SizedBox(height: Spacing.s16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s24),
              child: Text(
                l10n.sharedGiftsEmpty,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyLarge,
              ),
            ),
          ),
        ],
        for (final gift in view.gifts) ...[
          const SizedBox(height: Spacing.s12),
          GiftCard(
            title: gift.title,
            image: gift.image == null
                ? null
                : ApiImage(context.read<ApiClient>(), gift.image!.thumbUrl),
            onImageTap: gift.image == null
                ? null
                : () => showImageViewer(
                      context,
                      ApiImage(context.read<ApiClient>(), gift.image!.url),
                      semanticLabel: gift.title,
                    ),
            metadata: gift.priceAmount == null
                ? null
                : formatPrice(gift.priceAmount!, gift.priceCurrency!, locale),
            chips: [
              if (gift.description.isNotEmpty)
                StatusChip(label: l10n.giftDetails, icon: Icons.notes),
              if (gift.links.isNotEmpty)
                StatusChip(
                  label: l10n.giftLinkCount(gift.links.length),
                  icon: Icons.link,
                ),
            ],
            action: giftLinkAction(gift.links),
            onTap: gift.description.isEmpty
                ? null
                : () => _showDetails(context, gift),
          ),
        ],
      ],
    );
  }

  /// The gift's title and details, which the card has no room for.
  void _showDetails(BuildContext context, SharedGift gift) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) {
        final theme = Theme.of(context);
        return SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(
              Spacing.s24,
              0,
              Spacing.s24,
              Spacing.s24,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(gift.title, style: theme.textTheme.titleLarge),
                const SizedBox(height: Spacing.s12),
                Text(gift.description, style: theme.textTheme.bodyLarge),
              ],
            ),
          ),
        );
      },
    );
  }
}
