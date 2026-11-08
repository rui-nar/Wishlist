import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The ARB files must agree (DESIGN_SYSTEM_PLAN D8): gen-l10n falls back to
/// the template for a missing key without failing, and does not compare
/// placeholders between languages.
void main() {
  // `flutter test` runs from the package root.
  final template = _readArb('lib/l10n/app_en.arb');
  final french = _readArb('lib/l10n/app_fr.arb');

  test('the French file has the same message keys as the template', () {
    expect(_messageKeys(french), _messageKeys(template));
  });

  test('every message has the same placeholders in both files', () {
    final shared = _messageKeys(template).intersection(_messageKeys(french));
    for (final key in shared) {
      expect(
        placeholdersOf(french[key] as String),
        placeholdersOf(template[key] as String),
        reason: key,
      );
    }
  });

  test('every template message has an @ description', () {
    for (final key in _messageKeys(template)) {
      final meta = template['@$key'];
      expect(
        meta is Map &&
            meta['description'] is String &&
            (meta['description'] as String).trim().isNotEmpty,
        isTrue,
        reason: '@$key.description',
      );
    }
  });

  group('placeholdersOf', () {
    test('finds simple arguments', () {
      expect(placeholdersOf('Server {version} ({env})'), {'version', 'env'});
      expect(placeholdersOf('No argument'), isEmpty);
    });

    test('finds plural and select arguments, not their sub-message text', () {
      expect(
        placeholdersOf('{count, plural, =1{one {item}} other{{count} items}}'),
        {'count', 'item'},
      );
      expect(placeholdersOf('{role, select, a{x} other{y}}'), {'role'});
    });
  });
}

Map<String, dynamic> _readArb(String path) =>
    jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;

/// The message keys: every key but the `@` metadata and `@@` globals.
Set<String> _messageKeys(Map<String, dynamic> arb) =>
    arb.keys.where((key) => !key.startsWith('@')).toSet();

/// The argument names of an ICU message: `{name}`, and the `name` of
/// `{name, plural, ...}` or `{name, select, ...}`, including those nested in
/// sub-messages. Text in braces after an argument's type is a sub-message,
/// not an argument.
Set<String> placeholdersOf(String message) {
  final names = <String>{};
  // Whether each open brace started an argument (true) or a sub-message.
  final opened = <bool>[];
  for (var i = 0; i < message.length; i++) {
    final char = message[i];
    if (char == '{') {
      final inArgument = opened.isNotEmpty && opened.last;
      if (inArgument) {
        opened.add(false);
      } else {
        opened.add(true);
        final name = RegExp(r'\s*(\w+)').matchAsPrefix(message, i + 1);
        if (name != null) names.add(name.group(1)!);
      }
    } else if (char == '}' && opened.isNotEmpty) {
      opened.removeLast();
    }
  }
  return names;
}
