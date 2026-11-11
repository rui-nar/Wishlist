import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The iOS app links' entitlement (Shush Gift plan D7), read from the
/// project's files: only a build that sets SHUSHGIFT_APP_LINK_HOST signs
/// with Associated Domains (ios-release.yml writes CODE_SIGN_ENTITLEMENTS),
/// and every other build signs exactly as before.
void main() {
  String read(String path) => File(path).readAsStringSync();

  final plain = read('ios/Runner/Runner.entitlements');
  final appLinks = read('ios/Runner/RunnerAppLinks.entitlements');
  final identity = read('ios/Flutter/Identity.xcconfig');
  final project = read('ios/Runner.xcodeproj/project.pbxproj');

  const signInWithApple =
      '<key>com.apple.developer.applesignin</key>\n'
      '\t<array>\n'
      '\t\t<string>Default</string>\n'
      '\t</array>';
  const associatedDomains = '<key>com.apple.developer.associated-domains</key>';

  String normalized(String text) => text.replaceAll('\r\n', '\n');

  test('both entitlements files have Sign in with Apple', () {
    expect(normalized(plain), contains(signInWithApple));
    expect(normalized(appLinks), contains(signInWithApple));
  });

  test('only RunnerAppLinks has the app-link host as associated domain', () {
    expect(plain, isNot(contains(associatedDomains)));
    expect(
      normalized(appLinks),
      contains(
        '$associatedDomains\n'
        '\t<array>\n'
        '\t\t<string>applinks:\$(SHUSHGIFT_APP_LINK_HOST)</string>\n'
        '\t</array>',
      ),
    );
  });

  test('Identity.xcconfig chooses Runner.entitlements before the local file',
      () {
    final lines = normalized(identity).split('\n');
    final choice =
        lines.indexOf('CODE_SIGN_ENTITLEMENTS = Runner/Runner.entitlements');
    final local = lines.indexOf('#include? "Identity.local.xcconfig"');
    expect(choice, isNot(-1));
    expect(local, greaterThan(choice));
    expect(lines, contains('SHUSHGIFT_APP_LINK_HOST ='));
  });

  test('the project does not override that choice', () {
    final settings = RegExp(r'CODE_SIGN_ENTITLEMENTS = ([^;]*);')
        .allMatches(project)
        .map((match) => match.group(1))
        .toList();
    // The tests' target alone, set empty: it signed with none before.
    expect(settings, ['""', '""', '""']);
    final runnerTests = RegExp(
      r'CODE_SIGN_ENTITLEMENTS = "";\s*CODE_SIGN_STYLE = Automatic;'
      r'[^}]*\.RunnerTests";',
    );
    expect(runnerTests.allMatches(project), hasLength(3));
  });
}
