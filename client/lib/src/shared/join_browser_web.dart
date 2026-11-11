/// Web: the tab's session storage and the browser's history.
library;

import 'dart:js_interop';

import 'package:flutter_web_plugins/url_strategy.dart';

import 'pending_join.dart';

const _kKey = 'shushgift.pending_join';

JoinBrowser platformJoinBrowser() => WebJoinBrowser();

@JS('sessionStorage')
external _Storage get _sessionStorage;

extension type _Storage(JSObject _) implements JSObject {
  external String? getItem(String key);
  external void setItem(String key, String value);
  external void removeItem(String key);
}

/// Session storage is the tab's own and ends with it, unlike local storage:
/// a link opened in one tab stays pending in that tab only.
class WebJoinBrowser implements JoinBrowser {
  // Storage can be refused (a browser's privacy settings): the token then
  // lives in memory only, and a reload during sign-in loses it.
  @override
  String? read() {
    try {
      return _sessionStorage.getItem(_kKey);
    } catch (_) {
      return null;
    }
  }

  @override
  void write(String token) {
    try {
      _sessionStorage.setItem(_kKey, token);
    } catch (_) {}
  }

  @override
  void clear() {
    try {
      _sessionStorage.removeItem(_kKey);
    } catch (_) {}
  }

  /// Through the app's URL strategy, set before this runs, so the address
  /// keeps the app's base path and the history entry keeps the state the
  /// engine gave it.
  @override
  void replaceLocation(String location) {
    final strategy = urlStrategy;
    if (strategy == null) return;
    strategy.replaceState(
      strategy.getState(),
      '',
      strategy.prepareExternalUrl(location),
    );
  }
}
