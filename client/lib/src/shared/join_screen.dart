import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../lists/common.dart';
import 'pending_join.dart';
import 'shared_repository.dart';

enum _Stage { loading, confirm, joining, invalid, failed }

/// `/join`: what the pending link would join, and a confirmation before
/// joining (LISTS_GIFTS_SHARING_PLAN D5, D6; the review envelope's "Joining
/// is explicit").
///
/// The token is the one [PendingJoin] captured at start: the router never
/// sees the link's fragment. An owner is taken to the list, a member to the
/// occasion; anyone else is asked, and joins with "Join". The token is
/// cleared as soon as it is used, whatever the outcome, and the next page
/// takes this one's place in the browser's history, so going back never
/// replays the link (review R3-1, R3-2). A token that no longer works, or no
/// token at all, says the link is no longer valid.
class JoinScreen extends StatefulWidget {
  const JoinScreen({super.key});

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> {
  late final _repository = SharedRepository.of(context);
  late final _pending = context.read<PendingJoin>();
  _Stage _stage = _Stage.loading;
  JoinPreview? _preview;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _loadPreview();
  }

  Future<void> _loadPreview() async {
    final token = _pending.token;
    if (token == null) {
      setState(() => _stage = _Stage.invalid);
      return;
    }
    setState(() => _stage = _Stage.loading);
    try {
      final preview = await _repository.preview(token);
      if (!mounted) return;
      switch (preview.role) {
        case JoinRole.owner:
          _leaveFor('/lists/${preview.listId}');
        case JoinRole.member:
          _leaveFor('/shared/${preview.occasionId}');
        case JoinRole.none:
          setState(() {
            _preview = preview;
            _stage = _Stage.confirm;
          });
      }
    } catch (error) {
      _failed(error);
    }
  }

  Future<void> _join() async {
    final token = _pending.token;
    if (token == null) return;
    setState(() => _stage = _Stage.joining);
    try {
      final outcome = await _repository.join(token);
      if (!mounted) return;
      switch (outcome) {
        case Joined(:final occasionId):
          _leaveFor('/shared/$occasionId');
        case OwnsList(:final listId):
          _leaveFor('/lists/$listId');
      }
    } catch (error) {
      _failed(error);
    }
  }

  void _cancel() => _leaveFor('/');

  /// A refused token is used up; anything else (the server unreachable, or
  /// its error) leaves it pending, to try again. A 401 signs the user out,
  /// and the sign-in screen brings them back here with it.
  void _failed(Object error) {
    if (!mounted) return;
    if (error is ApiException &&
        (error.statusCode == 404 || error.statusCode == 422)) {
      _pending.clear();
      setState(() => _stage = _Stage.invalid);
      return;
    }
    setState(() {
      _error = error;
      _stage = _Stage.failed;
    });
  }

  /// Clears the token and opens [location] in this page's place.
  void _leaveFor(String location) {
    _pending.clear();
    Router.neglect(context, () => context.go(location));
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.joinTitle)),
      body: PageFrame(
        child: SafeArea(
          child: switch (_stage) {
            _Stage.loading => const Center(child: CircularProgressIndicator()),
            _Stage.confirm || _Stage.joining => _Confirmation(
                preview: _preview!,
                joining: _stage == _Stage.joining,
                onJoin: _join,
                onCancel: _cancel,
              ),
            _Stage.invalid => _Message(
                message: l10n.joinLinkInvalid,
                button: l10n.backToMyLists,
                onPressed: () => _leaveFor('/'),
              ),
            _Stage.failed => _Message(
                message: failureMessage(l10n, _error),
                button: l10n.retry,
                onPressed: _preview == null ? _loadPreview : _join,
              ),
          },
        ),
      ),
    );
  }
}

/// What joining gives access to, and the buttons deciding.
class _Confirmation extends StatelessWidget {
  const _Confirmation({
    required this.preview,
    required this.joining,
    required this.onJoin,
    required this.onCancel,
  });

  final JoinPreview preview;
  final bool joining;
  final VoidCallback onJoin;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Align(
      alignment: Alignment.topCenter,
      child: SingleChildScrollView(
        padding: PageFrame.paddingOf(context, ContentWidths.reading),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(Spacing.s24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  l10n.joinInvited,
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: Spacing.s8),
                Text(preview.name, style: theme.textTheme.headlineMedium),
                const SizedBox(height: Spacing.s4),
                Text(
                  formatOccasionDate(context, preview.date),
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: Spacing.s16),
                _Fact(label: l10n.joinListLabel, value: preview.listTitle),
                _Fact(
                  label: l10n.joinRecipientLabel,
                  value: personName(l10n, preview.recipientName),
                ),
                _Fact(
                  label: l10n.joinOwnersLabel,
                  value: peopleNames(l10n, preview.ownerNames),
                ),
                const SizedBox(height: Spacing.s16),
                Text(l10n.joinExplanation, style: theme.textTheme.bodyMedium),
                const SizedBox(height: Spacing.s24),
                FilledButton(
                  onPressed: joining ? null : onJoin,
                  child: Text(l10n.join),
                ),
                const SizedBox(height: Spacing.s8),
                OutlinedButton(
                  onPressed: joining ? null : onCancel,
                  child: Text(l10n.cancel),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A label and its value, on one line when they fit.
class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.s4),
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '$label  ',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            TextSpan(text: value, style: theme.textTheme.bodyLarge),
          ],
        ),
      ),
    );
  }
}

/// Why there is nothing to join, or why it failed, and one button.
class _Message extends StatelessWidget {
  const _Message({
    required this.message,
    required this.button,
    required this.onPressed,
  });

  final String message;
  final String button;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: SingleChildScrollView(
        padding: PageFrame.paddingOf(context, ContentWidths.reading),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(Spacing.s16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ErrorLine(message),
                const SizedBox(height: Spacing.s16),
                OutlinedButton(onPressed: onPressed, child: Text(button)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
