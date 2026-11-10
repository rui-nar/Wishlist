import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';

const kLegalTermsPath = '/legal/terms';
const kLegalPrivacyPath = '/legal/privacy';
const kLegalWithdrawalPath = '/legal/withdrawal';

/// The legal documents the app links to when the server names no address of
/// its own (PREMIUM_PLAN D17).
enum LegalDocument { terms, privacy, withdrawal }

/// `/legal/terms`, `/legal/privacy`, `/legal/withdrawal`: a public page that
/// says plainly it is a placeholder. It carries no legal wording, and nothing
/// on it binds anyone (PREMIUM_PLAN D17).
class LegalPlaceholderScreen extends StatelessWidget {
  const LegalPlaceholderScreen({super.key, required this.document});

  final LegalDocument document;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final title = switch (document) {
      LegalDocument.terms => l10n.legalTerms,
      LegalDocument.privacy => l10n.legalPrivacy,
      LegalDocument.withdrawal => l10n.legalWithdrawal,
    };
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: PageFrame(
        child: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.reading),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: Text(
                    l10n.legalPlaceholderBody,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
