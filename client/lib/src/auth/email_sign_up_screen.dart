import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../app_router.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../lists/common.dart';
import '../shared/pending_join.dart';
import 'email_link.dart';

enum _Stage { enter, sending, sent }

/// `/email-sign-up`: the address, then "check your inbox" (sign-in plan D2).
///
/// One flow for creating an account and replacing a forgotten password: the
/// server decides which from the address, and says nothing about it (D5), so
/// neither does this page.
class EmailSignUpScreen extends StatefulWidget {
  const EmailSignUpScreen({super.key, this.from});

  /// Where the user was going, kept for the way back to sign-in.
  final String? from;

  @override
  State<EmailSignUpScreen> createState() => _EmailSignUpScreenState();
}

class _EmailSignUpScreenState extends State<EmailSignUpScreen> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  _Stage _stage = _Stage.enter;
  Object? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_stage == _Stage.sending || !_form.currentState!.validate()) return;
    final api = context.read<ApiClient>();
    final pendingJoin = context.read<PendingJoin>();
    final language =
        Localizations.localeOf(context).languageCode == 'fr' ? 'fr' : 'en';
    setState(() {
      _stage = _Stage.sending;
      _error = null;
    });
    await pendingJoin.handOverForEmailLink();
    try {
      await startEmailLink(api, email: _email.text.trim(), language: language);
      if (mounted) setState(() => _stage = _Stage.sent);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _stage = _Stage.enter;
      });
    }
  }

  void _backToSignIn() => context.go(
        Uri(
          path: kSignInPath,
          queryParameters: widget.from == null ? null : {'from': widget.from},
        ).toString(),
      );

  String _failure(AppLocalizations l10n) => switch (_error) {
        ApiException(statusCode: 429) => l10n.signInTooManyAttempts,
        ApiException(statusCode: 422) => l10n.signInEmailInvalid,
        ApiException(statusCode: 503) => l10n.signInNotConfigured,
        final error => failureMessage(l10n, error),
      };

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final textTheme = Theme.of(context).textTheme;
    final sending = _stage == _Stage.sending;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.emailSignUpTitle)),
      body: PageFrame(
        child: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.form),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: _stage == _Stage.sent
                        ? [
                            Text(
                              l10n.checkInboxTitle,
                              style: textTheme.headlineSmall,
                            ),
                            const SizedBox(height: Spacing.s8),
                            Text(
                              l10n.checkInboxBody(_email.text.trim()),
                              style: textTheme.bodyLarge,
                            ),
                            const SizedBox(height: Spacing.s24),
                            OutlinedButton(
                              onPressed: () =>
                                  setState(() => _stage = _Stage.enter),
                              child: Text(l10n.checkInboxDifferentAddress),
                            ),
                            const SizedBox(height: Spacing.s8),
                            TextButton(
                              onPressed: _backToSignIn,
                              child: Text(l10n.emailSignUpBack),
                            ),
                          ]
                        : [
                            Text(
                              l10n.emailSignUpBody,
                              style: textTheme.bodyLarge,
                            ),
                            const SizedBox(height: Spacing.s16),
                            AutofillGroup(
                              child: Form(
                                key: _form,
                                child: TextFormField(
                                  controller: _email,
                                  enabled: !sending,
                                  decoration: InputDecoration(
                                    labelText: l10n.signInEmailLabel,
                                  ),
                                  keyboardType: TextInputType.emailAddress,
                                  textInputAction: TextInputAction.send,
                                  autocorrect: false,
                                  autofillHints: const [AutofillHints.email],
                                  onFieldSubmitted: (_) => _send(),
                                  validator: (value) =>
                                      isEmailAddress(value ?? '')
                                          ? null
                                          : l10n.signInEmailInvalid,
                                ),
                              ),
                            ),
                            const SizedBox(height: Spacing.s16),
                            FilledButton(
                              onPressed: sending ? null : _send,
                              child: Text(l10n.emailSignUpSend),
                            ),
                            if (_error != null) ...[
                              const SizedBox(height: Spacing.s16),
                              ErrorLine(_failure(l10n)),
                            ],
                            const SizedBox(height: Spacing.s8),
                            TextButton(
                              onPressed: _backToSignIn,
                              child: Text(l10n.emailSignUpBack),
                            ),
                          ],
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
