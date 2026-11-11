import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../admin/admin_repository.dart';
import '../api/api_client.dart';
import '../billing/billing_repository.dart';
import '../billing/legal_links.dart';
import '../billing/plan_screen.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../intro/intro_screen.dart';
import '../lists/gift_links.dart';
import 'auth_controller.dart';
import 'preferences_repository.dart';

/// The signed-in user's name and email, the email notifications switch
/// (COMMENTS_NOTIFICATIONS_PLAN D20), their plan when there is one to show
/// (PREMIUM_PLAN D18), the admin panel for the admin, the introduction, the
/// version screen, sign-out and account deletion (ACCOUNTS_PLAN D10). Signing
/// out or deleting ends the session; the router's guard then shows the sign-in
/// screen.
class AccountScreen extends StatefulWidget {
  const AccountScreen({super.key});

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen> {
  /// While signing out or deleting: the buttons are disabled.
  bool _busy = false;

  late final _preferences = PreferencesRepository.of(context);

  /// What the switch shows; null until read, and it stays off and disabled
  /// when the read fails.
  bool? _emailNotifications;

  /// A change of the switch is on its way: no second one starts meanwhile.
  bool _savingEmail = false;

  late final _billing = BillingRepository.of(context);

  /// The plan section's data; null until read, and when the read fails: the
  /// section is simply not there.
  BillingStatus? _billingStatus;

  @override
  void initState() {
    super.initState();
    _loadPreferences();
    _loadBilling();
  }

  Future<void> _loadBilling() async {
    try {
      final status = await _billing.status();
      if (mounted) setState(() => _billingStatus = status);
    } catch (_) {
      // Nobody came here for the plan: no error, and a 401 signs out anyway.
    }
  }

  /// The plan page, and the plan again on the way back: it may have changed.
  Future<void> _seePremium() async {
    await context.push(kPlanPath);
    if (mounted) await _loadBilling();
  }

  Future<void> _loadPreferences() async {
    try {
      final preferences = await _preferences.preferences();
      if (mounted) {
        setState(() => _emailNotifications = preferences.emailNotifications);
      }
    } catch (error) {
      if (mounted && error is! UnauthorizedException) {
        _say(AppLocalizations.of(context).emailNotificationsLoadFailed);
      }
    }
  }

  /// Shows [on] at once, and goes back if the server refuses it.
  Future<void> _setEmailNotifications(bool on) async {
    final l10n = AppLocalizations.of(context);
    setState(() {
      _emailNotifications = on;
      _savingEmail = true;
    });
    try {
      final preferences = await _preferences.setEmailNotifications(on);
      if (mounted) {
        setState(() => _emailNotifications = preferences.emailNotifications);
      }
    } catch (error) {
      if (mounted) {
        setState(() => _emailNotifications = !on);
        // A 401 signs the user out: the sign-in screen says enough.
        if (error is! UnauthorizedException) {
          _say(l10n.emailNotificationsSaveFailed);
        }
      }
    }
    if (mounted) setState(() => _savingEmail = false);
  }

  void _say(String message) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));

  Future<void> _signOut() async {
    setState(() => _busy = true);
    await context.read<AuthController>().signOut();
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _delete() async {
    final l10n = AppLocalizations.of(context);
    setState(() => _busy = true);
    // Read now, not when the screen opened: a subscription bought meanwhile
    // must be warned of (Apple IAP plan D9). Unknown when it cannot be read.
    bool? appleRenewing;
    try {
      appleRenewing = (await _billing.status()).appleRenewing;
    } catch (_) {
      appleRenewing = null;
    }
    if (!mounted) return;
    setState(() => _busy = false);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => _DeleteDialog(appleRenewing: appleRenewing),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<AuthController>().deleteAccount();
    } catch (_) {
      // Not deleted: the user is still signed in and can try again.
      messenger.showSnackBar(SnackBar(content: Text(l10n.deleteAccountFailed)));
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final user = context.select((AuthController auth) => auth.user);
    final isAdmin = context.select((AuthController auth) => auth.isAdmin);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.accountTitle)),
      body: PageFrame(
        child: SafeArea(
          child: SingleChildScrollView(
            padding: PageFrame.paddingOf(context, ContentWidths.reading),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(Spacing.s16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // No user for the frame between signing out and the
                    // guard's redirect.
                    if (user != null) ...[
                      Text(user.name, style: theme.textTheme.titleMedium),
                      const SizedBox(height: Spacing.s4),
                      Text(
                        user.email,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: Spacing.s12),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(l10n.emailNotifications),
                        subtitle: Text(l10n.emailNotificationsHint),
                        value: _emailNotifications ?? false,
                        onChanged: _emailNotifications == null ||
                                _savingEmail ||
                                _busy
                            ? null
                            : _setEmailNotifications,
                      ),
                      const SizedBox(height: Spacing.s12),
                      if (_billingStatus case final billing?
                          when !billing.nothingToShow) ...[
                        _PlanSection(
                          status: billing,
                          onSeePremium: _seePremium,
                          onStale: _loadBilling,
                        ),
                        const SizedBox(height: Spacing.s12),
                      ],
                    ],
                    // The admin's only (admin panel plan D10).
                    if (isAdmin) ...[
                      OutlinedButton.icon(
                        onPressed: () => context.push(kAdminPath),
                        icon: const Icon(Icons.admin_panel_settings_outlined),
                        label: Text(l10n.adminPanel),
                      ),
                      const SizedBox(height: Spacing.s12),
                    ],
                    OutlinedButton.icon(
                      onPressed: () => context.push(kIntroPath),
                      icon: const Icon(Icons.help_outline),
                      label: Text(l10n.howItWorks),
                    ),
                    const SizedBox(height: Spacing.s12),
                    OutlinedButton.icon(
                      onPressed: () => context.push('/about'),
                      icon: const Icon(Icons.info_outline),
                      label: Text(l10n.aboutApp),
                    ),
                    const SizedBox(height: Spacing.s12),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _signOut,
                      icon: const Icon(Icons.logout),
                      label: Text(l10n.signOut),
                    ),
                    const SizedBox(height: Spacing.s12),
                    TextButton.icon(
                      onPressed: _busy ? null : _delete,
                      style: TextButton.styleFrom(
                        foregroundColor: theme.colorScheme.error,
                      ),
                      icon: const Icon(Icons.delete_outline),
                      label: Text(l10n.deleteAccount),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// "Your plan": what it is, and the way to Premium or to manage it: through
/// Stripe on the web, through Apple in the iOS app (Apple IAP plan D8, review
/// R1-8). On Android, the plan and its limits only (PREMIUM_PLAN D18).
class _PlanSection extends StatelessWidget {
  const _PlanSection({
    required this.status,
    required this.onSeePremium,
    required this.onStale,
  });

  final BillingStatus status;
  final VoidCallback onSeePremium;
  final VoidCallback onStale;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final maxLists = status.maxLists;
    final maxGifts = status.maxGiftsPerList;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(l10n.planSectionTitle, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: Spacing.s8),
        PlanSummary(status: status),
        // The apps show the limits too (NEEDS), and link to no plan page.
        if (!onTheWeb && maxLists != null && maxGifts != null) ...[
          const SizedBox(height: Spacing.s8),
          Text(l10n.planFreeLimits(maxLists, maxGifts)),
        ],
        if (!status.isPremium && status.offeredHere) ...[
          const SizedBox(height: Spacing.s12),
          OutlinedButton(onPressed: onSeePremium, child: Text(l10n.planSee)),
        ],
        if (status.offersAppleManagement) ...[
          const SizedBox(height: Spacing.s12),
          const AppleSubscriptionsButton(),
        ],
        if (status.offersStripePortal) ...[
          const SizedBox(height: Spacing.s12),
          ManageSubscriptionButton(onStale: onStale),
        ],
        if (onTheWeb || onIos) ...[
          const SizedBox(height: Spacing.s8),
          LegalLinks(legal: status.legal, apple: onIos),
        ],
      ],
    );
  }
}

