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

/// Why [fetchServerVersion] has no version to give.
enum ServerVersionFailure {
  /// The server could not be reached.
  unreachable,

  /// The server did not answer in time.
  timedOut,

  /// The server answered with a status other than 200.
  httpError,

  /// The server's answer is not the expected JSON.
  unexpectedAnswer,
}

/// Thrown by [fetchServerVersion]. Carries a [reason], not a message: the
/// screen shows the localised text for it.
class ServerVersionException implements Exception {
  const ServerVersionException(this.reason, {this.statusCode});

  final ServerVersionFailure reason;

  /// The HTTP status, for [ServerVersionFailure.httpError] only.
  final int? statusCode;

  @override
  String toString() => statusCode == null
      ? 'ServerVersionException: ${reason.name}'
      : 'ServerVersionException: ${reason.name} $statusCode';
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
    throw const ServerVersionException(ServerVersionFailure.unreachable);
  } on TimeoutException {
    throw const ServerVersionException(ServerVersionFailure.timedOut);
  }
  if (response.statusCode != 200) {
    throw ServerVersionException(
      ServerVersionFailure.httpError,
      statusCode: response.statusCode,
    );
  }
  try {
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return ServerVersion(
      version: body['version'] as String,
      env: body['env'] as String,
    );
  } catch (_) {
    throw const ServerVersionException(
      ServerVersionFailure.unexpectedAnswer,
    );
  }
}
