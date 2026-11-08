import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';

/// Who is signed in, until the lists plan gives home its content
/// (ACCOUNTS_PLAN D10). The app bar's button opens the account screen.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final user = context.select((AuthController auth) => auth.user);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.appTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.account_circle_outlined),
            tooltip: l10n.accountTitle,
            onPressed: () => context.push('/account'),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(Spacing.s16),
          child: Align(
            alignment: Alignment.topCenter,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(Spacing.s16),
                child: SizedBox(
                  width: double.infinity,
                  // No user for the frame between signing out and the
                  // guard's redirect.
                  child: user == null
                      ? null
                      : Text(
                          l10n.homeSignedInAs(user.name),
                          style: Theme.of(context).textTheme.bodyLarge,
                        ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
