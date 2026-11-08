import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../error_line.dart';
import 'auth_controller.dart';

/// Holds the app's screens back until the stored session is known, so the
/// router's guard decides once, with the answer (ACCOUNTS_PLAN D10).
///
/// While the session is restored it shows progress. When the server could
/// not confirm a stored session (unreachable, or an error other than 401), it
/// says so with a button to try again, keeping the session: an outage does
/// not sign anyone out.
class StartGate extends StatelessWidget {
  const StartGate({super.key, required this.child});

  /// The router's screens.
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final status = context.select((AuthController auth) => auth.status);
    return switch (status) {
      AuthStatus.restoring => const Scaffold(
          body: Center(child: CircularProgressIndicator()),
        ),
      AuthStatus.unavailable => const _Unavailable(),
      _ => child,
    };
  }
}

class _Unavailable extends StatelessWidget {
  const _Unavailable();

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(Spacing.s16),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(Spacing.s16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ErrorLine(l10n.serverUnreachable),
                    const SizedBox(height: Spacing.s16),
                    OutlinedButton(
                      onPressed: () => context.read<AuthController>().restore(),
                      child: Text(l10n.retry),
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
