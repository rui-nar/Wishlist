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

import 'package:flutter/foundation.dart' show kIsWeb, visibleForTesting;
import 'package:google_sign_in/google_sign_in.dart';

Future<void>? _initialized;

/// Calls [GoogleSignIn.initialize] once per app run with [clientId], the web
/// client ID from `/api/config` (D6): as the client ID on the web, and as the
/// server client ID on Android, which then receives an ID token for the
/// server. Later calls return the same future. The plugin refuses a second
/// initialize(), so a failed one is not retried.
Future<void> ensureGoogleSignInInitialized(String clientId) =>
    _initialized ??= GoogleSignIn.instance.initialize(
      clientId: kIsWeb ? clientId : null,
      serverClientId: kIsWeb ? null : clientId,
    );

/// Forgets the first call, so each test starts uninitialised.
@visibleForTesting
void resetGoogleSignInInitialized() => _initialized = null;
