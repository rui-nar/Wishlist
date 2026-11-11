import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../lists/common.dart';
import 'admin_format.dart';
import 'admin_reauth.dart';
import 'admin_repository.dart';
import 'admin_users_screen.dart';

/// The furthest a grant may end, and its default (admin panel plan D8).
const _kMaxGrantYears = 10;
const _kDefaultGrantYears = 1;

/// [years] after [day], the 28th for a 29 February, as the server counts.
DateTime _yearsAfter(DateTime day, int years) {
  final date = DateTime(day.year + years, day.month, day.day);
  return date.month == day.month ? date : DateTime(day.year + years, day.month, 28);
}

/// `/admin/users/:id`: one account, its lists as counts (D6), its plan with
/// the grant and its end (D8), and its deletion (D9). Each change asks first.
class AdminUserScreen extends StatefulWidget {
  const AdminUserScreen({super.key, required this.userId});

  final String userId;

  @override
  State<AdminUserScreen> createState() => _AdminUserScreenState();
}

class _AdminUserScreenState extends State<AdminUserScreen> {
  late final _repository = AdminRepository.of(context);

  AdminUserDetail? _detail;
  Object? _error;

  /// A change is on its way: the buttons wait.
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final detail = await _repository.user(widget.userId);
      if (mounted) {
        setState(() {
          _detail = detail;
          _error = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  void _retry() {
    setState(() => _error = null);
    _load();
  }

  void _say(String message) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));

  /// Back to the users, which read the list again on the way.
  void _leave() => context.canPop() ? context.pop() : context.go(kAdminPath);

  Future<void> _grant(AdminUserDetail detail) async {
    final today = DateUtils.dateOnly(DateTime.now());
    final until = await showDialog<DateTime>(
      context: context,
      builder: (context) => _GrantDialog(
        email: detail.user.email,
        initial: detail.manualGrantEnd?.toLocal() ??
            _yearsAfter(today, _kDefaultGrantYears),
        first: today.add(const Duration(days: 1)),
        last: _yearsAfter(today, _kMaxGrantYears),
      ),
    );
    if (until == null || !mounted) return;
    final done = AppLocalizations.of(context).adminGrantDone(
      formatDay(context, until),
    );
    await _change(() => _repository.grantPremium(widget.userId, until), done);
  }

  Future<void> _endGrant(AdminUserDetail detail) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmAction(
      context,
      title: l10n.adminEndGrantTitle,
      body: l10n.adminEndGrantBody(detail.user.email),
      action: l10n.adminEndGrantConfirm,
    );
    if (!confirmed || !mounted) return;
    await _change(
      () => _repository.endPremium(widget.userId),
      l10n.adminEndGrantDone,
    );
  }

