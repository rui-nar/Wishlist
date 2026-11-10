import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import 'auth_controller.dart';
import 'email_link.dart';

/// The email and password fields of the sign-in screen (sign-in plan D10).
///
/// The fields carry the platform's autofill hints, so a password manager can
/// fill them. The outcome is [AuthController]'s, shown by the screen.
class EmailSignInForm extends StatefulWidget {
  const EmailSignInForm({super.key, required this.busy});

  /// A sign-in is running: the form stays, but cannot be sent again.
  final bool busy;

  @override
  State<EmailSignInForm> createState() => _EmailSignInFormState();
}

class _EmailSignInFormState extends State<EmailSignInForm> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  void _submit() {
    if (widget.busy || !_form.currentState!.validate()) return;
    context
        .read<AuthController>()
        .signInWithEmail(_email.text.trim(), _password.text);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AutofillGroup(
      child: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextFormField(
              controller: _email,
              enabled: !widget.busy,
              decoration: InputDecoration(labelText: l10n.signInEmailLabel),
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              autocorrect: false,
              autofillHints: const [AutofillHints.email],
              validator: (value) =>
                  isEmailAddress(value ?? '') ? null : l10n.signInEmailInvalid,
            ),
            const SizedBox(height: Spacing.s16),
            TextFormField(
              controller: _password,
              enabled: !widget.busy,
              decoration: InputDecoration(labelText: l10n.signInPasswordLabel),
              obscureText: true,
              autocorrect: false,
              enableSuggestions: false,
              textInputAction: TextInputAction.done,
              autofillHints: const [AutofillHints.password],
              onFieldSubmitted: (_) => _submit(),
              validator: (value) => (value == null || value.isEmpty)
                  ? l10n.signInPasswordRequired
                  : null,
            ),
            const SizedBox(height: Spacing.s16),
            FilledButton(
              onPressed: widget.busy ? null : _submit,
              child: Text(l10n.signInEmailAction),
            ),
          ],
        ),
      ),
    );
  }
}
