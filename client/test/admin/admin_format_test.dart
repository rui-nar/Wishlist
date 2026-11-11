import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/l10n/app_localizations.dart';
import 'package:wishlist/src/admin/admin_format.dart';
import 'package:wishlist/src/admin/admin_repository.dart';

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

  AdminSubscription subscription(String status, {DateTime? periodEnd}) =>
      AdminSubscription(
        status: status,
        startedAt: DateTime.utc(2026, 5, 2, 10),
        periodEnd: periodEnd ?? DateTime.utc(2027, 3, 12, 12),
      );

  AdminUserRow row({AdminSubscription? subscription, DateTime? grantEnd}) =>
      AdminUserRow(
        id: 'u1',
        email: 'bob@example.com',
        displayName: '',
        createdAt: DateTime.utc(2026, 5, 2),
        signIn: const ['google'],
        plan: const AdminPlan(isPremium: false),
        subscription: subscription,
        manualGrantEnd: grantEnd,
        listsOwned: 0,
        photos: const AdminPhotos(count: 0, bytes: 0, measuring: false),
      );

  testWidgets('a subscription on one short line, for each status',
      (tester) async {
    final lines = await inLocale(
      tester,
      const Locale('en'),
      (context) => [
        for (final status in ['active', 'past_due', 'canceling', 'incomplete'])
          subscriptionShortLine(context, subscription(status)),
        subscriptionShortLine(
          context,
          subscription('ended', periodEnd: DateTime.utc(2026, 3, 12, 12)),
        ),
        // Without its day, the status in words.
        subscriptionShortLine(
          context,
          const AdminSubscription(status: 'active'),
        ),
      ],
    );

    expect(lines, [
      'Stripe · renews Mar 12, 2027',
      'Stripe · payment failed',
      'Stripe · ends Mar 12, 2027',
      'Stripe · first payment not completed',
      'Stripe · ended Mar 12, 2026',
      'Stripe · Active',
    ]);
  });

  testWidgets('the plan cell: the subscription and the grant apart',
      (tester) async {
    final grantEnd = DateTime.utc(2027, 6, 1, 12);
    final cells = await inLocale(
      tester,
      const Locale('en'),
      (context) => [
        planLines(context, row()),
        planLines(context, row(subscription: subscription('active'))),
        planLines(context, row(grantEnd: grantEnd)),
        planLines(
          context,
          row(subscription: subscription('past_due'), grantEnd: grantEnd),
        ),
      ],
    );

    expect(cells, [
      ['Free'],
      ['Stripe · renews Mar 12, 2027'],
      ['Granted here until Jun 1, 2027'],
      ['Stripe · payment failed', 'Granted here until Jun 1, 2027'],
    ]);
  });

  testWidgets('the plan cell in French', (tester) async {
    final lines = await inLocale(
      tester,
      const Locale('fr'),
      (context) => planLines(
        context,
        row(
          subscription: subscription('canceling'),
          grantEnd: DateTime.utc(2027, 6, 1, 12),
        ),
      ),
    );

    expect(lines, [
      'Stripe · fin le 12 mars 2027',
      "Accordé ici jusqu'au 1 juin 2027",
    ]);
  });
}