  /// Makes a plan change, then shows the account as the server returns it.
  Future<void> _change(
    Future<AdminUserDetail> Function() call,
    String done,
  ) async {
    final l10n = AppLocalizations.of(context);
    setState(() => _busy = true);
    try {
      final detail = await call();
      if (mounted) {
        setState(() => _detail = detail);
        _say(done);
      }
    } on ReauthRequiredException {
      if (mounted) await askToSignInAgain(context);
    } catch (error) {
      if (mounted) {
        switch (error) {
          // A 401 signs the admin out: the sign-in screen says enough.
          case UnauthorizedException():
            break;
          case _ when refusalCode(error) == kNoManualGrant:
            _say(l10n.adminNoGrant);
            await _load();
          case _ when refusalCode(error) == kPeriodEndOutOfRange:
            _say(l10n.adminDateOutOfRange);
          case _ when isNotFound(error):
            _say(l10n.adminUserGone);
            _leave();
          default:
            _say(failureMessage(l10n, error));
        }
      }
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _delete(AdminUserDetail detail) async {
    final l10n = AppLocalizations.of(context);
    final typed = await showDialog<String>(
      context: context,
      builder: (context) => _DeleteDialog(email: detail.user.email),
    );
    if (typed == null || !mounted) return;
    setState(() => _busy = true);
    try {
      await _repository.deleteUser(widget.userId, typed);
      if (mounted) {
        _say(l10n.adminDeleteDone);
        _leave();
      }
    } on ReauthRequiredException {
      if (mounted) await askToSignInAgain(context);
    } catch (error) {
      if (mounted) {
        final code = refusalCode(error);
        if (error is UnauthorizedException) {
          // Signed out: the sign-in screen says enough.
        } else if (code == kEmailMismatch) {
          _say(l10n.adminDeleteMismatch);
        } else if (code == kUseAccountScreen) {
          _say(l10n.adminOwnAccount);
        } else if (code == kBillingUnavailable ||
            (error is ApiException && error.statusCode == 502)) {
          _say(l10n.adminDeleteBilling);
        } else if (isNotFound(error)) {
          _say(l10n.adminUserGone);
          _leave();
        } else {
          _say(failureMessage(l10n, error));
        }
      }
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final detail = _detail;
    final me = context.select((AuthController auth) => auth.user?.id);
    final Widget body;
    if (detail == null && _error != null) {
      body = LoadFailure(
        error: _error,
        onRetry: _retry,
        notFound: l10n.adminUserGone,
        backLocation: kAdminPath,
        backLabel: l10n.adminBackToPanel,
      );
    } else if (detail == null) {
      body = const Center(child: CircularProgressIndicator());
    } else {
      // The admin's own account is deleted from their account screen (D9).
      final self = me == detail.user.id;
      body = ListView(
        padding: PageFrame.paddingOf(context, ContentWidths.reading),
        children: [
          _Section(child: _Identity(user: detail.user)),
          const SizedBox(height: Spacing.s12),
          _Section(
            title: l10n.adminPlanTitle,
            child: _Plan(
              detail: detail,
              busy: _busy,
              onGrant: () => _grant(detail),
              onEnd: () => _endGrant(detail),
            ),
          ),
          const SizedBox(height: Spacing.s12),
          _Section(
            title: l10n.adminListsTitle,
            child: _Lists(lists: detail.lists),
          ),
          const SizedBox(height: Spacing.s12),
          _Section(
            child: self
                ? Text(l10n.adminOwnAccount)
                : Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: _busy ? null : () => _delete(detail),
                      style: TextButton.styleFrom(
                        foregroundColor: Theme.of(context).colorScheme.error,
                      ),
                      icon: const Icon(Icons.delete_outline),
                      label: Text(l10n.adminDeleteAccount),
                    ),
                  ),
          ),
        ],
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(l10n.adminUserTitle)),
      body: PageFrame(child: SafeArea(child: body)),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({this.title, required this.child});

  final String? title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(Spacing.s16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (title case final title?) ...[
                Text(title, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: Spacing.s8),
              ],
              child,
            ],
          ),
        ),
      );
}

/// Who: the address, the name, since when, how they sign in, and the counts.
class _Identity extends StatelessWidget {
  const _Identity({required this.user});

  final AdminUserRow user;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final small = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SelectableText(user.email, style: theme.textTheme.titleMedium),
        if (user.displayName.isNotEmpty) Text(user.displayName),
        const SizedBox(height: Spacing.s4),
        Text(
          l10n.adminFiguresLine(
            l10n.adminCreated(formatDay(context, user.createdAt)),
            signInLine(l10n, user.signIn),
          ),
          style: small,
        ),
        Text(
          l10n.adminFiguresLine(
            l10n.adminListsOwned(user.listsOwned),
            photosLine(context, user.photos),
          ),
          style: small,
        ),
      ],
    );
  }
}

/// The plan, the grant and its end when there is one, and the two changes.
class _Plan extends StatelessWidget {
  const _Plan({
    required this.detail,
    required this.busy,
    required this.onGrant,
    required this.onEnd,
  });

  final AdminUserDetail detail;
  final bool busy;
  final VoidCallback onGrant;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final grantEnd = detail.manualGrantEnd;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(planLine(context, detail.user.plan)),
        // Already said by the plan line when the grant is what it shows.
        if (grantEnd != null && detail.user.plan.source != 'manual')
          Text(l10n.adminGrantedUntil(formatDay(context, grantEnd))),
        const SizedBox(height: Spacing.s12),
        Wrap(
          spacing: Spacing.s8,
          runSpacing: Spacing.s8,
          children: [
            FilledButton.tonal(
              onPressed: busy ? null : onGrant,
              child: Text(
                grantEnd == null ? l10n.adminGrantPremium : l10n.adminChangeGrant,
              ),
            ),
            if (grantEnd != null)
              OutlinedButton(
                onPressed: busy ? null : onEnd,
                child: Text(l10n.adminEndGrant),
              ),
          ],
        ),
      ],
    );
  }
}

