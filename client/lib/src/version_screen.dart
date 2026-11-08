import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../l10n/app_localizations.dart';
import 'design/tokens.dart';
import 'design/widgets/page_frame.dart';
import 'error_line.dart';
import 'server_version.dart';

/// Shows the app's version and the server's version and env, or why the
/// server's could not be read, in a card under the themed app bar.
class VersionScreen extends StatefulWidget {
  const VersionScreen({
    super.key,
    required this.httpClient,
    required this.apiBaseUrl,
    required this.appVersion,
  });

  final http.Client httpClient;
  final String apiBaseUrl;
  final String appVersion;

  @override
  State<VersionScreen> createState() => _VersionScreenState();
}

class _VersionScreenState extends State<VersionScreen> {
  late final Future<ServerVersion> _server = fetchServerVersion(
    widget.httpClient,
    baseUrl: widget.apiBaseUrl,
  );

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final textTheme = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.appTitle)),
      body: PageFrame.centered(
        child: SafeArea(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    l10n.appVersion(widget.appVersion),
                    style: textTheme.bodyLarge,
                  ),
                  const SizedBox(height: Spacing.s8),
                  FutureBuilder<ServerVersion>(
                    future: _server,
                    builder: (context, snapshot) {
                      if (snapshot.hasError) {
                        return ErrorLine(
                          _failureText(l10n, snapshot.error!),
                        );
                      }
                      final server = snapshot.data;
                      if (server == null) {
                        return const Align(
                          alignment: Alignment.centerLeft,
                          child: CircularProgressIndicator(),
                        );
                      }
                      return Text(
                        l10n.serverVersion(server.version, server.env),
                        style: textTheme.bodyLarge,
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The localised text for why the server's version could not be read. An
/// error [fetchServerVersion] does not classify still means no version, shown
/// as the server being unreachable.
String _failureText(AppLocalizations l10n, Object error) {
  if (error is! ServerVersionException) return l10n.serverUnreachable;
  return switch (error.reason) {
    ServerVersionFailure.unreachable => l10n.serverUnreachable,
    ServerVersionFailure.timedOut => l10n.serverTimedOut,
    ServerVersionFailure.httpError => l10n.serverHttpError(error.statusCode!),
    ServerVersionFailure.unexpectedAnswer => l10n.serverUnexpectedAnswer,
  };
}
