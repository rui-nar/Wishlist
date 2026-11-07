import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'server_version.dart';

/// Shows the app's version and the server's version and env, or why the
/// server's could not be read.
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
    return Scaffold(
      appBar: AppBar(title: const Text('Wishlist')),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('App ${widget.appVersion}'),
            const SizedBox(height: 8),
            FutureBuilder<ServerVersion>(
              future: _server,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return Text(
                    '${snapshot.error}',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  );
                }
                final server = snapshot.data;
                if (server == null) {
                  return const CircularProgressIndicator();
                }
                return Text('Server ${server.version} (${server.env})');
              },
            ),
          ],
        ),
      ),
    );
  }
}
