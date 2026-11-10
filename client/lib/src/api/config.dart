/// The server's `GET /api/config` (ACCOUNTS_PLAN D6).
library;

import 'api_client.dart';

/// What the client learns from the server at run time, so one build serves
/// every environment.
class ClientConfig {
  const ClientConfig({
    required this.googleClientId,
    this.publicBaseUrl,
    this.appleClientId,
    this.appleRedirectUri,
    this.emailSignIn = false,
  });

  /// Google's web client ID, also Android's server client ID; null when
  /// Google sign-in is not configured on this server.
  final String? googleClientId;

  /// The origin share links start with, without a trailing slash
  /// (LISTS_GIFTS_SHARING_PLAN D5); null when the server sets none, and the
  /// web client then uses its own origin.
  final String? publicBaseUrl;

  /// The Services ID that Apple sign-in presents; null when it is not
  /// configured on this server (sign-in plan D18).
  final String? appleClientId;

  /// Where Apple sends its answer; null without a public address.
  final String? appleRedirectUri;

  /// Whether the server can mail the links of email sign-in (D18).
  final bool emailSignIn;
}

/// Reads `/api/config`. Throws the [ApiClient] errors; an answer whose
/// fields are not of their type or null throws [ApiUnreachableException]. A
/// field that an older server does not send reads as not configured.
Future<ClientConfig> fetchClientConfig(ApiClient api) async {
  final body = await api.getJson('/api/config');
  String? text(String field) {
    final value = body[field];
    if (value != null && value is! String) {
      throw const ApiUnreachableException();
    }
    return value == null || (value as String).isEmpty ? null : value;
  }

  final emailSignIn = body['email_sign_in'];
  if (emailSignIn != null && emailSignIn is! bool) {
    throw const ApiUnreachableException();
  }

  return ClientConfig(
    googleClientId: text('google_client_id'),
    publicBaseUrl: text('public_base_url'),
    appleClientId: text('apple_client_id'),
    appleRedirectUri: text('apple_redirect_uri'),
    emailSignIn: emailSignIn == true,
  );
}
