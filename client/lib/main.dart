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
import 'src/auth/email_link.dart';
import 'src/auth/language_report.dart';
import 'src/auth/start_gate.dart';
import 'src/auth/token_store.dart';
import 'src/billing/billing_repository.dart';
import 'src/billing/store.dart';
import 'src/billing/store_purchases.dart';
import 'src/config.dart';
import 'src/design/theme.dart';
import 'src/shared/pending_join.dart';

void main() {
  // /account, not /#/account: the server answers every client path with the
  // web app (its catch-all).
  if (kIsWeb) usePathUrlStrategy();
  WidgetsFlutterBinding.ensureInitialized();
  LicenseRegistry.addLicense(_fontLicenses);
  final api = ApiClient(http.Client(), baseUrl: kApiBaseUrl);
  final auth = AuthController(api: api, store: TokenStore.forPlatform());
  // From the live address, before the router exists: the path URL strategy
  // never hands the link's fragment to the router, and the sign-in redirect
  // would drop it (LISTS_GIFTS_SHARING_PLAN D5, review R3-1).
  final joinBrowser = JoinBrowser.forPlatform();
  final pendingJoin = PendingJoin.capture(Uri.base, joinBrowser);
  // The same for a mailed link: read here, and off the address bar at once.
  final emailLinkToken = captureEmailLinkToken(Uri.base, joinBrowser);
  unawaited(auth.restore());
  runApp(WishlistApp(
    api: api,
    auth: auth,
    pendingJoin: pendingJoin,
    emailLinkToken: emailLinkToken,
  ));
}

class WishlistApp extends StatefulWidget {
  const WishlistApp({
    super.key,
    required this.api,
    required this.auth,
    this.appVersion = kAppVersion,
    this.pendingJoin,
    this.emailLinkToken,
  });

  // Injectable so tests can give the client a MockClient
  // (package:http/testing.dart) and the controller an in-memory store.
  final ApiClient api;
  final AuthController auth;
  final String appVersion;

  /// The occasion link the app was opened with; none when null.
  final PendingJoin? pendingJoin;

  /// The token of the mailed link the app was opened with; none when null.
  final String? emailLinkToken;

  @override
  State<WishlistApp> createState() => _WishlistAppState();
}

class _WishlistAppState extends State<WishlistApp> {
  late final PendingJoin _pendingJoin =
      widget.pendingJoin ?? PendingJoin(MemoryJoinBrowser());
  late final GoRouter _router = buildRouter(
    auth: widget.auth,
    api: widget.api,
    appVersion: widget.appVersion,
    emailLinkToken: widget.emailLinkToken,
  );

  /// The phone store's purchases (Apple IAP plan D3), listened to while
  /// someone is signed in, whatever page is shown. Null without a store: on
  /// the web, and on Android until its store is sold through.
  StorePurchases? _purchases;

  @override
  void initState() {
    super.initState();
    if (deviceStore case final store?) {
      _purchases = StorePurchases(
        store: store,
        report: BillingRepository(widget.api).reportAppleTransaction,
      );
      widget.auth.addListener(_followSession);
      _followSession();
    }
  }

  void _followSession() {
    if (widget.auth.isSignedIn) {
      _purchases!.start();
    } else {
      _purchases!.stop();
    }
  }

  @override
  void dispose() {
    if (_purchases case final purchases?) {
      widget.auth.removeListener(_followSession);
      purchases.dispose();
    }
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: widget.api),
        ChangeNotifierProvider<AuthController>.value(value: widget.auth),
        Provider<PendingJoin>.value(value: _pendingJoin),
        Provider<StorePurchases?>.value(value: _purchases),
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
        builder: (context, child) =>
            LanguageReport(child: StartGate(child: child!)),
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
