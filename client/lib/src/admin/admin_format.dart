/// How the admin panel words what the server counts.
library;

import 'package:flutter/widgets.dart';
import 'package:intl/intl.dart';

import '../../l10n/app_localizations.dart';
import 'admin_repository.dart';

/// [bytes] in the largest unit under 1000 of it, decimal units as phones and
/// Macs show file sizes, one decimal at most, with the locale's separator:
/// `1.5 MB` in English, `1,5 Mo` in French.
String formatBytes(BuildContext context, int bytes) {
  final l10n = AppLocalizations.of(context);
  final number = NumberFormat('#,##0.#', Localizations.localeOf(context).toString());
  if (bytes < 1000) return l10n.sizeBytes(number.format(bytes));
  final units = [l10n.sizeKilobytes, l10n.sizeMegabytes, l10n.sizeGigabytes];
  var value = bytes / 1000;
  var unit = 0;
  // Rounded as shown, so 999,960 bytes reads 1 MB, not 1,000 KB.
  while (unit < units.length - 1 && _rounded(value) >= 1000) {
    value /= 1000;
    unit++;
  }
  return units[unit](number.format(value));
}

double _rounded(double value) => (value * 10).roundToDouble() / 10;

/// A calendar day in the locale: `12 Mar 2027`, `12 mars 2027`.
String formatDay(BuildContext context, DateTime date) => DateFormat.yMMMd(
      Localizations.localeOf(context).toString(),
    ).format(date.toLocal());

/// The panel's clock. Tests set it to a fixed day, and set it back.
DateTime Function() adminClock = DateTime.now;

/// Today, a calendar day by [adminClock].
DateTime adminToday() {
  final now = adminClock();
  return DateTime(now.year, now.month, now.day);
}

/// The admin's grant ending on [end] is over: its day is before today.
bool grantExpired(DateTime end) {
  final local = end.toLocal();
  return DateTime(local.year, local.month, local.day).isBefore(adminToday());
}

/// The ways a user signs in, in words; [compact] for the table's column.
String signInLine(
  AppLocalizations l10n,
  List<String> providers, {
  bool compact = false,
}) {
  if (providers.isEmpty) return l10n.adminSignInNone;
  return providers
      .map((provider) => switch (provider) {
            'google' => l10n.adminSignInGoogle,
            'apple' => l10n.adminSignInApple,
            'email' when compact => l10n.adminSignInEmailShort,
            'email' => l10n.adminSignInEmail,
            _ => provider,
          })
      .join(', ');
}

/// Free, or Premium with its end and where it comes from.
String planLine(BuildContext context, AdminPlan plan) {
  final l10n = AppLocalizations.of(context);
  if (!plan.isPremium) return l10n.adminPlanFree;
  final until = plan.until;
  final premium = until == null
      ? l10n.planPremium
      : l10n.adminPlanPremiumUntil(formatDay(context, until));
  final source = switch (plan.source) {
    'manual' => l10n.adminSourceManual,
    'stripe' => l10n.adminSourceStripe,
    'apple' => l10n.adminSourceApple,
    'google' => l10n.adminSourceGoogle,
    final other => other,
  };
  return source == null ? premium : l10n.adminFiguresLine(premium, source);
}

/// Who sells a subscription the panel shows: each in a block of its own.
enum SubscriptionSeller { stripe, apple, google }

/// A subscription's status in words, Stripe's unless [seller] says
/// otherwise; `no_news` with the last day the seller gave. A store's
/// `past_due` without a day is Apple's billing retry, or Google's account
/// hold or pause (Android release plan D6).
String subscriptionStatus(
  BuildContext context,
  AdminSubscription subscription, {
  SubscriptionSeller seller = SubscriptionSeller.stripe,
}) {
  final l10n = AppLocalizations.of(context);
  final end = subscription.periodEnd;
  return switch ((subscription.status, end)) {
    ('active', _) => l10n.adminSubscriptionActive,
    ('past_due', null) when seller == SubscriptionSeller.google =>
      l10n.adminGoogleOnHold,
    ('past_due', _) => l10n.adminSubscriptionPastDue,
    ('canceling', _) => l10n.adminSubscriptionCanceling,
    ('incomplete', _) => l10n.adminSubscriptionIncomplete,
    ('ended', _) => l10n.adminSubscriptionEnded,
    ('no_news', final DateTime end) => switch (seller) {
        SubscriptionSeller.stripe =>
          l10n.adminSubscriptionNoNewsSince(formatDay(context, end)),
        SubscriptionSeller.apple =>
          l10n.adminAppleNoNewsSince(formatDay(context, end)),
        SubscriptionSeller.google =>
          l10n.adminGoogleNoNewsSince(formatDay(context, end)),
      },
    ('no_news', _) => switch (seller) {
        SubscriptionSeller.stripe => l10n.adminSubscriptionNoNews,
        SubscriptionSeller.apple => l10n.adminAppleNoNews,
        SubscriptionSeller.google => l10n.adminGoogleNoNews,
      },
    (final other, _) => other,
  };
}

