// The browser side of capturing an occasion link: the tab's session storage
// and the history entry (LISTS_GIFTS_SHARING_PLAN D5). Runs in a browser
// only:
//   flutter test --platform chrome test/shared/web/join_browser_web_test.dart
@TestOn('browser')
library;

import 'dart:ui' as ui;
import 'dart:ui_web' as ui_web;

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:wishlist/src/shared/join_browser_web.dart';
import 'package:wishlist/src/shared/pending_join.dart';

/// Records what the browser's history is asked to do.
class _RecordingUrlStrategy implements UrlStrategy {
  final replaced = <(Object?, String)>[];

  @override
  ui.VoidCallback addPopStateListener(ui_web.PopStateListener fn) => () {};

  @override
  String getPath() => '/join';

  @override
  Object? getState() => const {'serialCount': 0};

  @override
  String prepareExternalUrl(String internalUrl) => '/base$internalUrl';

  @override
  void pushState(Object? state, String title, String url) {}

  @override
  void replaceState(Object? state, String title, String url) =>
      replaced.add((state, url));

  @override
  Future<void> go(int count) async {}
}

void main() {
  setUp(() => WebJoinBrowser().clear());
  tearDown(() => WebJoinBrowser().clear());

  test('the token survives a reload of the tab: session storage', () {
    WebJoinBrowser().write('abc');

    // A new start of the app reads what the previous one kept.
    expect(WebJoinBrowser().read(), 'abc');

    WebJoinBrowser().clear();
    expect(WebJoinBrowser().read(), isNull);
  });

  test('capture keeps the link, a reload finds it, using it clears it', () {
    final first = PendingJoin.capture(
      Uri.parse('http://localhost:5500/join#abc'),
      _NoHistory(),
    );
    expect(first.token, 'abc');

    final reloaded = PendingJoin.capture(
      Uri.parse('http://localhost:5500/sign-in?from=%2Fjoin'),
      WebJoinBrowser(),
    );
    expect(reloaded.token, 'abc');

    reloaded.clear();
    expect(
      PendingJoin.capture(
        Uri.parse('http://localhost:5500/join'),
        WebJoinBrowser(),
      ).token,
      isNull,
    );
  });

  test('the fragment leaves the address bar through the URL strategy', () {
    final strategy = _RecordingUrlStrategy();
    // As main() does with the path strategy; once per page, so not undone.
    setUrlStrategy(strategy);

    WebJoinBrowser().replaceLocation('/join');

    // Same history entry and state, the address without the fragment.
    expect(strategy.replaced, [(const {'serialCount': 0}, '/base/join')]);
  });
}

/// The web browser's storage, without touching the test page's history.
class _NoHistory extends WebJoinBrowser {
  @override
  void replaceLocation(String location) {}
}
