/// The server's `GET /api/version`.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// What `/api/version` reports: the image's version and its `APP_ENV`.
class ServerVersion {
  const ServerVersion({required this.version, required this.env});

  final String version;
  final String env;
}

/// Why [fetchServerVersion] has no version to give. [message] is shown as is.
class ServerVersionException implements Exception {
  const ServerVersionException(this.message);

  final String message;

  @override
  String toString() => message;
}

const _kTimeout = Duration(seconds: 10);

/// Calls `<baseUrl>/api/version`.
///
/// Throws [ServerVersionException] when the server cannot be reached, answers
/// with an error status, or answers something that is not the expected JSON.
Future<ServerVersion> fetchServerVersion(
  http.Client client, {
  required String baseUrl,
}) async {
  final http.Response response;
  try {
    response =
        await client.get(Uri.parse('$baseUrl/api/version')).timeout(_kTimeout);
  } on http.ClientException {
    throw const ServerVersionException('Server unreachable');
  } on TimeoutException {
    throw const ServerVersionException('Server unreachable (timed out)');
  }
  if (response.statusCode != 200) {
    throw ServerVersionException('Server answered HTTP ${response.statusCode}');
  }
  try {
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return ServerVersion(
      version: body['version'] as String,
      env: body['env'] as String,
    );
  } catch (_) {
    throw const ServerVersionException('Unexpected answer from the server');
  }
}
