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

/// A Stripe subscription's status in words.
String subscriptionStatus(AppLocalizations l10n, String status) =>
    switch (status) {
      'active' => l10n.adminSubscriptionActive,
      'past_due' => l10n.adminSubscriptionPastDue,
      'canceling' => l10n.adminSubscriptionCanceling,
      'incomplete' => l10n.adminSubscriptionIncomplete,
      'ended' => l10n.adminSubscriptionEnded,
      final other => other,
    };

/// When the subscription renews, ends or ended; null without the day.
String? subscriptionEndLine(
  BuildContext context,
  AdminSubscription subscription,
) {
  final l10n = AppLocalizations.of(context);
  final end = subscription.periodEnd;
  if (end == null) return null;
  final day = formatDay(context, end);
  return switch (subscription.status) {
    'active' || 'past_due' => l10n.adminSubscriptionRenews(day),
    'ended' => l10n.adminSubscriptionEndedOn(day),
    _ => l10n.adminSubscriptionEnds(day),
  };
}

/// The subscription on one short line of the users list:
/// `Stripe · renews 12 Mar 2027`.
String subscriptionShortLine(
  BuildContext context,
  AdminSubscription subscription,
) {
  final l10n = AppLocalizations.of(context);
  final end = subscription.periodEnd;
  final day = end == null ? null : formatDay(context, end);
  final state = switch ((subscription.status, day)) {
    ('past_due', _) => l10n.adminStripePaymentFailed,
    ('incomplete', _) => l10n.adminStripeIncomplete,
    ('active', final String day) => l10n.adminStripeRenews(day),
    ('canceling', final String day) => l10n.adminStripeEnds(day),
    ('ended', final String day) => l10n.adminStripeEnded(day),
    // Without its day, the status in words.
    (final status, _) => subscriptionStatus(l10n, status),
  };
  return l10n.adminFiguresLine(l10n.adminSourceStripe, state);
}

/// The users list's plan: the Stripe subscription and the grant on lines of
/// their own, so neither hides the other; the effective plan when there is
/// neither.
List<String> planLines(BuildContext context, AdminUserRow user) {
  final subscription = user.subscription;
  final grantEnd = user.manualGrantEnd;
  if (subscription == null && grantEnd == null) {
    return [planLine(context, user.plan)];
  }
  final l10n = AppLocalizations.of(context);
  return [
    if (subscription != null) subscriptionShortLine(context, subscription),
    if (grantEnd != null) l10n.adminGrantedUntil(formatDay(context, grantEnd)),
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
