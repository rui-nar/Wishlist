import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import 'l10n/app_localizations.dart';
import 'src/api/api_client.dart';
import 'src/app_router.dart';
import 'src/auth/auth_controller.dart';
import 'src/auth/start_gate.dart';
import 'src/auth/token_store.dart';
import 'src/config.dart';
import 'src/design/theme.dart';

void main() {
  // /account, not /#/account: the server answers every client path with the
  // web app (its catch-all).
  if (kIsWeb) usePathUrlStrategy();
  WidgetsFlutterBinding.ensureInitialized();
  LicenseRegistry.addLicense(_fontLicenses);
  final api = ApiClient(http.Client(), baseUrl: kApiBaseUrl);
  final auth = AuthController(api: api, store: TokenStore.forPlatform());
  unawaited(auth.restore());
  runApp(WishlistApp(api: api, auth: auth));
}

class WishlistApp extends StatefulWidget {
  const WishlistApp({
    super.key,
    required this.api,
    required this.auth,
    this.appVersion = kAppVersion,
  });

  // Injectable so tests can give the client a MockClient
  // (package:http/testing.dart) and the controller an in-memory store.
  final ApiClient api;
  final AuthController auth;
  final String appVersion;

  @override
  State<WishlistApp> createState() => _WishlistAppState();
}

class _WishlistAppState extends State<WishlistApp> {
  late final GoRouter _router = buildRouter(
    auth: widget.auth,
    api: widget.api,
    appVersion: widget.appVersion,
  );

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: widget.api),
        ChangeNotifierProvider<AuthController>.value(value: widget.auth),
      ],
      child: MaterialApp.router(
        onGenerateTitle: (context) => AppLocalizations.of(context).appTitle,
        // The device's language when it is English or French (D8). Otherwise
        // English, the first supported locale (l10n.yaml).
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: buildLightTheme(),
        darkTheme: buildDarkTheme(),
        themeMode: ThemeMode.system,
        routerConfig: _router,
        builder: (context, child) => StartGate(child: child!),
      ),
    );
  }
}

/// The SIL Open Font License texts of the bundled fonts, shown on the
/// licences page.
Stream<LicenseEntry> _fontLicenses() async* {
  for (final (family, path) in [
    ('Inter', 'assets/fonts/inter/OFL.txt'),
    ('Space Grotesk', 'assets/fonts/space_grotesk/OFL.txt'),
  ]) {
    yield LicenseEntryWithLineBreaks(
      [family],
      await rootBundle.loadString(path),
    );
  }
}
