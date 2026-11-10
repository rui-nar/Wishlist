/// Web: loads Apple's script for the sign-in popup (sign-in plan D16).
///
/// Added to the page only by the sign-in screen, and only when the server
/// offers Apple, so that no other visitor fetches it and index.html does not
/// depend on it. If it is blocked, nothing on the page breaks: the button
/// fails with the sign-in screen's message.
library;

import 'package:web/web.dart' as web;

const _src =
    'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js';

bool _added = false;

void loadAppleScript() {
  if (_added) return;
  _added = true;
  web.document.head?.appendChild(
    web.HTMLScriptElement()
      ..src = _src
      ..async = true,
  );
}
