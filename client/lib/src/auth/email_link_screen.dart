import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../shared/pending_join.dart';
import 'auth_controller.dart';
import 'email_link.dart';

/// Which page a mailed link opened.
enum EmailLinkKind { create, reset }

enum _Stage { enter, sending, expired }

/// `/create-account` and `/reset-password`: the page a mailed link opens, to
/// choose a password; on success the session, and the occasion link that was
/// waiting if there is one (sign-in plan D2, D9, D19).
///
/// Public: a link works signed out, and a signed-in person who follows one
/// ends up in that account. Nothing is sent until the button is pressed, since
/// mail security scanners open links, so opening the page does not use it up.
class EmailLinkScreen extends StatefulWidget {
  const EmailLinkScreen({super.key, required this.kind, required this.token});

  final EmailLinkKind kind;

  /// From the link's fragment; null when the address has none, as after a
  /// reload.
  final String? token;

  @override
  State<EmailLinkScreen> createState() => _EmailLinkScreenState();
}

class _EmailLinkScreenState extends State<EmailLinkScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _password = TextEditingController();
  late _Stage _stage = widget.token == null ? _Stage.expired : _Stage.enter;
  EmailLinkFailure? _failure;

  bool get _creating => widget.kind == EmailLinkKind.create;

  @override
  void dispose() {
    _name.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_stage == _Stage.sending || !_form.currentState!.validate()) return;
    final auth = context.read<AuthController>();
    final pendingJoin = context.read<PendingJoin>();
    setState(() {
      _stage = _Stage.sending;
      _failure = null;
    });
    final failure = await auth.completeEmailLink(
      token: widget.token!,
      password: _password.text,
      displayName: _creating ? _name.text.trim() : null,
    );
    if (failure == null) {
      await pendingJoin.resumeAfterEmailLink();
      if (!mounted) return;
      // In this page's place, so going back does not come to a used link.
      final target = pendingJoin.token == null ? '/' : kJoinPath;
      Router.neglect(context, () => context.go(target));
      return;
    }
    if (!mounted) return;
    setState(() {
      _failure = failure;
      _stage = failure == EmailLinkFailure.expired
          ? _Stage.expired
          : _Stage.enter;
    });
  }

  String? _nameError(AppLocalizations l10n, String? value) {
    final length = (value ?? '').trim().runes.length;
    if (length == 0) return l10n.emailLinkNameRequired;
    return length > 100 ? l10n.emailLinkNameTooLong : null;
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final sending = _stage == _Stage.sending;
    return Scaffold(
      appBar: AppBar(
        title: Text(_creating ? l10n.registerTitle : l10n.resetPasswordTitle),
      ),
      body: PageFrame(
        child: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.form),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: _stage == _Stage.expired
                      ? _Expired(onNewLink: () => context.go(kEmailSignUpPath))
                      : AutofillGroup(
                          child: Form(
                            key: _form,
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                if (_creating) ...[
                                  TextFormField(
                                    controller: _name,
                                    enabled: !sending,
                                    decoration: InputDecoration(
                                      labelText: l10n.emailLinkNameLabel,
                                    ),
                                    textInputAction: TextInputAction.next,
                                    autofillHints: const [AutofillHints.name],
                                    validator: (value) =>
                                        _nameError(l10n, value),
                                  ),
                                  const SizedBox(height: Spacing.s16),
                                ],
                                TextFormField(
                                  controller: _password,
                                  enabled: !sending,
                                  decoration: InputDecoration(
                                    labelText: _creating
                                        ? l10n.emailLinkPasswordLabel
                                        : l10n.emailLinkNewPasswordLabel,
                                    helperText: l10n.emailLinkPasswordHelp,
                                  ),
                                  obscureText: true,
                                  autocorrect: false,
                                  enableSuggestions: false,
                                  textInputAction: TextInputAction.done,
                                  autofillHints: const [
                                    AutofillHints.newPassword,
                                  ],
                                  onFieldSubmitted: (_) => _submit(),
                                  validator: (value) =>
                                      isAcceptablePassword(value ?? '')
                                          ? null
                                          : l10n.emailLinkPasswordLength,
                                ),
                                const SizedBox(height: Spacing.s24),
                                FilledButton(
                                  onPressed: sending ? null : _submit,
                                  child: Text(
                                    _creating
                                        ? l10n.createAccountAction
                                        : l10n.resetPasswordAction,
                                  ),
                                ),
                                if (_failure != null) ...[
                                  const SizedBox(height: Spacing.s16),
                                  ErrorLine(switch (_failure!) {
                                    EmailLinkFailure.tooManyAttempts =>
                                      l10n.signInTooManyAttempts,
                                    EmailLinkFailure.notAccepted =>
                                      l10n.emailLinkNotAccepted,
                                    EmailLinkFailure.unreachable =>
                                      l10n.serverUnreachable,
                                    EmailLinkFailure.expired ||
                                    EmailLinkFailure.serverError =>
                                      l10n.serverError,
                                  }),
                                ],
                              ],
                            ),
                          ),
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

/// The link cannot be used: why, and a button to ask for another.
class _Expired extends StatelessWidget {
  const _Expired({required this.onNewLink});

  final VoidCallback onNewLink;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ErrorLine(l10n.emailLinkExpired),
        const SizedBox(height: Spacing.s16),
        OutlinedButton(onPressed: onNewLink, child: Text(l10n.emailLinkNewLink)),
      ],
    );
  }
}
