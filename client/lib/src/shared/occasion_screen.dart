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
import 'gift_sheet.dart';
import 'shared_repository.dart';

enum _OccasionAction { leave }

/// The occasion, what its givers did and their hidden gifts, loaded
/// together; no claims nor hidden gifts for someone sent elsewhere: an owner
/// on Shared with me, a recipient, or an invitee on an owner's location.
typedef _Page = ({
  OccasionView view,
  OccasionClaims? claims,
  List<HiddenGift>? hidden,
});

/// What the page shows above the gifts, from either view.
typedef _Header = ({
  String name,
  DateTime date,
  String line,
  String recipient,
  List<SharedGift> gifts,
});

/// An occasion shared with the user: its list, who the gifts are for, the
/// privacy banner, and the gifts with their links, prices and rose activity
/// chips. Tapping a gift opens its sheet, where the user reserves, joins a
/// group gift or marks it bought (RESERVING_PLAN D13). The menu leaves the
/// occasion. Nothing here edits the list (LISTS_GIFTS_SHARING_PLAN D8, D11).
///
/// An owner who opens it from Shared with me is sent to the list, where they
/// manage it; the occasion's activity is not asked for (RESERVING_PLAN D14).
///
/// Below the list's gifts, the givers' own hidden gifts, each with who added
/// it, and the way to add one (HIDDEN_GIFTS_PLAN D14).
///
/// Opened under the list ([listId], `/lists/:id/occasions/:occasionId`), it
/// is the giver mode of an owner of a list for someone else: the same gifts,
/// chips, sheet and actions, and no menu, since an owner has nothing to
/// leave. An owner of a list for themselves, the recipient, is sent to the
/// list without the activity being asked for (D4, D14); an invitee is sent
/// to the occasion under Shared with me. An occasion of another list is not
/// found there.
class OccasionScreen extends StatefulWidget {
  const OccasionScreen({super.key, required this.occasionId, this.listId});

  final String occasionId;

  /// The list the location names, in giver mode; null under Shared with me.
  final String? listId;

  @override
  State<OccasionScreen> createState() => _OccasionScreenState();
}

