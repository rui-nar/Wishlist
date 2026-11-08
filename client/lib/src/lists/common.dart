/// Pieces the list and gift screens share.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../error_line.dart';
import 'lists_repository.dart';

/// Whether [error] says the list or gift is gone, or not the user's (D7).
bool isNotFound(Object? error) => error is ApiException && error.statusCode == 404;

/// Why a call failed, in the user's words. A 401 needs none: it signs the
/// user out and the guard shows the sign-in screen.
String failureMessage(AppLocalizations l10n, Object? error) =>
    error is ApiUnreachableException ? l10n.serverUnreachable : l10n.serverError;

/// Who a list is for, as the line under its title.
String recipientLine(
  AppLocalizations l10n,
  RecipientKind kind,
  String? recipientName,
) =>
    kind == RecipientKind.self ? l10n.listForMe : l10n.listForName(recipientName!);

/// A failed load, in a card: why, and a button to try again, or to go back
/// to My lists when what was asked for no longer exists ([notFound]).
class LoadFailure extends StatelessWidget {
  const LoadFailure({
    super.key,
    required this.error,
    required this.onRetry,
    this.notFound,
  });

  final Object? error;
  final VoidCallback onRetry;

  /// Shown instead of the server's error when [error] is a 404.
  final String? notFound;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final gone = notFound != null && isNotFound(error);
    return Align(
      alignment: Alignment.topCenter,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(Spacing.s16),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(Spacing.s16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ErrorLine(gone ? notFound! : failureMessage(l10n, error)),
                const SizedBox(height: Spacing.s16),
                gone
                    ? OutlinedButton(
                        onPressed: () => context.go('/'),
                        child: Text(l10n.backToMyLists),
                      )
                    : OutlinedButton(
                        onPressed: onRetry,
                        child: Text(l10n.retry),
                      ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Asks before deleting; true to delete.
Future<bool> confirmDelete(
  BuildContext context, {
  required String title,
  required String body,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) {
      final l10n = AppLocalizations.of(context);
      return AlertDialog(
        title: Text(title),
        content: Text(body),
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
            child: Text(l10n.delete),
          ),
        ],
      );
    },
  );
  return confirmed == true;
}

/// Tells the list screens when the user comes back to them; the router
/// registers it. Page routes only: closing a dialog or a menu is not coming
/// back.
final listsRouteObserver = RouteObserver<PageRoute<dynamic>>();

/// Loads the screen again when the page above it closes, whoever opened that
/// page and however it closes (back button, browser back, a form saving): a
/// list or a gift may have changed meanwhile.
mixin ReloadOnReturn<T extends StatefulWidget> on State<T>
    implements RouteAware {
  PageRoute<dynamic>? _route;

  void reload();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route is PageRoute && route != _route) {
      listsRouteObserver.unsubscribe(this);
      _route = route;
      listsRouteObserver.subscribe(this, route);
    }
  }

  @override
  void dispose() {
    listsRouteObserver.unsubscribe(this);
    super.dispose();
  }

  @override
  void didPopNext() => reload();

  @override
  void didPush() {}

  @override
  void didPop() {}

  @override
  void didPushNext() {}
}
