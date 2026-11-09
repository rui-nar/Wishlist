/// A gift's comments and its follow toggle, for the givers of its occasion
/// (COMMENTS_NOTIFICATIONS_PLAN D2, D3, D20).
library;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../error_line.dart';
import '../lists/common.dart';
import 'shared_repository.dart';

/// The longest comment, in Unicode code points (D2).
const kCommentMaxLength = 2000;

/// [text] as it is counted and sent: line feeds only, since the server
/// refuses carriage returns (D2), and trimmed.
String commentText(String text) =>
    text.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();

/// When a comment was written, in the viewer's time and [locale]: today,
/// yesterday, or the date, with its year when not [now]'s.
String commentTimeLabel(
  AppLocalizations l10n,
  String locale,
  DateTime at,
  DateTime now,
) {
  final local = at.toLocal();
  final time = DateFormat.jm(locale).format(local);
  if (DateUtils.isSameDay(local, now)) return l10n.commentToday(time);
  if (DateUtils.isSameDay(local, DateTime(now.year, now.month, now.day - 1))) {
    return l10n.commentYesterday(time);
  }
  final date = local.year == now.year
      ? DateFormat.MMMd(locale)
      : DateFormat.yMMMd(locale);
  return l10n.commentOnDate(date.format(local), time);
}

/// What to say when a call of the thread failed; [write] for a change, as
/// opposed to loading it.
String commentFailureMessage(
  AppLocalizations l10n,
  Object? error, {
  required bool write,
}) {
  if (isNotFound(error)) {
    return write ? l10n.commentGoneNow : l10n.commentsUnavailable;
  }
  if (write && error is ApiException && error.statusCode == 422) {
    return l10n.commentRefused;
  }
  return write && error is ApiUnreachableException
      ? l10n.claimNeedsConnection
      : failureMessage(l10n, error);
}

/// One gift's thread as last loaded, shared by the sheet's header and its
/// comments. Loaded again after each write or error: no optimistic state
/// (D20, RESERVING_PLAN D13).
class GiftThreadController extends ChangeNotifier {
  GiftThreadController({
    required this.repository,
    required this.occasionId,
    required this.giftId,
    required this.onFailure,
  });

  final SharedRepository repository;
  final String occasionId;
  final String giftId;

  /// Told of every failure, after the thread closed too (review R3-2).
  final void Function(Object error, {required bool write}) onFailure;

  /// Null until loaded, and once the gift is gone.
  GiftThread? thread;

  /// Why there is no [thread]; null while it loads.
  Object? loadError;

  /// A write is on its way: no second one starts meanwhile.
  bool busy = false;

  bool _disposed = false;

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  /// Loads the thread; what is shown stays when that fails, unless the gift
  /// is gone. A failure is said when [report] is set.
  Future<void> load({bool report = true}) async {
    try {
      thread = await repository.thread(occasionId, giftId);
      loadError = null;
    } catch (error) {
      if (_disposed) return;
      if (isNotFound(error)) thread = null;
      if (thread == null) loadError = error;
      if (report) onFailure(error, write: false);
    }
    _changed();
  }

  /// Loads the thread again after it failed to load.
  void retry() {
    loadError = null;
    _changed();
    load();
  }

  /// Sends [call], then loads the thread again, saying only the first of the
  /// two failures. Left meanwhile, the write's own failure is still said;
  /// nothing is loaded again. True when the write went through.
  Future<bool> _write(Future<Object?> Function() call) async {
    if (busy) return false;
    busy = true;
    _changed();
    var written = true;
    try {
      await call();
    } catch (error) {
      written = false;
      onFailure(error, write: true);
    }
    if (!_disposed) await load(report: written);
    busy = false;
    _changed();
    return written;
  }

  Future<bool> post(String body) =>
      _write(() => repository.comment(occasionId, giftId, body));

  Future<bool> edit(String commentId, String body) => _write(
        () => repository.editComment(occasionId, giftId, commentId, body),
      );

  Future<bool> delete(String commentId) => _write(
        () => repository.deleteComment(occasionId, giftId, commentId),
      );

  /// Follows the gift, or stops; only once [thread] says which.
  Future<bool> toggleFollow() => _write(
        () => thread!.following
            ? repository.unfollow(occasionId, giftId)
            : repository.follow(occasionId, giftId),
      );
}

/// "Follow" or "Following", once the thread says which.
class GiftFollowToggle extends StatelessWidget {
  const GiftFollowToggle({super.key, required this.controller});

  final GiftThreadController controller;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final thread = controller.thread;
        if (thread == null) return const SizedBox.shrink();
        return Semantics(
          toggled: thread.following,
          child: TextButton.icon(
            onPressed: controller.busy ? null : controller.toggleFollow,
            icon: Icon(
              thread.following
                  ? Icons.notifications_active_outlined
                  : Icons.notifications_none,
            ),
            label: Text(thread.following ? l10n.giftFollowing : l10n.giftFollow),
          ),
        );
      },
    );
  }
}

/// "Comments": the thread, oldest first, Edit and Delete on the user's own,
/// and the field to write one. Not rose: rose stays for activity chips (D20).
class GiftThreadSection extends StatefulWidget {
  const GiftThreadSection({super.key, required this.controller});

  final GiftThreadController controller;

  @override
  State<GiftThreadSection> createState() => _GiftThreadSectionState();
}

