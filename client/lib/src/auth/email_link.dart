/// What the steps of email sign-in share (sign-in plan D2, D8).
library;

import 'dart:async';

import '../api/api_client.dart';
import '../shared/pending_join.dart';

/// The page that asks for an address and mails a link.
const kEmailSignUpPath = '/email-sign-up';

/// The pages a mailed link opens: `<origin>/create-account#<token>` or
/// `<origin>/reset-password#<token>`.
const kCreateAccountPath = '/create-account';
const kResetPasswordPath = '/reset-password';

final _emailAddress = RegExp(r'^[^@\s\x00-\x1f\x7f-\x9f]+@[^@\s\x00-\x1f\x7f-\x9f]+$');

/// Whether [value] can be an address, by the server's rule (D4): exactly one
/// `@`, no whitespace or control character, at most 254 characters.
bool isEmailAddress(String value) {
  final trimmed = value.trim();
  return trimmed.length <= 254 && _emailAddress.hasMatch(trimmed);
}

/// Whether the server accepts [password] when one is chosen: 10 to 128
/// characters, counted as the server counts them, not in UTF-16 units (D11).
bool isAcceptablePassword(String password) {
  final length = password.runes.length;
  return length >= 10 && length <= 128;
}

/// The token a mailed link carries in [url]: the fragment of a link to
/// [kCreateAccountPath] or [kResetPasswordPath], or null for any other address.
String? emailLinkTokenFrom(Uri url) {
  if ((url.path != kCreateAccountPath && url.path != kResetPasswordPath) ||
      url.fragment.isEmpty) {
    return null;
  }
  return url.fragment;
}

/// The token of the mailed link the app was opened at, taken out of the
/// address bar at once, like an occasion link's (D8). Kept nowhere but in
/// memory: after a reload the person follows the link in the email again.
String? captureEmailLinkToken(Uri startUrl, JoinBrowser browser) {
  final token = emailLinkTokenFrom(startUrl);
  if (token == null) return null;
  browser.replaceLocation(
    Uri(
      path: startUrl.path,
      query: startUrl.hasQuery ? startUrl.query : null,
    ).toString(),
  );
  return token;
}

/// Asks the server to mail [email] a link (`POST /api/auth/email/start`).
/// Throws the [ApiClient] errors. The route answers 202 with no body, the
/// same whether the address has an account or not (D5).
Future<void> startEmailLink(
  ApiClient api, {
  required String email,
  required String language,
}) =>
    api.post(
      '/api/auth/email/start',
      body: {'email': email, 'language': language},
    );