class _OccasionScreenState extends State<OccasionScreen>
    with ReloadOnReturn<OccasionScreen> {
  late final _repository = SharedRepository.of(context);
  late Future<_Page> _page;

  /// The claims loaded again after an action, newer than [_page]'s.
  OccasionClaims? _claims;
  bool _leaving = false;

  /// An action on a gift is on its way: a progress bar shows it, and no
  /// second one starts meanwhile (review R3-3).
  bool _acting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void reload() => setState(_load);

  void _load() {
    _claims = null;
    _page = _fetch();
  }

  Future<_Page> _fetch() async {
    final view = await _repository.occasion(widget.occasionId);
    final String? elsewhere = switch (view) {
      // Not an occasion of the list the location names: as if it were gone.
      OwnedOccasion(:final listId)
          when widget.listId != null && listId != widget.listId =>
        throw const ApiException(404),
      // A giver on their own list's occasion: here.
      OwnedOccasion(:final givesHere) when givesHere && widget.listId != null =>
        null,
      // Any other owner, the recipient first, manages it from the list.
      OwnedOccasion(:final listId) => '/lists/$listId',
      InviteeOccasion() when widget.listId != null =>
        '/shared/${Uri.encodeComponent(widget.occasionId)}',
      InviteeOccasion() => null,
    };
    if (elsewhere != null) {
      if (mounted) {
        // In place of this page, so going back does not come here again.
        Router.neglect(context, () => context.go(elsewhere));
      }
      return (view: view, claims: null, hidden: null);
    }
    final claims = _repository.claims(widget.occasionId);
    final hidden = _repository.hiddenGifts(widget.occasionId);
    await Future.wait([claims, hidden]);
    return (view: view, claims: await claims, hidden: await hidden);
  }

  /// This page's location: under Shared with me, or under the list in giver
  /// mode.
  String get _location {
    final occasion = Uri.encodeComponent(widget.occasionId);
    final listId = widget.listId;
    return listId == null
        ? '/shared/$occasion'
        : '/lists/${Uri.encodeComponent(listId)}/occasions/$occasion';
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

  /// The gift's sheet, then the action chosen there; while one is on its
  /// way, a tap says to wait rather than doing nothing.
  Future<void> _openSheet(
    SharedGift gift,
    GiftClaim? claim,
    bool passed,
  ) async {
    if (_acting) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context).claimActionInFlight),
          ),
        );
      return;
    }
    final action = await showGiftSheet(
      context,
      gift: gift,
      claim: claim,
      passed: passed,
    );
    if (action != null && mounted) await _act(gift, claim, action);
  }

  /// Confirms [action] on [gift], or asks for the pledge, sends it, then
  /// loads the claims again, after a refusal too (D13: no optimistic state).
  /// Left meanwhile, the write's own failure is still said; nothing is
  /// loaded again (review R3-2).
  Future<void> _act(
    SharedGift gift,
    GiftClaim? claim,
    GiftAction action,
  ) async {
    final l10n = AppLocalizations.of(context);
    final occasionId = widget.occasionId;
    Future<bool> confirm(String title, String body, String button) =>
        confirmAction(context, title: title, body: body, action: button);
    final Future<void> Function() send;
    switch (action) {
      case GiftAction.reserve:
        send = () => _repository.reserve(occasionId, gift.id);
      case GiftAction.release:
        final confirmed = await confirm(
          l10n.releaseTitle,
          l10n.releaseBody,
          l10n.claimRelease,
        );
        if (!confirmed) return;
        send = () => _repository.release(occasionId, gift.id);
      case GiftAction.markBought:
        final confirmed = await confirm(
          l10n.markBoughtTitle,
          l10n.markBoughtBody,
          l10n.claimMarkBought,
        );
        if (!confirmed) return;
        send = () => _repository.markBought(occasionId, gift.id);
      case GiftAction.leaveGroup:
        final confirmed = await confirm(
          l10n.leaveGroupTitle,
          l10n.leaveGroupBody,
          l10n.leaveGroupConfirm,
        );
        if (!confirmed) return;
        send = () => _repository.leaveGroup(occasionId, gift.id);
      case GiftAction.startGroup ||
          GiftAction.joinGroup ||
          GiftAction.changeAmount:
        final mine = claim?.participants
            .where((participant) => participant.mine)
            .firstOrNull;
        final pledge = await showPledgeDialog(
          context,
          action: action,
          currency: gift.priceCurrency,
          current: mine?.pledgeAmount,
        );
        if (pledge == null) return;
        send = () => _repository.pledge(occasionId, gift.id, pledge.amount);
      case GiftAction.edit:
        // Reloads on the way back.
        await context.push(
          '$_location/hidden/${Uri.encodeComponent(gift.id)}/edit',
        );
        return;
      case GiftAction.delete:
        final confirmed = await confirmDelete(
          context,
          title: l10n.deleteGiftTitle,
          body: l10n.hiddenGiftDeleteBody,
        );
        if (!confirmed) return;
        send = () => _repository.deleteHiddenGift(occasionId, gift.id);
    }
    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    void say(String message) =>
        messenger.showSnackBar(SnackBar(content: Text(message)));
    setState(() => _acting = true);
    try {
      await send();
      if (mounted) {
        if (action == GiftAction.delete) {
          reload();
        } else {
          await _reloadClaims(l10n, say);
        }
      }
    } on ClaimConflict catch (conflict) {
      say(switch (conflict.code) {
        ClaimConflictCode.taken => l10n.claimTakenNow,
        ClaimConflictCode.bought => l10n.claimBoughtNow,
        ClaimConflictCode.passed => l10n.claimPassedNow,
      });
      if (mounted) await _reloadClaims(l10n, say);
    } on HiddenGiftRefused catch (refused) {
      say(hiddenGiftRefusalMessage(l10n, refused.refusal));
      if (mounted) reload();
    } catch (error) {
      if (error is ApiException &&
          (error.statusCode == 404 || error.statusCode == 422)) {
        // The gift was deleted or changed (its price removed), or the
        // occasion is no longer shared: the page, loaded again, shows which.
        say(l10n.claimGiftChanged);
        if (mounted) reload();
      } else {
        say(
          error is ApiUnreachableException
              ? l10n.claimNeedsConnection
              : failureMessage(l10n, error),
        );
      }
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  /// The claims, loaded again; a failure says so and keeps what is shown.
  /// [l10n] comes from before the write: no context is read after it.
  Future<void> _reloadClaims(
    AppLocalizations l10n,
    void Function(String) say,
  ) async {
    try {
      final claims = await _repository.claims(widget.occasionId);
      if (mounted) setState(() => _claims = claims);
    } catch (error) {
      if (!mounted) return;
      isNotFound(error) ? reload() : say(failureMessage(l10n, error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return FutureBuilder<_Page>(
      future: _page,
      builder: (context, snapshot) {
        final page = snapshot.data;
        final claims = page?.claims == null ? null : _claims ?? page!.claims;
        // Nothing of the occasion until its claims are in, nor for someone
        // on their way elsewhere.
        final view = claims == null ? null : page!.view;
        final listId = widget.listId;
        return Scaffold(
          appBar: AppBar(
            title: Text(switch (view) {
              InviteeOccasion(:final occasion) => occasion.listTitle,
              OwnedOccasion(:final listTitle) => listTitle,
              null => '',
            }),
            actions: [
              if (view is InviteeOccasion)
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
          body: Stack(
            fit: StackFit.expand,
            children: [
              PageFrame(
                child: SafeArea(
                  child: snapshot.hasError
                      ? listId == null
                          ? LoadFailure(
                              error: snapshot.error,
                              onRetry: reload,
                              notFound: l10n.occasionNoLongerShared,
                              backLocation: '/shared',
                              backLabel: l10n.backToSharedWithMe,
                            )
                          : LoadFailure(
                              error: snapshot.error,
                              onRetry: reload,
                              notFound: l10n.occasionNotFound,
                              backLocation: '/lists/$listId',
                              backLabel: l10n.backToList,
                            )
                      : view == null
                          // Loading, or on the way elsewhere.
                          ? const Center(child: CircularProgressIndicator())
                          : _content(
                              context,
                              _header(l10n, view),
                              claims!,
                              page!.hidden ?? const [],
                            ),
                ),
              ),
              // An action on its way, under the app bar (review R3-3).
              if (_acting)
                const Positioned(
                  top: 0,
                  left: 0,
                  right: 0,
                  child: LinearProgressIndicator(),
                ),
            ],
          ),
        );
      },
    );
  }

  /// An invitee reads who the gifts are for and who shared them; an owner
  /// giving, who their list is for.
  _Header _header(AppLocalizations l10n, OccasionView view) => switch (view) {
        InviteeOccasion(:final occasion, :final gifts) => (
            name: occasion.name,
            date: occasion.date,
            line: l10n.sharedForBy(
              personName(l10n, occasion.recipientName),
              peopleNames(l10n, occasion.ownerNames),
            ),
            recipient: personName(l10n, occasion.recipientName),
            gifts: gifts,
          ),
        OwnedOccasion() => (
            name: view.name,
            date: view.date,
            line: recipientLine(l10n, view.recipientKind, view.recipientName),
            recipient: personName(l10n, view.recipientName!),
            gifts: view.gifts,
          ),
      };

  Widget _content(
    BuildContext context,
    _Header header,
    OccasionClaims claims,
    List<HiddenGift> hidden,
  ) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final metadata = theme.textTheme.bodyLarge?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return ListView(
      padding: PageFrame.paddingOf(context, ContentWidths.reading),
      children: [
        Text(header.name, style: theme.textTheme.headlineMedium),
        const SizedBox(height: Spacing.s4),
        Text(formatOccasionDate(context, header.date), style: metadata),
        Text(header.line, style: metadata),
        const SizedBox(height: Spacing.s16),
        PrivacyBanner(message: l10n.recipientDoesNotSee(header.recipient)),
        if (header.gifts.isEmpty) ...[
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
        for (final gift in header.gifts) ...[
          const SizedBox(height: Spacing.s12),
          _card(context, gift, claims.gifts[gift.id], claims.passed),
        ],
        // Nothing to see or do in a section once passed and empty.
        if (hidden.isNotEmpty || !claims.passed) ...[
          const SizedBox(height: Spacing.s24),
          Text(l10n.hiddenGiftsTitle, style: theme.textTheme.headlineMedium),
          const SizedBox(height: Spacing.s4),
          Text(l10n.hiddenGiftsExplanation(header.recipient), style: metadata),
          for (final gift in hidden) ...[
            const SizedBox(height: Spacing.s12),
            _card(context, gift, claims.gifts[gift.id], claims.passed),
          ],
          if (!claims.passed) ...[
            const SizedBox(height: Spacing.s12),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: () => context.push('$_location/hidden/new'),
                icon: const Icon(Icons.add),
                label: Text(l10n.addHiddenGift),
              ),
            ),
          ],
        ],
      ],
    );
  }

  /// The gift's card: who added it, for a hidden gift, and its activity chip,
  /// in rose, first, when it has a claim. Tapping it opens the sheet.
  Widget _card(
    BuildContext context,
    SharedGift gift,
    GiftClaim? claim,
    bool passed,
  ) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context).toString();
    final author = gift is HiddenGift ? authorChip(l10n, gift) : null;
    return GiftCard(
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
        ?author,
        if (claim != null) claimChip(l10n, claim),
        if (gift.description.isNotEmpty)
          StatusChip(label: l10n.giftDetails, icon: Icons.notes),
        if (gift.links.isNotEmpty)
          StatusChip(
            label: l10n.giftLinkCount(gift.links.length),
            icon: Icons.link,
          ),
      ],
      action: giftLinkAction(gift.links),
      onTap: () => _openSheet(gift, claim, passed),
    );
  }
}