/// Asks before deleting; pops true to delete. Warns, on every platform, of an
/// Apple subscription the deletion does not stop, with the way to Apple's
/// page (Apple IAP plan D9).
class _DeleteDialog extends StatelessWidget {
  const _DeleteDialog({required this.appleRenewing});

  /// Null when the plan could not be read: the warning is then conditional.
  final bool? appleRenewing;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final warning = switch (appleRenewing) {
      true => l10n.deleteAccountAppleRenewing,
      null => l10n.deleteAccountAppleUnknown,
      false => null,
    };
    return AlertDialog(
      title: Text(l10n.deleteAccountTitle),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.deleteAccountBody),
            if (warning != null) ...[
              const SizedBox(height: Spacing.s12),
              Text(
                warning,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: Spacing.s4),
              const _AppleSubscriptionsLink(),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(l10n.cancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(
            foregroundColor: Theme.of(context).colorScheme.error,
          ),
          child: Text(l10n.deleteAccountConfirm),
        ),
      ],
    );
  }
}

/// Apple's subscriptions page, in the browser or the App Store.
class _AppleSubscriptionsLink extends StatelessWidget {
  const _AppleSubscriptionsLink();

  Future<void> _open(BuildContext context) async {
    final message = AppLocalizations.of(context).planActionFailed;
    final messenger = ScaffoldMessenger.of(context);
    if (!await openGiftLink(kAppleSubscriptionsUrl)) {
      messenger.showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) => TextButton.icon(
        onPressed: () => _open(context),
        icon: const Icon(Icons.open_in_new),
        label: Text(AppLocalizations.of(context).deleteAccountAppleLink),
      );
}