class _GiftThreadSectionState extends State<GiftThreadSection> {
  final _compose = TextEditingController();
  final _edit = TextEditingController();

  /// The comment being edited, in place.
  String? _editing;

  GiftThreadController get _thread => widget.controller;

  @override
  void dispose() {
    _compose.dispose();
    _edit.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final sent = await _thread.post(commentText(_compose.text));
    if (sent && mounted) _compose.clear();
  }

  void _startEditing(Comment comment) {
    _edit.text = comment.body;
    setState(() => _editing = comment.id);
  }

  void _stopEditing() => setState(() => _editing = null);

  /// Saves the edit; unchanged, there is nothing to mark as edited.
  Future<void> _save(Comment comment) async {
    final text = commentText(_edit.text);
    if (text == comment.body) return _stopEditing();
    final saved = await _thread.edit(comment.id, text);
    if (saved && mounted) _stopEditing();
  }

  Future<void> _delete(Comment comment) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmDelete(
      context,
      title: l10n.commentDeleteTitle,
      body: l10n.commentDeleteBody,
    );
    if (confirmed) await _thread.delete(comment.id);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return ListenableBuilder(
      listenable: _thread,
      builder: (context, _) {
        final thread = _thread.thread;
        final error = _thread.loadError;
        final metadata = theme.textTheme.bodyLarge?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(l10n.commentsTitle, style: theme.textTheme.titleMedium),
            const SizedBox(height: Spacing.s8),
            if (thread != null) ...[
              if (thread.comments.isEmpty)
                Text(l10n.commentsEmpty, style: metadata),
              for (final comment in thread.comments)
                Padding(
                  padding: const EdgeInsets.only(bottom: Spacing.s12),
                  child: _comment(context, comment),
                ),
              const SizedBox(height: Spacing.s8),
              _CommentField(
                controller: _compose,
                readOnly: _thread.busy,
                actions: (valid) => [
                  TextButton(
                    onPressed: valid && !_thread.busy ? _send : null,
                    child: Text(l10n.commentSend),
                  ),
                ],
              ),
            ] else if (error == null)
              const Center(child: CircularProgressIndicator())
            else ...[
              ErrorLine(
                isNotFound(error)
                    ? l10n.commentsUnavailable
                    : l10n.commentsLoadFailed,
              ),
              if (!isNotFound(error))
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: _thread.retry,
                    child: Text(l10n.retry),
                  ),
                ),
            ],
          ],
        );
      },
    );
  }

  /// A comment: who wrote it and when, its text selectable, or the field
  /// when it is being edited.
  Widget _comment(BuildContext context, Comment comment) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final locale = Localizations.localeOf(context).toString();
    final author = comment.authorName;
    final when = commentTimeLabel(
      l10n,
      locale,
      comment.createdAt,
      DateTime.now(),
    );
    final busy = _thread.busy;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          comment.mine
              ? l10n.claimYou
              : author == null
                  ? l10n.commentDeletedUser
                  : personName(l10n, author),
          style: theme.textTheme.titleSmall,
        ),
        Text(
          comment.edited ? l10n.commentEdited(when) : when,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: Spacing.s4),
        if (comment.id == _editing)
          _CommentField(
            controller: _edit,
            readOnly: busy,
            autofocus: true,
            actions: (valid) => [
              TextButton(
                onPressed: busy ? null : _stopEditing,
                child: Text(l10n.cancel),
              ),
              TextButton(
                onPressed: valid && !busy ? () => _save(comment) : null,
                child: Text(l10n.save),
              ),
            ],
          )
        else ...[
          SelectableText(comment.body, style: theme.textTheme.bodyLarge),
          if (comment.mine)
            Row(
              children: [
                TextButton(
                  onPressed: busy ? null : () => _startEditing(comment),
                  child: Text(l10n.commentEdit),
                ),
                TextButton(
                  onPressed: busy ? null : () => _delete(comment),
                  style: TextButton.styleFrom(
                    foregroundColor: theme.colorScheme.error,
                  ),
                  child: Text(l10n.delete),
                ),
              ],
            ),
        ],
      ],
    );
  }
}

/// The field a comment is written or edited in: the counter of code points,
/// and what is past the limit is refused rather than cut (D2). [actions]
/// are told whether the text can be sent.
class _CommentField extends StatelessWidget {
  const _CommentField({
    required this.controller,
    required this.readOnly,
    required this.actions,
    this.autofocus = false,
  });

  final TextEditingController controller;
  final bool readOnly;
  final bool autofocus;
  final List<Widget> Function(bool valid) actions;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return ValueListenableBuilder<TextEditingValue>(
      valueListenable: controller,
      builder: (context, value, _) {
        final length = commentText(value.text).runes.length;
        final tooLong = length > kCommentMaxLength;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: controller,
              readOnly: readOnly,
              autofocus: autofocus,
              minLines: 1,
              maxLines: 5,
              keyboardType: TextInputType.multiline,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                hintText: l10n.commentHint,
                counterText: l10n.commentCounter(length, kCommentMaxLength),
                errorText:
                    tooLong ? l10n.commentTooLong(kCommentMaxLength) : null,
                errorMaxLines: 2,
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: actions(length > 0 && !tooLong),
            ),
          ],
        );
      },
    );
  }
}
