/// The server's `GET /api/config` (ACCOUNTS_PLAN D6).
library;

import 'api_client.dart';

/// What the client learns from the server at run time, so one build serves
/// every environment.
class ClientConfig {
  const ClientConfig({required this.googleClientId});

  /// Google's web client ID, also Android's server client ID; null when
  /// Google sign-in is not configured on this server.
  final String? googleClientId;
}

/// Reads `/api/config`. Throws the [ApiClient] errors; an answer without the
/// expected field throws [ApiUnreachableException].
Future<ClientConfig> fetchClientConfig(ApiClient api) async {
  final body = await api.getJson('/api/config');
  final id = body['google_client_id'];
  if (id != null && id is! String) throw const ApiUnreachableException();
  final clientId = id as String?;
  return ClientConfig(
    googleClientId: clientId == null || clientId.isEmpty ? null : clientId,
  );
}
