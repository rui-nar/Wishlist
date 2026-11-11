/// Initialises Google sign-in on first use, from the sign-in screen
/// (ACCOUNTS_PLAN D11).
///
/// On the web, initialising is what loads Google's script
/// (accounts.google.com/gsi/client; the vendored google_sign_in_web in
/// client/third_party/ does not load it at plugin registration). Only the
/// sign-in screen calls [ensureGoogleSignInInitialized], so a visitor who
/// never reaches it, such as one following a share link, sends nothing to
/// Google.
library;

import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb, visibleForTesting;
import 'package:google_sign_in/google_sign_in.dart';

import '../config.dart';

Future<void>? _initialized;

String _iosClientId = kGoogleIosClientId;

bool get _isIos => !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

/// Whether Google sign-in can be offered with [webClientId], the web client
/// ID from `/api/config` (D6), null when the server has none. The iOS app
/// also needs its own client, from the build (IOS_APP_PLAN D3): built
/// without one, it offers Apple and email only.
bool canOfferGoogleSignIn(String? webClientId) =>
    webClientId != null && (!_isIos || _iosClientId.isNotEmpty);

/// Calls [GoogleSignIn.initialize] once per app run with [webClientId]: as
/// the client ID on the web, and as the server client ID on Android and iOS,
/// which then receive an ID token for the server. iOS also passes its own
/// client ID, without which the plugin ignores the server client ID. Later
/// calls return the same future. The plugin refuses a second initialize(),
/// so a failed one is not retried.
Future<void> ensureGoogleSignInInitialized(String webClientId) =>
    _initialized ??= GoogleSignIn.instance.initialize(
      clientId: kIsWeb ? webClientId : (_isIos ? _iosClientId : null),
      serverClientId: kIsWeb ? null : webClientId,
    );

/// Forgets the first call, so each test starts uninitialised, with the
/// build's iOS client ID.
@visibleForTesting
void resetGoogleSignInInitialized() {
  _initialized = null;
  _iosClientId = kGoogleIosClientId;
}

/// Stands in for the build's iOS client ID until the next reset.
@visibleForTesting
void setGoogleIosClientIdForTesting(String clientId) => _iosClientId = clientId;
