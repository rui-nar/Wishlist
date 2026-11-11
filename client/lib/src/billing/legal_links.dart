import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../legal/legal_placeholder_screen.dart';
import '../lists/gift_links.dart';
import 'billing_repository.dart';
import 'store.dart';

/// The legal links of a sale: the address the server names, or the app's own
/// placeholder page when it names none (PREMIUM_PLAN D17). Shown where
/// something can be bought: on the web, all three (D18); in the iOS app, where
/// Apple sells and handles withdrawal, the terms, Apple's standard licence
/// when the server names none, and the privacy policy (Apple IAP plan D8); in
/// the Android app, where Google Play sells and handles refunds, the terms and
/// the privacy policy (Android release plan D8).
class LegalLinks extends StatelessWidget {
  const LegalLinks({super.key, required this.legal, this.store});

  final LegalUrls legal;

  /// The phone store that sells in this app; null on the web.
  final StoreSource? store;

  Future<void> _open(BuildContext context, String? url, String page) async {
    if (url == null) {
      context.push(page);
      return;
    }
    final message = AppLocalizations.of(context).planActionFailed;
    final messenger = ScaffoldMessenger.of(context);
    if (!await openGiftLink(url)) {
      messenger.showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final links = [
      (
        l10n.legalTerms,
        store == StoreSource.apple
            ? legal.terms ?? kAppleStandardEulaUrl
            : legal.terms,
        kLegalTermsPath,
      ),
      (l10n.legalPrivacy, legal.privacy, kLegalPrivacyPath),
      if (store == null)
        (l10n.legalWithdrawal, legal.withdrawal, kLegalWithdrawalPath),
    ];
    return Wrap(
      spacing: Spacing.s8,
      children: [
        for (final (label, url, page) in links)
          TextButton(
            onPressed: () => _open(context, url, page),
            child: Text(label),
          ),
      ],
    );
  }
}
