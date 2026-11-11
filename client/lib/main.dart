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
import 'src/shared/app_links.dart';
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
  runApp(ShushGiftApp(
    api: api,
    auth: auth,
    pendingJoin: pendingJoin,
    emailLinkToken: emailLinkToken,
    // Android and iOS: links open the app (Shush Gift plan D7). The web reads
    // its address above, and its history comes back through the router.
    openAppLinks: !kIsWeb,
  ));
}

class ShushGiftApp extends StatefulWidget {
  const ShushGiftApp({
    super.key,
    required this.api,
    required this.auth,
    this.appVersion = kAppVersion,
    this.pendingJoin,
    this.emailLinkToken,
    this.openAppLinks = false,
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

  /// Whether the links the platform opens the app with go through
  /// [AppLinkReceiver]: at start, the platform's initial route, and while it
  /// runs, every pushed one. On Android and iOS, not on the web, whose
  /// browser pushes its history the same way.
  final bool openAppLinks;

  @override
  State<ShushGiftApp> createState() => _ShushGiftAppState();
}

class _ShushGiftAppState extends State<ShushGiftApp> {
  late final PendingJoin _pendingJoin =
      widget.pendingJoin ?? PendingJoin(MemoryJoinBrowser());
  late String? _emailLinkToken = widget.emailLinkToken;
  AppLinkReceiver? _appLinks;
  int _linksOpened = 0;
  String? _initialLocation;
  late final GoRouter _router = buildRouter(
    auth: widget.auth,
    api: widget.api,
    appVersion: widget.appVersion,
    emailLinkToken: () => _emailLinkToken,
    initialLocation: _initialLocation,
  );

  /// The phone store's purchases (Apple IAP plan D3, Android release plan
  /// D6), listened to while someone is signed in, whatever page is shown.
  /// Null without a store, as on the web.
  StorePurchases? _purchases;

  @override
  void initState() {
    super.initState();
    if (widget.openAppLinks) {
      _initialLocation = _receiveLink(
        Uri.parse(WidgetsBinding.instance.platformDispatcher.defaultRouteName),
      );
      // Before the router's own listener, which the first build adds. Each
      // link has its own extra, so one for the page already shown builds it
      // again, for its own token: the router ignores a go() to the same
      // location with the same extra.
      _appLinks = AppLinkReceiver(
        (link) => _router.go(_receiveLink(link), extra: ++_linksOpened),
      );
      WidgetsBinding.instance.addObserver(_appLinks!);
    }
    if (deviceStore case final store?) {
      _purchases = StorePurchases(
        store: store,
        report: BillingRepository(widget.api).reporterFor(store),
      );
      widget.auth.addListener(_followSession);
      _followSession();
    }
  }

  /// Keeps the tokens [link] carries, as the web does from its address, and
  /// gives the location to open.
  String _receiveLink(Uri link) {
    _pendingJoin.receive(link);
    _emailLinkToken = emailLinkTokenFrom(link) ?? _emailLinkToken;
    return appLocationOf(link);
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
    if (_appLinks case final appLinks?) {
      WidgetsBinding.instance.removeObserver(appLinks);
    }
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
