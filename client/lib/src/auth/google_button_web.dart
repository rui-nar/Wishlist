/// Web: Google's own sign-in button, rendered by its script through the
/// vendored google_sign_in_web. A sign-in through it arrives on
/// `GoogleSignIn.instance.authenticationEvents`.
library;

import 'package:flutter/material.dart';
import 'package:google_sign_in_web/web_only.dart' as gsi_web;

// The height of Google's large button, which matches the themed buttons'.
const double _kGoogleButtonHeight = 44;

Widget buildGoogleSignInButton(BuildContext context) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return SizedBox(
    height: _kGoogleButtonHeight,
    child: gsi_web.renderButton(
      configuration: gsi_web.GSIButtonConfiguration(
        theme: dark
            ? gsi_web.GSIButtonTheme.filledBlack
            : gsi_web.GSIButtonTheme.outline,
        text: gsi_web.GSIButtonText.continueWith,
        size: gsi_web.GSIButtonSize.large,
        // Google's text in the app's language, not the browser's.
        locale: Localizations.localeOf(context).languageCode,
      ),
    ),
  );
}
