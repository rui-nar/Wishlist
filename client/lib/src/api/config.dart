/// The server's `GET /api/config` (ACCOUNTS_PLAN D6).
library;

import 'api_client.dart';

/// What the client learns from the server at run time, so one build serves
/// every environment.
class ClientConfig {
  const ClientConfig({required this.googleClientId, this.publicBaseUrl});

  /// Google's web client ID, also Android's server client ID; null when
  /// Google sign-in is not configured on this server.
  final String? googleClientId;

  /// The origin share links start with, without a trailing slash
  /// (LISTS_GIFTS_SHARING_PLAN D5); null when the server sets none, and the
  /// web client then uses its own origin.
  final String? publicBaseUrl;
}

/// Reads `/api/config`. Throws the [ApiClient] errors; an answer whose
/// fields are not strings or null throws [ApiUnreachableException].
Future<ClientConfig> fetchClientConfig(ApiClient api) async {
  final body = await api.getJson('/api/config');
  String? text(String field) {
    final value = body[field];
    if (value != null && value is! String) {
      throw const ApiUnreachableException();
    }
    return value == null || (value as String).isEmpty ? null : value;
  }

  return ClientConfig(
    googleClientId: text('google_client_id'),
    publicBaseUrl: text('public_base_url'),
  );
}
