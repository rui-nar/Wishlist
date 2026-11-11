import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The paths Android's app-link intent filter claims (Shush Gift plan D7),
/// read from build.gradle.kts, which writes the filter: exactly those of the
/// server's assetlinks host (server/app/app_links.py), and none of the pages
/// that stay in the browser.
void main() {
  final gradle = File('android/app/build.gradle.kts').readAsStringSync();
  final claims = [
    for (final match in RegExp(r'<data android:(path\w*)="([^"]*)"')
        .allMatches(gradle))
      (match.group(1)!, match.group(2)!),
  ];

  bool claimed(String path) => claims.any(
        (claim) => switch (claim) {
          ('path', final exact) => path == exact,
          ('pathPrefix', final prefix) => path.startsWith(prefix),
          _ => throw StateError('unexpected claim $claim'),
        },
      );

  test('exactly the paths that open the app', () {
    expect(claims, [
      ('path', '/join'),
      ('pathPrefix', '/shared/'),
      ('path', '/create-account'),
      ('path', '/reset-password'),
      ('path', '/account'),
    ]);
    for (final path in [
      '/join',
      '/shared/o-1',
      '/create-account',
      '/reset-password',
      '/account',
    ]) {
      expect(claimed(path), isTrue, reason: path);
    }
  });

  test('the pages that stay in the browser are not claimed', () {
    for (final path in [
      '/account/plan',
      '/unsubscribe',
      '/legal/terms',
      '/api/version',
      '/welcome',
      '/',
      '/sign-in',
      '/lists/l-1',
    ]) {
      expect(claimed(path), isFalse, reason: path);
    }
  });
}
