import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../app_router.dart';
import '../auth/auth_controller.dart';
import 'admin_repository.dart';

/// A change refused with `reauth_required` (admin panel plan D3): the session
/// is too old to change anything. Says so, and on the admin's word signs them
/// out on purpose, to come back to the panel once signed in again.
Future<void> askToSignInAgain(BuildContext context) async {
  final router = GoRouter.of(context);
  final auth = context.read<AuthController>();
  final again = await showDialog<bool>(
    context: context,
    builder: (context) {
      final l10n = AppLocalizations.of(context);
      return AlertDialog(
        title: Text(l10n.adminReauthTitle),
        content: Text(l10n.adminReauthBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.cancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(l10n.adminReauthAction),
          ),
        ],
      );
    },
  );
  if (again != true) return;
  await auth.signOut();
  router.go(
    Uri(path: kSignInPath, queryParameters: {'from': kAdminPath}).toString(),
  );
}
