/// The join token of an occasion link, from the moment the app starts until
/// the join screen uses it (LISTS_GIFTS_SHARING_PLAN D5).
library;

import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

// Web: the browser's session storage and history. Android and iOS: memory,
// since a link reaches the running app there (app_links.dart) instead of
// loading it again.
import 'join_browser_stub.dart'
    if (dart.library.js_interop) 'join_browser_web.dart';

/// The path of an occasion link: `<origin>/join#<token>`.
const kJoinPath = '/join';

/// How long an occasion link waits for the mailed link that follows it
/// (sign-in plan D19): as long as that link works.
const kJoinHandoverLifetime = Duration(hours: 1);

const _kHandoverKey = 'shushgift.join_handover';

/// Where the pending token outlives a reload, and the address bar.
abstract class JoinBrowser {
  /// The browser's on the web, memory elsewhere.
  factory JoinBrowser.forPlatform() => platformJoinBrowser();

  /// The token kept by an earlier load of this tab, or null.
  String? read();

  void write(String token);

  void clear();

  /// Shows [location] (a path and query) in the address bar in place of the
  /// current address, without a new history entry.
  void replaceLocation(String location);
}

/// A [JoinBrowser] in memory: what Android and iOS use, and tests.
class MemoryJoinBrowser implements JoinBrowser {
  MemoryJoinBrowser([this.stored]);

  /// What [write] kept; survives a new [PendingJoin.capture], as session
  /// storage survives a reload.
  String? stored;

  /// Every [replaceLocation], in order.
  final replaced = <String>[];

  @override
  String? read() => stored;

  @override
  void write(String token) => stored = token;

  @override
  void clear() => stored = null;

  @override
  void replaceLocation(String location) => replaced.add(location);
}

/// The token an occasion link carries when the app starts at [startUrl]:
/// the fragment of `/join#<token>`, or null for any other address.
///
/// Browsers never send the fragment to the server, so the token is in no
/// access log; the path URL strategy never hands it to the router either, so
/// it is read here, from the live address, before the router exists.
String? joinTokenFrom(Uri startUrl) {
  if (startUrl.path != kJoinPath || startUrl.fragment.isEmpty) return null;
  return startUrl.fragment;
}

/// The token of the occasion link this tab was opened with, until it is
/// used.
///
/// Kept in memory and in the browser's session storage, so the sign-in that
/// opening a link may need, and a reload during it, keep it. Cleared by the
/// join screen as soon as it is used, whatever the outcome, so going back to
/// `/join` never replays it (review R3-2).
class PendingJoin {
  PendingJoin(this._browser, [this._token]);

  /// Captures the token from [startUrl], the address the app started at: a
  /// new link replaces any pending token and leaves the address bar as
  /// `/join`, without its fragment; any other address keeps what an earlier
  /// load of this tab left pending (a reload during sign-in).
  factory PendingJoin.capture(Uri startUrl, JoinBrowser browser) {
    final fresh = joinTokenFrom(startUrl);
    if (fresh == null) return PendingJoin(browser, browser.read());
    browser
      ..write(fresh)
      ..replaceLocation(
        Uri(
          path: startUrl.path,
          query: startUrl.hasQuery ? startUrl.query : null,
        ).toString(),
      );
    return PendingJoin(browser, fresh);
  }

  final JoinBrowser _browser;
  String? _token;

  /// The token waiting to be used, or null.
  String? get token => _token;

  /// Takes the token of [link], a link that opened the running app on
  /// Android or iOS (Shush Gift plan D7): as a new page load does on the web,
  /// it replaces any pending token. A link without one changes nothing.
  void receive(Uri link) {
    final fresh = joinTokenFrom(link);
    if (fresh == null) return;
    _token = fresh;
    _browser.write(fresh);
  }

  /// Forgets the token: it was used.
  void clear() {
    _token = null;
    _browser.clear();
  }

  /// Copies the pending token where the tab a mailed link opens can read it,
  /// for [kJoinHandoverLifetime] (sign-in plan D19): that tab cannot see this
  /// one's session storage. With nothing pending, an earlier copy is removed,
  /// so that this link cannot join someone else's occasion.
  Future<void> handOverForEmailLink({DateTime? now}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final token = _token;
      if (token == null) {
        await prefs.remove(_kHandoverKey);
        return;
      }
      final expires = (now ?? DateTime.now()).add(kJoinHandoverLifetime);
      await prefs.setString(
        _kHandoverKey,
        jsonEncode({
          'token': token,
          'expires_at': expires.millisecondsSinceEpoch,
        }),
      );
    } catch (_) {
      // Storage can be refused: the person opens the invitation again.
    }
  }

  /// Takes back what [handOverForEmailLink] left, once a mailed link has
  /// signed in. What this tab already has pending wins, being more recent.
  /// The copy is gone afterwards, used or not.
  Future<void> resumeAfterEmailLink({DateTime? now}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      // Another tab wrote it, after this one read its preferences.
      await prefs.reload();
      final stored = prefs.getString(_kHandoverKey);
      await prefs.remove(_kHandoverKey);
      if (stored == null || _token != null) return;
      final handover = jsonDecode(stored) as Map<String, dynamic>;
      final expires = DateTime.fromMillisecondsSinceEpoch(
        handover['expires_at'] as int,
      );
      if (!(now ?? DateTime.now()).isBefore(expires)) return;
      final token = handover['token'] as String;
      _token = token;
      _browser.write(token);
    } catch (_) {
      // Unreadable or refused: the same as none.
    }
  }
}
