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

  // The panel's today.
  setUp(() => adminClock = () => DateTime(2026, 11, 11, 10));
  tearDown(() => adminClock = DateTime.now);

  AdminSubscription subscription(String status, {DateTime? periodEnd}) =>
      AdminSubscription(
        status: status,
        startedAt: DateTime.utc(2026, 5, 2, 10),
        periodEnd: periodEnd ?? DateTime.utc(2027, 3, 12, 12),
      );

  AdminUserRow row({
    AdminSubscription? subscription,
    DateTime? grantEnd,
    AdminPlan plan = const AdminPlan(isPremium: false),
  }) =>
      AdminUserRow(
        id: 'u1',
        email: 'bob@example.com',
        displayName: '',
        createdAt: DateTime.utc(2026, 5, 2),
        signIn: const ['google'],
        plan: plan,
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
        for (final status in ['active', 'past_due', 'canceling'])
          subscriptionShortLine(context, subscription(status)),
        // The server sends no day for these (review R5-1).
        for (final status in ['incomplete', 'ended'])
          subscriptionShortLine(context, AdminSubscription(status: status)),
        subscriptionShortLine(
          context,
          subscription('no_news', periodEnd: DateTime.utc(2026, 10, 1, 12)),
        ),
        subscriptionShortLine(
          context,
          const AdminSubscription(status: 'no_news'),
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
      'Stripe · ended',
      'Stripe · no news since Oct 1, 2026',
      'Stripe · no news',
      'Stripe · Active',
    ]);
  });

  testWidgets('a subscription in words on the account page, for each status',
      (tester) async {
    final lines = await inLocale(
      tester,
      const Locale('en'),
      (context) => [
        for (final status in ['active', 'past_due', 'canceling'])
          (
            subscriptionStatus(context, subscription(status)),
            subscriptionEndLine(context, subscription(status)),
          ),
        for (final status in ['incomplete', 'ended'])
          (
            subscriptionStatus(context, AdminSubscription(status: status)),
            subscriptionEndLine(context, AdminSubscription(status: status)),
          ),
        for (final sub in [
          subscription('no_news', periodEnd: DateTime.utc(2026, 10, 1, 12)),
          const AdminSubscription(status: 'no_news'),
        ])
          (
            subscriptionStatus(context, sub),
            subscriptionEndLine(context, sub),
          ),
      ],
    );

    expect(lines, [
      ('Active', 'Renews on Mar 12, 2027'),
      ('Payment overdue', 'Renews on Mar 12, 2027'),
      ('Cancellation scheduled', 'Ends on Mar 12, 2027'),
      ('First payment not completed', null),
      ('Ended', null),
      // Its day is in the status: no second line for it.
      ('No news from Stripe since Oct 1, 2026', null),
      ('No news from Stripe', null),
    ]);
  });

  test('a grant is expired once its day is before today', () {
    expect(grantExpired(DateTime(2026, 11, 10, 23)), isTrue);
    expect(grantExpired(DateTime(2026, 11, 11)), isFalse);
    expect(grantExpired(DateTime(2026, 11, 12)), isFalse);
    adminClock = () => DateTime(2026, 11, 12, 0, 1);
    expect(grantExpired(DateTime(2026, 11, 11, 23)), isTrue);
  });

  testWidgets(
      'the plan cell: the effective plan, then the subscription and the '
      'grant apart', (tester) async {
    final grantEnd = DateTime.utc(2027, 6, 1, 12);
    final premium = AdminPlan(isPremium: true, source: 'manual', until: grantEnd);
    final cells = await inLocale(
      tester,
      const Locale('en'),
      (context) => [
        planLines(context, row()),
        planLines(context, row(subscription: subscription('active'))),
        planLines(context, row(grantEnd: grantEnd, plan: premium)),
        planLines(
          context,
          row(subscription: subscription('past_due'), grantEnd: grantEnd),
        ),
        // Its day has passed: it grants nothing, and the plan says so.
        planLines(context, row(grantEnd: DateTime.utc(2026, 10, 1, 12))),
        planLines(context, row(grantEnd: DateTime.utc(2026, 11, 11, 12))),
      ],
    );

    expect(cells, [
      ['Free'],
      ['Free', 'Stripe · renews Mar 12, 2027'],
      [
        'Premium until Jun 1, 2027 · granted here',
        'Granted here until Jun 1, 2027',
      ],
      [
        'Free',
        'Stripe · payment failed',
        'Granted here until Jun 1, 2027',
      ],
      ['Free', 'Granted here until Oct 1, 2026 (expired)'],
      ['Free', 'Granted here until Nov 11, 2026'],
    ]);
  });

  testWidgets('the plan cell in French', (tester) async {
    final cells = await inLocale(
      tester,
      const Locale('fr'),
      (context) => [
        planLines(
          context,
          row(
            subscription: subscription('canceling'),
            grantEnd: DateTime.utc(2027, 6, 1, 12),
          ),
        ),
        planLines(
          context,
          row(
            subscription: subscription(
              'no_news',
              periodEnd: DateTime.utc(2026, 10, 1, 12),
            ),
            grantEnd: DateTime.utc(2026, 10, 1, 12),
          ),
        ),
        planLines(
          context,
          row(subscription: const AdminSubscription(status: 'ended')),
        ),
      ],
    );

    expect(cells, [
      [
        'Gratuite',
        'Stripe · fin le 12 mars 2027',
        "Accordé ici jusqu'au 1 juin 2027",
      ],
      [
        'Gratuite',
        'Stripe · aucune nouvelle depuis le 1 oct. 2026',
        "Accordé ici jusqu'au 1 oct. 2026 (expiré)",
      ],
      ['Gratuite', 'Stripe · terminé'],
    ]);
  });
}
