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
/// its Stripe subscription apart from the grant and its end (D8), and its
/// deletion (D9). Each change asks first.
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
    final today = adminToday();
    final end = detail.user.manualGrantEnd;
    final until = await showDialog<DateTime>(
      context: context,
      builder: (context) => _GrantDialog(
        email: detail.user.email,
        // A grant whose day has passed is granted anew, a year ahead.
        initial: end != null && !grantExpired(end)
            ? end.toLocal()
            : _yearsAfter(today, _kDefaultGrantYears),
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
              user: detail.user,
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

/// Wide enough for the subscription and the grant side by side: each block
/// keeps room for its dates and the grant's buttons. Stacked below.
const _kBlocksSideBySide = 2 * 4 * Spacing.s64 + Spacing.s12;

/// The effective plan, then the Stripe subscription and the grant in blocks
/// of their own: neither hides the other, and the grant's changes are in its
/// block only.
class _Plan extends StatelessWidget {
  const _Plan({
    required this.user,
    required this.busy,
    required this.onGrant,
    required this.onEnd,
  });

  final AdminUserRow user;
  final bool busy;
  final VoidCallback onGrant;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final subscription = _Block(
      key: const ValueKey('admin-subscription'),
      title: l10n.adminSubscriptionTitle,
      child: _Subscription(subscription: user.subscription),
    );
    final grant = _Block(
      key: const ValueKey('admin-grant'),
      title: l10n.adminGrantBlockTitle,
      child: _Grant(
        end: user.manualGrantEnd,
        busy: busy,
        onGrant: onGrant,
        onEnd: onEnd,
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(planLine(context, user.plan)),
        const SizedBox(height: Spacing.s12),
        LayoutBuilder(
          builder: (context, constraints) =>
              constraints.maxWidth >= _kBlocksSideBySide
                  // As tall as each other, so they read as a pair.
                  ? IntrinsicHeight(
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Expanded(child: subscription),
                          const SizedBox(width: Spacing.s12),
                          Expanded(child: grant),
                        ],
                      ),
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        subscription,
                        const SizedBox(height: Spacing.s12),
                        grant,
                      ],
                    ),
        ),
      ],
    );
  }
}

/// A titled, outlined block inside the plan section.
class _Block extends StatelessWidget {
  const _Block({super.key, required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: theme.colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(Radii.md),
      ),
      child: Padding(
        padding: const EdgeInsets.all(Spacing.s12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: theme.textTheme.labelLarge),
            const SizedBox(height: Spacing.s8),
            child,
          ],
        ),
      ),
    );
  }
}

/// The Stripe subscription: its status, since when, when it renews or ends,
/// a failed payment Stripe is retrying, and where to look when Stripe was not
/// heard of.
class _Subscription extends StatelessWidget {
  const _Subscription({required this.subscription});

  final AdminSubscription? subscription;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final subscription = this.subscription;
    if (subscription == null) return Text(l10n.adminNoSubscription);
    final small = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    final started = subscription.startedAt;
    final end = subscriptionEndLine(context, subscription);
    final warning = switch (subscription.status) {
      'past_due' => l10n.adminSubscriptionRetrying,
      // Its events were lost: Stripe may still be billing it (review R5-2).
      'no_news' => l10n.adminSubscriptionCheckStripe,
      _ => null,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(subscriptionStatus(context, subscription)),
        if (started != null)
          Text(
            l10n.adminSubscriptionStarted(formatDay(context, started)),
            style: small,
          ),
        if (end != null) Text(end, style: small),
        if (warning case final warning?) ...[
          const SizedBox(height: Spacing.s4),
          Text(
            warning,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.error,
            ),
          ),
        ],
      ],
    );
  }
}

/// The Premium granted here: until when, and its changes. Once its day has
/// passed it grants nothing, so it is granted again rather than changed or
/// ended.
class _Grant extends StatelessWidget {
  const _Grant({
    required this.end,
    required this.busy,
    required this.onGrant,
    required this.onEnd,
  });

  final DateTime? end;
  final bool busy;
  final VoidCallback onGrant;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final end = this.end;
    final running = end != null && !grantExpired(end);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          end == null
              ? l10n.adminGrantBlockNone
              : running
                  ? l10n.adminGrantBlockUntil(formatDay(context, end))
                  : l10n.adminGrantBlockExpired(formatDay(context, end)),
        ),
        const SizedBox(height: Spacing.s12),
        Wrap(
          spacing: Spacing.s8,
          runSpacing: Spacing.s8,
          children: [
            FilledButton.tonal(
              onPressed: busy ? null : onGrant,
              child: Text(
                running ? l10n.adminChangeGrant : l10n.adminGrantPremium,
              ),
            ),
            if (running)
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