/// The lists the account owns, as counts only (D6): a table when wide.
class _Lists extends StatelessWidget {
  const _Lists({required this.lists});

  final List<AdminList> lists;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    if (lists.isEmpty) return Text(l10n.adminNoLists);
    if (adminWide(context)) {
      return LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: constraints.maxWidth),
            child: DataTable(
              columns: [
                DataColumn(label: Text(l10n.adminColumnTitle)),
                DataColumn(label: Text(l10n.adminColumnCreated)),
                DataColumn(label: Text(l10n.adminColumnGifts), numeric: true),
                DataColumn(label: Text(l10n.adminColumnOwners), numeric: true),
              ],
              rows: [
                for (final list in lists)
                  DataRow(cells: [
                    DataCell(Text(list.title)),
                    DataCell(Text(formatDay(context, list.createdAt))),
                    DataCell(Text('${list.giftCount}')),
                    DataCell(Text('${list.ownerCount}')),
                  ]),
              ],
            ),
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final list in lists)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: Spacing.s4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(list.title, style: theme.textTheme.bodyLarge),
                Text(
                  l10n.adminListLine(
                    formatDay(context, list.createdAt),
                    l10n.listGiftCount(list.giftCount),
                    l10n.adminOwnerCount(list.ownerCount),
                  ),
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Premium until a day the admin picks, one year ahead unless changed; pops
/// the day to grant it.
class _GrantDialog extends StatefulWidget {
  const _GrantDialog({
    required this.email,
    required this.initial,
    required this.first,
    required this.last,
  });

  final String email;
  final DateTime initial;
  final DateTime first;
  final DateTime last;

  @override
  State<_GrantDialog> createState() => _GrantDialogState();
}

class _GrantDialogState extends State<_GrantDialog> {
  late DateTime _until = _clamp(DateUtils.dateOnly(widget.initial));

  DateTime _clamp(DateTime day) => day.isBefore(widget.first)
      ? widget.first
      : day.isAfter(widget.last)
          ? widget.last
          : day;

  Future<void> _pick() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _until,
      firstDate: widget.first,
      lastDate: widget.last,
    );
    if (picked != null && mounted) setState(() => _until = picked);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.adminGrantTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l10n.adminGrantBody(widget.email, formatDay(context, _until))),
          const SizedBox(height: Spacing.s8),
          TextButton.icon(
            onPressed: _pick,
            icon: const Icon(Icons.event),
            label: Text(l10n.adminGrantChangeDate),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.cancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(_until),
          child: Text(l10n.adminGrantConfirm),
        ),
      ],
    );
  }
}

/// Deleting asks for the account's address; the button waits until what is
/// typed matches it, ignoring case and surrounding spaces, as the server
/// does (D9). Pops what was typed.
class _DeleteDialog extends StatefulWidget {
  const _DeleteDialog({required this.email});

  final String email;

  @override
  State<_DeleteDialog> createState() => _DeleteDialogState();
}

class _DeleteDialogState extends State<_DeleteDialog> {
  final _typed = TextEditingController();

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  static String _normal(String email) => email.trim().toLowerCase();

  bool get _matches => _normal(_typed.text) == _normal(widget.email);

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.adminDeleteTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(l10n.adminDeleteBody(widget.email)),
          const SizedBox(height: Spacing.s16),
          TextField(
            controller: _typed,
            autofocus: true,
            autocorrect: false,
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(labelText: l10n.adminDeleteField),
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.cancel),
        ),
        TextButton(
          onPressed: _matches
              ? () => Navigator.of(context).pop(_typed.text.trim())
              : null,
          style: TextButton.styleFrom(
            foregroundColor: Theme.of(context).colorScheme.error,
          ),
          child: Text(l10n.adminDeleteConfirm),
        ),
      ],
    );
  }
}
