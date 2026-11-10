/// Asks Apple who the user is, on the web and Android (sign-in plan D15, D16).
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';

/// What `POST /api/auth/apple` needs from Apple's answer.
class AppleAuthorisation {
  const AppleAuthorisation({
    required this.idToken,
    required this.nonce,
    this.name,
  });

  final String idToken;

  /// The raw nonce: Apple was given its hash, and the server compares.
  final String nonce;

  /// Sent by Apple at the first authorisation only.
  final String? name;
}

// Longest display name the server accepts, in characters (D13).
const _maxNameLength = 100;

// What the server refuses in a display name (`_UNPRINTABLE`, D13).
bool _isUnprintable(int c) =>
    c <= 0x1f ||
    (c >= 0x7f && c <= 0x9f) ||
    (c >= 0x2028 && c <= 0x202e) ||
    (c >= 0x2066 && c <= 0x2069);

// Apple's error codes for the user leaving the popup, or starting again:
// https://developer.apple.com/documentation/signinwithapplejs/signinerrori
const _webCancellations = [
  'popup_closed_by_user',
  'user_cancelled_authorize',
  'user_trigger_new_signin_flow',
];

/// Opens Apple's sign-in: a popup on the web, a custom tab on Android.
///
/// Returns null when the user cancelled, and throws for any other failure.
/// On the web, a popup opens only within the tap that asked for it: call this
/// directly from the tap, with nothing awaited first. On Android, the future
/// may never complete if the user closes the tab, so a caller must not wait
/// on it to allow another attempt.
Future<AppleAuthorisation?> authoriseWithApple({
  required String clientId,
  required String redirectUri,
}) async {
  final nonce = generateNonce();
  try {
    final credential = await SignInWithApple.getAppleIDCredential(
      scopes: const [
        AppleIDAuthorizationScopes.email,
        AppleIDAuthorizationScopes.fullName,
      ],
      webAuthenticationOptions: WebAuthenticationOptions(
        clientId: clientId,
        redirectUri: Uri.parse(redirectUri),
      ),
      // The package passes this on as it is, on every platform.
      nonce: sha256.convert(utf8.encode(nonce)).toString(),
    );
    final idToken = credential.identityToken;
    if (idToken == null || idToken.isEmpty) {
      throw const FormatException('no ID token');
    }
    return AppleAuthorisation(
      idToken: idToken,
      nonce: nonce,
      name: appleDisplayName(credential.givenName, credential.familyName),
    );
  } catch (error) {
    if (_isCancellation(error)) return null;
    rethrow;
  }
}

/// The name to send the server, or null when Apple gave none, or one the
/// server would refuse: that must not cost the user their sign-in, and the
/// server then falls back on the address (D15).
String? appleDisplayName(String? givenName, String? familyName) {
  final name = [givenName, familyName]
      .map((part) => part?.trim() ?? '')
      .where((part) => part.isNotEmpty)
      .join(' ');
  if (name.isEmpty ||
      name.runes.length > _maxNameLength ||
      name.runes.any(_isUnprintable)) {
    return null;
  }
  return name;
}

bool _isCancellation(Object error) => switch (error) {
      SignInWithAppleAuthorizationException(:final code) =>
        code == AuthorizationErrorCode.canceled,
      // The web plugin reports all of Apple's errors this way.
      SignInWithAppleCredentialsException(:final message) =>
        _webCancellations.any(message.contains),
      _ => false,
    };
