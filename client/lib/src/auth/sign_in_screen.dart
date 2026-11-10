import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../api/config.dart';
import '../design/tokens.dart';
import '../design/widgets/backdrop.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../app_router.dart';
import 'auth_controller.dart';
import 'email_link.dart';
import 'email_sign_in_form.dart';
// Web: Google's own button. Android and iOS: a stub, since they show a
// themed button calling authenticate().
import 'google_button_stub.dart'
    if (dart.library.js_interop) 'google_button_web.dart';
import 'google_sign_in_init.dart';

/// The app's name and each way of signing in that the server offers, in a
/// card (ACCOUNTS_PLAN D10), on the bold backdrop (WEB_LAYOUT_PLAN D9).
///
/// [register] is the welcome page's Register (WEB_LAYOUT_PLAN D7): the first
/// Google sign-in creates the account, so it changes only the heading and
/// the prompt. [offerWelcome] adds a link to the welcome page, for a visitor
/// who is not in the middle of following a link.
///
/// Reads the Google client ID from `/api/config` (D6) and initialises Google
/// sign-in with it: the only place that does, so Google's script loads only
/// here on the web (D11). When the server offers no way of signing in it says
/// sign-in is not available instead of showing a button that cannot work.
/// Once signed in, the router's guard takes the user where they were going.
class SignInScreen extends StatefulWidget {
  const SignInScreen({
    super.key,
    this.register = false,
    this.offerWelcome = false,
    this.from,
  });

  final bool register;
  final bool offerWelcome;

  /// Where the user is going after signing in, to carry through the page that
  /// asks for an email link and back.
  final String? from;

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  late Future<ClientConfig> _config;
  StreamSubscription<GoogleSignInAuthenticationEvent>? _googleEvents;

  /// Whether Google sign-in finished initialising; the button waits for it.
  bool _googleReady = false;

  /// Whether Google's side failed: initialising, or its sign-in flow.
  bool _googleFailed = false;

  @override
  void initState() {
    super.initState();
    _googleEvents = GoogleSignIn.instance.authenticationEvents.listen(
      _onGoogleEvent,
      onError: _onGoogleError,
    );
    _loadConfig();
  }

  @override
  void dispose() {
    _googleEvents?.cancel();
    super.dispose();
  }

  void _loadConfig() {
    _config = fetchClientConfig(context.read<ApiClient>());
    _config.then((config) {
      final clientId = config.googleClientId;
      if (clientId == null) return;
      ensureGoogleSignInInitialized(clientId).then((_) {
        if (mounted) setState(() => _googleReady = true);
      }, onError: (Object _) {
        if (mounted) setState(() => _googleFailed = true);
      });
    }, onError: (Object _) {
      // Shown by the FutureBuilder.
    });
  }

  void _retryConfig() => setState(_loadConfig);

  /// A Google account from the web button or from authenticate(): its ID
  /// token goes to the server.
  void _onGoogleEvent(GoogleSignInAuthenticationEvent event) {
    if (event is! GoogleSignInAuthenticationEventSignIn || !mounted) return;
    final idToken = event.user.authentication.idToken;
    if (idToken == null || idToken.isEmpty) {
      _onGoogleError(StateError('no ID token'));
      return;
    }
    setState(() => _googleFailed = false);
    context.read<AuthController>().signInWithGoogle(idToken);
  }

  void _onGoogleError(Object error) {
    if (!mounted) return;
    if (error is GoogleSignInException &&
        error.code == GoogleSignInExceptionCode.canceled) {
      return;
    }
    setState(() => _googleFailed = true);
  }

