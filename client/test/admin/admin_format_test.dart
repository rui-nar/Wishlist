import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/l10n/app_localizations.dart';
import 'package:wishlist/src/admin/admin_format.dart';

/// [read] in a context localised in [locale].
Future<T> inLocale<T>(
  WidgetTester tester,
  Locale locale,
  T Function(BuildContext context) read,
) async {
  late T value;
  await tester.pumpWidget(MaterialApp(
    locale: locale,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Builder(builder: (context) {
      value = read(context);
      return const SizedBox();
    }),
  ));
  return value;
}

void main() {
  testWidgets('sizes in decimal units, one decimal at most, in English',
      (tester) async {
    final sizes = await inLocale(
      tester,
      const Locale('en'),
      (context) => [
        for (final bytes in [0, 999, 1000, 1500, 999960, 1500000, 2340000000])
          formatBytes(context, bytes),
      ],
    );

    expect(sizes, [
      '0 B',
      '999 B',
      '1 KB',
      '1.5 KB',
      // Rounded as shown: never "1,000 KB".
      '1 MB',
      '1.5 MB',
      '2.3 GB',
    ]);
  });

  testWidgets("in French, the locale's comma and French units",
      (tester) async {
    final sizes = await inLocale(
      tester,
      const Locale('fr'),
      (context) => [
        for (final bytes in [640, 12500, 1500000, 2340000000])
          formatBytes(context, bytes),
      ],
    );

    expect(sizes, ['640 o', '12,5 ko', '1,5 Mo', '2,3 Go']);
  });
}