/// When the subscription renews or ends; null without the day, and for the
/// statuses whose day says nothing of it (review R5-1) or that their status
/// already dates. A store's one past due is in the store's grace period,
/// which ends on its day (Apple IAP plan D5, Android release plan D6).
String? subscriptionEndLine(
  BuildContext context,
  AdminSubscription subscription, {
  SubscriptionSeller seller = SubscriptionSeller.stripe,
}) {
  final l10n = AppLocalizations.of(context);
  final end = subscription.periodEnd;
  if (end == null) return null;
  final day = formatDay(context, end);
  return switch ((subscription.status, seller)) {
    ('past_due', SubscriptionSeller.apple) => l10n.adminAppleGraceUntil(day),
    ('past_due', SubscriptionSeller.google) =>
      l10n.adminGoogleGraceUntil(day),
    ('active' || 'past_due', _) => l10n.adminSubscriptionRenews(day),
    ('canceling', _) => l10n.adminSubscriptionEnds(day),
    _ => null,
  };
}

/// The subscription on one short line of the users list:
/// `Stripe · renews 12 Mar 2027`, `App Store · …` or `Google Play · …` by
/// [seller].
String subscriptionShortLine(
  BuildContext context,
  AdminSubscription subscription, {
  SubscriptionSeller seller = SubscriptionSeller.stripe,
}) {
  final l10n = AppLocalizations.of(context);
  final end = subscription.periodEnd;
  final day = end == null ? null : formatDay(context, end);
  final state = switch ((subscription.status, day)) {
    ('past_due', null) when seller == SubscriptionSeller.google =>
      l10n.adminGoogleOnHoldShort,
    ('past_due', _) => l10n.adminStripePaymentFailed,
    ('incomplete', _) => l10n.adminStripeIncomplete,
    ('ended', _) => l10n.adminStripeEnded,
    ('active', final String day) => l10n.adminStripeRenews(day),
    ('canceling', final String day) => l10n.adminStripeEnds(day),
    ('no_news', final String day) => l10n.adminStripeNoNews(day),
    ('no_news', _) => l10n.adminStripeNoNewsUndated,
    // Without its day, the status in words.
    _ => subscriptionStatus(context, subscription, seller: seller),
  };
  return l10n.adminFiguresLine(
    switch (seller) {
      SubscriptionSeller.stripe => l10n.adminSourceStripe,
      SubscriptionSeller.apple => l10n.adminSourceApple,
      SubscriptionSeller.google => l10n.adminSourceGoogle,
    },
    state,
  );
}

/// The users list's plan: the effective plan first, then the Stripe, Apple
/// and Google subscriptions and the grant on lines of their own, so none
/// hides another.
List<String> planLines(BuildContext context, AdminUserRow user) {
  final l10n = AppLocalizations.of(context);
  final subscription = user.subscription;
  final apple = user.appleSubscription;
  final google = user.googleSubscription;
  final grantEnd = user.manualGrantEnd;
  return [
    planLine(context, user.plan),
    if (subscription != null) subscriptionShortLine(context, subscription),
    if (apple != null)
      subscriptionShortLine(context, apple, seller: SubscriptionSeller.apple),
    if (google != null)
      subscriptionShortLine(
        context,
        google,
        seller: SubscriptionSeller.google,
      ),
    if (grantEnd != null)
      grantExpired(grantEnd)
          ? l10n.adminGrantedUntilExpired(formatDay(context, grantEnd))
          : l10n.adminGrantedUntil(formatDay(context, grantEnd)),
  ];
}

/// The photos' count and space, or "measuring" while some are not measured.
String photosLine(BuildContext context, AdminPhotos photos) {
  final l10n = AppLocalizations.of(context);
  final count = l10n.adminPhotoCount(photos.count);
  if (photos.count == 0) return count;
  return l10n.adminFiguresLine(
    count,
    photos.measuring ? l10n.adminPhotosMeasuring : formatBytes(context, photos.bytes),
  );
}
