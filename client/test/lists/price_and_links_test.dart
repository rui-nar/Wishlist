import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/src/lists/currencies.dart';
import 'package:wishlist/src/lists/gift_links.dart';
import 'package:wishlist/src/lists/price.dart';

import 'support/fake_lists_server.dart';

void main() {
  group('formatPrice', () {
    test('follows the locale, not the currency (D13)', () {
      expect(formatPrice('149.00', 'EUR', 'en'), '€149.00');
      // French puts a (narrow) no-break space before the symbol.
      expect(
        formatPrice('149.00', 'EUR', 'fr'),
        matches(RegExp('^149,00[  ]€\$')),
      );
      expect(formatPrice('1234.5', 'USD', 'en'), r'$1,234.50');
    });
  });

  group('parseAmount', () {
    test('takes either decimal separator', () {
      expect(parseAmount('149'), '149');
      expect(parseAmount(' 149.9 '), '149.9');
      expect(parseAmount('149,90'), '149.90');
      expect(parseAmount('9999999999.99'), '9999999999.99');
    });

    test('refuses what the server would (D3)', () {
      for (final text in [
        '',
        '-1',
        '19.999',
        '10000000000',
        '1e3',
        '1 000',
        '12.',
        'abc',
      ]) {
        expect(parseAmount(text), isNull, reason: text);
      }
    });
  });

  group('webLink', () {
    test('absolute http and https links only (D12)', () {
      expect(webLink('https://shop.example/item?id=1'), isNotNull);
      expect(webLink('http://shop.example'), isNotNull);
      for (final link in [
        'javascript:alert(1)',
        'ftp://shop.example',
        'shop.example/item',
        '/item',
        'https://',
        'https://shop.example/a b',
        'mailto:a@example.com',
        '',
      ]) {
        expect(webLink(link), isNull, reason: link);
      }
    });

    test('openGiftLink opens http links externally and nothing else',
        () async {
      final launcher = installFakeUrlLauncher();

      expect(await openGiftLink('https://shop.example/h'), isTrue);
      expect(await openGiftLink('javascript:alert(1)'), isFalse);

      expect(launcher.launched, [
        ('https://shop.example/h', PreferredLaunchMode.externalApplication),
      ]);
    });
  });

  test("the currencies are the server's", () {
    // `flutter test` runs in client/; the server is next to it.
    final source =
        File('../server/app/lists/currencies.py').readAsStringSync();
    final codes = RegExp(r'CURRENCIES = frozenset\(\s*"""([^"]*)"""')
        .firstMatch(source)!
        .group(1)!
        .split(RegExp(r'\s+'))
        .where((code) => code.isNotEmpty)
        .toSet();
    expect(kCurrencies, codes);
    expect(kCurrencies, contains(kDefaultCurrency));
  });
}
