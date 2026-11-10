import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import 'auth_controller.dart';
import 'preferences_repository.dart';

/// The signed-in user's name and email, the email notifications switch
/// (COMMENTS_NOTIFICATIONS_PLAN D20), the version screen, sign-out and
/// account deletion (ACCOUNTS_PLAN D10). Signing out or deleting ends the
/// session; the router's guard then shows the sign-in screen.
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

  @override
  void initState() {
    super.initState();
    _loadPreferences();
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
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => const _DeleteDialog(),
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
                    ],
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

/// Asks before deleting; pops true to delete.
class _DeleteDialog extends StatelessWidget {
  const _DeleteDialog();

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.deleteAccountTitle),
      content: Text(l10n.deleteAccountBody),
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
