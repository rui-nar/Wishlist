import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import 'common.dart';
import 'lists_repository.dart';

/// An occasion's invitees, for the list's owner: who joined, each with a
/// button removing them, and the people removed, each with a button allowing
/// them again (LISTS_GIFTS_SHARING_PLAN D4, D8; `docs/NEEDS.md`, Access).
class OccasionMembersScreen extends StatefulWidget {
  const OccasionMembersScreen({
    super.key,
    required this.listId,
    required this.occasionId,
  });

  final String listId;
  final String occasionId;

  @override
  State<OccasionMembersScreen> createState() => _OccasionMembersScreenState();
}

class _OccasionMembersScreenState extends State<OccasionMembersScreen> {
  late final _repository = ListsRepository.of(context);
  late Future<List<Member>> _members;

  /// The person a call is running for; their button waits for it.
  String? _busy;

  @override
  void initState() {
    super.initState();
    _members = _repository.members(widget.occasionId);
  }

  void _reload() {
    setState(() {
      _members = _repository.members(widget.occasionId);
    });
  }

  Future<void> _remove(Member member) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmAction(
      context,
      title: l10n.removeInviteeTitle(personName(l10n, member.displayName)),
      body: l10n.removeInviteeBody(personName(l10n, member.displayName)),
      action: l10n.removeInvitee,
    );
    if (!confirmed) return;
    await _change(
      member,
      () => _repository.removeMember(widget.occasionId, member.userId),
    );
  }

  Future<void> _allowAgain(Member member) async {
    final l10n = AppLocalizations.of(context);
    final done = l10n.allowedAgain(personName(l10n, member.displayName));
    if (await _change(
      member,
      () => _repository.allowAgain(widget.occasionId, member.userId),
    )) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(done)));
      }
    }
  }

  /// Runs [call] for [member], then loads the people again; true when it
  /// succeeded.
  Future<bool> _change(Member member, Future<void> Function() call) async {
    if (!mounted) return false;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = member.userId);
    var done = false;
    try {
      await call();
      done = true;
    } catch (error) {
      messenger.showSnackBar(SnackBar(
        content: Text(
          isNotFound(error) ? l10n.occasionNotFound : l10n.saveFailed,
        ),
      ));
    }
    if (!mounted) return done;
    setState(() => _busy = null);
    _reload();
    return done;
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.inviteesTitle)),
      body: PageFrame(
        child: SafeArea(
          child: FutureBuilder<List<Member>>(
            future: _members,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return LoadFailure(
                  error: snapshot.error,
                  onRetry: _reload,
                  notFound: l10n.occasionNotFound,
                  backLocation: '/lists/${widget.listId}',
                  backLabel: l10n.backToList,
                );
              }
              final members = snapshot.data;
              if (members == null) {
                return const Center(child: CircularProgressIndicator());
              }
              return _content(context, members);
            },
          ),
        ),
      ),
    );
  }

  Widget _content(BuildContext context, List<Member> members) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final joined = [for (final m in members) if (!m.removed) m];
    final removed = [for (final m in members) if (m.removed) m];
    final note = theme.textTheme.bodyMedium?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return ListView(
      padding: PageFrame.paddingOf(context, ContentWidths.reading),
      children: [
        if (joined.isEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s24),
              child: Text(
                l10n.inviteesEmpty,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyLarge,
              ),
            ),
          )
        else
          _People(
            people: joined,
            busy: _busy,
            action: l10n.removeInvitee,
            destructive: true,
            onPressed: _remove,
          ),
        if (removed.isNotEmpty) ...[
          const SizedBox(height: Spacing.s32),
          Text(l10n.removedTitle, style: theme.textTheme.titleMedium),
          const SizedBox(height: Spacing.s4),
          Text(l10n.removedIntro, style: note),
          const SizedBox(height: Spacing.s12),
          _People(
            people: removed,
            busy: _busy,
            action: l10n.allowAgain,
            onPressed: _allowAgain,
          ),
        ],
      ],
    );
  }
}

/// People in a card, one row each, with one button.
class _People extends StatelessWidget {
  const _People({
    required this.people,
    required this.busy,
    required this.action,
    required this.onPressed,
    this.destructive = false,
  });

  final List<Member> people;
  final String? busy;
  final String action;
  final void Function(Member member) onPressed;

  /// The button in the error colour.
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Card(
      child: Column(
        children: [
          for (final (index, member) in people.indexed) ...[
            if (index > 0) const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: Spacing.s16,
                vertical: Spacing.s8,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      personName(l10n, member.displayName),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyLarge,
                    ),
                  ),
                  const SizedBox(width: Spacing.s8),
                  TextButton(
                    onPressed:
                        busy == null ? () => onPressed(member) : null,
                    style: destructive
                        ? TextButton.styleFrom(
                            foregroundColor: theme.colorScheme.error,
                          )
                        : null,
                    child: Text(action),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