  /// Android and iOS: Google's account picker. The account arrives through
  /// [GoogleSignIn.authenticationEvents], like the web button's.
  Future<void> _authenticate() async {
    setState(() => _googleFailed = false);
    try {
      await GoogleSignIn.instance.authenticate();
    } on GoogleSignInException catch (e) {
      _onGoogleError(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final textTheme = Theme.of(context).textTheme;
    return Scaffold(
      body: PageFrame(
        intensity: BackdropIntensity.bold,
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.form),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        widget.register ? l10n.registerTitle : l10n.appTitle,
                        style: textTheme.headlineMedium,
                      ),
                      const SizedBox(height: Spacing.s8),
                      Text(
                        widget.register
                            ? l10n.registerPrompt
                            : l10n.signInPrompt,
                        style: textTheme.bodyLarge,
                      ),
                      const SizedBox(height: Spacing.s24),
                      FutureBuilder<ClientConfig>(
                        future: _config,
                        builder: (context, snapshot) {
                          if (snapshot.hasError) {
                            return _ConfigError(
                              message: snapshot.error is ApiException
                                  ? l10n.serverError
                                  : l10n.serverUnreachable,
                              onRetry: _retryConfig,
                            );
                          }
                          final config = snapshot.data;
                          if (config == null) return const _Progress();
                          if (config.googleClientId == null &&
                              !config.emailSignIn) {
                            return Text(
                              l10n.signInNotConfigured,
                              style: textTheme.bodyLarge,
                            );
                          }
                          return _signIn(context, l10n, config);
                        },
                      ),
                      if (widget.offerWelcome) ...[
                        const SizedBox(height: Spacing.s16),
                        Center(
                          child: TextButton.icon(
                            onPressed: () => context.go(kWelcomePath),
                            icon: const Icon(Icons.help_outline),
                            label: Text(l10n.whatIsWishlist),
                          ),
                        ),
                      ],
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

  /// What the server offers, progress while Google initialises or the server
  /// checks a sign-in, and why the last attempt failed.
  Widget _signIn(
    BuildContext context,
    AppLocalizations l10n,
    ClientConfig config,
  ) {
    final auth = context.watch<AuthController>();
    final failure = _googleFailed
        ? l10n.signInGoogleFailed
        : switch (auth.failure) {
            null => null,
            SignInFailure.rejected => l10n.signInRejected,
            SignInFailure.wrongCredentials => l10n.signInWrongCredentials,
            SignInFailure.tooManyAttempts => l10n.signInTooManyAttempts,
            SignInFailure.notConfigured => l10n.signInNotConfigured,
            SignInFailure.unreachable => l10n.serverUnreachable,
            SignInFailure.serverError => l10n.serverError,
          };
    final busy = auth.status == AuthStatus.signingIn;
    final hasGoogle = config.googleClientId != null;
    final toSignUp = Uri(
      path: kEmailSignUpPath,
      queryParameters: widget.from == null ? null : {'from': widget.from},
    ).toString();
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (busy || (hasGoogle && !_googleReady && !_googleFailed))
          const _Progress()
        else if (hasGoogle && !_googleReady)
          // Initialising failed: no button can work; the failure says so.
          const SizedBox.shrink()
        else if (hasGoogle && kIsWeb)
          Center(child: buildGoogleSignInButton(context))
        else if (hasGoogle)
          OutlinedButton.icon(
            onPressed: _authenticate,
            icon: const Icon(Icons.login),
            label: Text(l10n.signInWithGoogle),
          ),
        // The Apple button goes here (sign-in plan U5), under Google's. It
        // also joins Google in "not configured" and in the line about other
        // buttons below.
        if (config.emailSignIn) ...[
          if (hasGoogle) ...[
            const SizedBox(height: Spacing.s16),
            Row(
              children: [
                const Expanded(child: Divider()),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: Spacing.s8),
                  child: Text(l10n.signInOr),
                ),
                const Expanded(child: Divider()),
              ],
            ),
            const SizedBox(height: Spacing.s8),
            Text(
              l10n.signInOtherProviderHint,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: Spacing.s16),
          ] else if (busy)
            const SizedBox(height: Spacing.s16),
          // Keyed: the widgets above come and go, and the typed address and
          // password must not.
          EmailSignInForm(key: const ValueKey('email-sign-in'), busy: busy),
        ],
        if (failure != null) ...[
          const SizedBox(height: Spacing.s16),
          ErrorLine(failure),
        ],
        if (config.emailSignIn) ...[
          const SizedBox(height: Spacing.s8),
          TextButton(
            onPressed: () => context.go(toSignUp),
            child: Text(l10n.signInForgotPassword),
          ),
          TextButton(
            onPressed: () => context.go(toSignUp),
            child: Text(l10n.signInCreateWithEmail),
          ),
        ],
      ],
    );
  }
}

class _Progress extends StatelessWidget {
  const _Progress();

  @override
  Widget build(BuildContext context) =>
      const Center(child: CircularProgressIndicator());
}

/// `/api/config` could not be read: why, and a button to try again.
class _ConfigError extends StatelessWidget {
  const _ConfigError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ErrorLine(message),
        const SizedBox(height: Spacing.s16),
        OutlinedButton(
          onPressed: onRetry,
          child: Text(AppLocalizations.of(context).retry),
        ),
      ],
    );
  }
}
