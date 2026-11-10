import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../legal/legal_placeholder_screen.dart';
import '../lists/gift_links.dart';
import 'billing_repository.dart';

/// The three legal links of a sale: the address the server names, or the
/// app's own placeholder page when it names none (PREMIUM_PLAN D17). Shown
/// where something can be bought, so on the web only (D18).
class LegalLinks extends StatelessWidget {
  const LegalLinks({super.key, required this.legal});

  final LegalUrls legal;

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
      (l10n.legalTerms, legal.terms, kLegalTermsPath),
      (l10n.legalPrivacy, legal.privacy, kLegalPrivacyPath),
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
