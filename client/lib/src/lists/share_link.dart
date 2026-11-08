/// An occasion's link, as the owner copies or shares it
/// (LISTS_GIFTS_SHARING_PLAN D5).
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

/// Where share links start: the server's `public_base_url` when it sets one,
/// otherwise the web client's own origin ([webOrigin]); null when there is
/// neither, on Android and iOS against a server without one, where a link
/// would have no host (review R1-7).
String? shareLinkBase({String? publicBaseUrl, String? webOrigin}) =>
    publicBaseUrl ?? webOrigin;

/// The web client's origin, null on Android and iOS.
String? get currentWebOrigin => kIsWeb ? Uri.base.origin : null;

/// `<base>/join#<token>`: the token is in the fragment, which browsers never
/// send to the server (D5).
String shareLink(String base, String token) => '$base/join#$token';

/// Puts [link] on the clipboard.
Future<void> copyLink(String link) =>
    Clipboard.setData(ClipboardData(text: link));

/// Opens the platform's share sheet for [link], with [subject] where the
/// target takes one. False when there is no share sheet (most desktop
/// browsers): the caller copies the link instead.
Future<bool> shareLinkWithSheet(String link, {required String subject}) async {
  try {
    await SharePlus.instance.share(ShareParams(
      uri: Uri.parse(link),
      subject: subject,
      // No mail draft in its place: copying the link is the fallback.
      mailToFallbackEnabled: false,
    ));
    return true;
  } catch (_) {
    return false;
  }
}
