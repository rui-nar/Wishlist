/// Stand-ins for the server, the token store and Google, shared by the tests.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:google_sign_in_platform_interface/google_sign_in_platform_interface.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/l10n/app_localizations.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/google_sign_in_init.dart';
import 'package:wishlist/src/auth/token_store.dart';
import 'package:wishlist/src/design/theme.dart';

const kApiBase = 'http://api.test';

/// The ID token [FakeServer] accepts.
const kValidIdToken = 'valid-google-id-token';

const kAlice = {
  'id': '7b0c2f1e-0000-4000-8000-000000000001',
  'email': 'alice@example.com',
  'display_name': 'Alice Martin',
};

/// The unsubscribe token [FakeServer] accepts.
const kUnsubscribeToken = 'v1.dXNlcg.c2lnbmF0dXJl';

/// `GET /api/billing` (PREMIUM_PLAN D11); by default the unset state: free,
/// nothing on sale and no limit applied.
Map<String, Object?> billingStatus({
  String plan = 'free',
  String? status,
  String? renewsAt,
  String? endsAt,
  Map<String, Object?>? limits = const {
    'max_lists': 1,
    'max_gifts_per_list': 20,
  },
  bool enforced = false,
  Map<String, Object?>? offer,
  bool canManage = false,
  Map<String, Object?> legal = const {
    'terms_url': null,
    'privacy_url': null,
    'withdrawal_url': null,
  },
}) =>
    {
      'plan': plan,
      'source': plan == 'premium' ? 'stripe' : null,
      'status': status,
      'renews_at': renewsAt,
      'ends_at': endsAt,
      'limits': limits,
      'enforced': enforced,
      'offer': offer,
      'can_manage': canManage,
      'legal': legal,
    };

/// The offer of a server that is selling, as in `GET /api/billing`.
const kBillingOffer = {'amount': '49.00', 'currency': 'EUR', 'interval': 'year'};

/// The server's account endpoints (ACCOUNTS_PLAN D7), preferences and
/// unsubscribing (COMMENTS_NOTIFICATIONS_PLAN D18), billing (PREMIUM_PLAN
/// D11) and `/api/version`, in memory. [status] forces an answer for
/// `'<METHOD> <path>'`.
class FakeServer {
  FakeServer({this.googleClientId = 'test-client-id', this.publicBaseUrl});

  String? googleClientId;

  /// Where share links start; none by default, as in DEV.
  String? publicBaseUrl;

  /// Session token → user.
  final sessions = <String, Map<String, String>>{};
  final status = <String, int>{};

  /// Every request, as `'<METHOD> <path>'`.
  final calls = <String>[];
  bool deleted = false;

  /// Alice's `email_notifications` and `language`.
  final preferences = <String, Object>{
    'email_notifications': true,
    'language': 'en',
  };

  /// The body of every `PATCH /api/me/preferences`, oldest first.
  final preferencePatches = <Map<String, dynamic>>[];

  /// The `Authorization` header of every unsubscribe call that reached the
  /// server, null when it had none.
  final unsubscribeSessions = <String?>[];

  /// What `GET /api/billing` answers.
  Map<String, Object?> billing = billingStatus();
  String checkoutUrl = 'https://checkout.stripe.test/session';
  String portalUrl = 'https://billing.stripe.test/session';
  int _next = 0;

  late final http.Client client = MockClient(_handle);

  /// A session for Alice, as if she had signed in earlier.
  String addSession() {
    final token = 'session-${_next++}';
    sessions[token] = kAlice;
    return token;
  }

  Future<http.Response> _handle(http.Request request) async {
    final call = '${request.method} ${request.url.path}';
    calls.add(call);
    final forced = status[call];
    if (forced != null) return http.Response('', forced);
    final auth = request.headers['Authorization'];
    final token = auth != null && auth.startsWith('Bearer ')
        ? auth.substring('Bearer '.length)
        : null;
    final user = sessions[token];
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);
    final unauthorized = http.Response('{"detail":"Not authenticated"}', 401);
    if (request.method == 'POST' &&
        request.url.path.startsWith('/api/unsubscribe/')) {
      unsubscribeSessions.add(auth);
      final valid = request.url.pathSegments.last == kUnsubscribeToken;
      if (valid) preferences['email_notifications'] = false;
      return http.Response('', valid ? 204 : 404);
    }
    switch (call) {
      case 'GET /api/config':
        return json({
          'google_client_id': googleClientId,
          'public_base_url': publicBaseUrl,
        });
      case 'GET /api/version':
        return json({'version': 'v1.2.0', 'env': 'validation'});
      case 'POST /api/auth/google':
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        if (body['id_token'] != kValidIdToken) return unauthorized;
        final token = addSession();
        return json({'token': token, 'user': kAlice});
      case 'POST /api/auth/sign-out':
        if (user == null) return unauthorized;
        sessions.remove(token);
        return http.Response('', 204);
      case 'GET /api/me':
        return user == null ? unauthorized : json(user);
      case 'DELETE /api/me':
        if (user == null) return unauthorized;
        sessions.clear();
        deleted = true;
        return http.Response('', 204);
      case 'GET /api/me/preferences':
        return user == null ? unauthorized : json(preferences);
      case 'PATCH /api/me/preferences':
        if (user == null) return unauthorized;
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        preferencePatches.add(body);
        final language = body['language'];
        if (language != null && language != 'en' && language != 'fr') {
          return http.Response('', 422);
        }
        preferences.addAll(body.cast<String, Object>());
        return json(preferences);
      case 'GET /api/billing':
        return user == null ? unauthorized : json(billing);
      case 'POST /api/billing/checkout':
        return user == null ? unauthorized : json({'url': checkoutUrl});
      case 'POST /api/billing/portal':
        return user == null ? unauthorized : json({'url': portalUrl});
    }
    // Any later endpoint depends on current_user (D5).
    return user == null ? unauthorized : http.Response('', 404);
  }
}

/// A [TokenStore] in memory.
class MemoryTokenStore implements TokenStore {
  MemoryTokenStore([this.token]);

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String token) async => this.token = token;

  @override
  Future<void> clear() async => token = null;
}

/// Google's platform implementation: records init(), and lets a test sign in
/// as the web button or authenticate() would, by emitting an event.
class FakeGoogleSignIn extends GoogleSignInPlatform {
  final initCalls = <InitParameters>[];
  int authenticateCalls = 0;

  /// Set to make init() fail.
  Object? initError;

  final _events = StreamController<AuthenticationEvent>.broadcast();

  @override
  Future<void> init(InitParameters params) async {
    initCalls.add(params);
    if (initError != null) throw initError!;
  }

  @override
  Stream<AuthenticationEvent>? get authenticationEvents => _events.stream;

  @override
  bool supportsAuthenticate() => true;

  @override
  Future<AuthenticationResults> authenticate(
    AuthenticateParameters params,
  ) async {
    authenticateCalls++;
    final results = signInResults(kValidIdToken);
    _events.add(AuthenticationEventSignIn(
      user: results.user,
      authenticationTokens: results.authenticationTokens,
    ));
    return results;
  }

  /// Google signs the user in with [idToken].
  void signIn(String idToken) {
    final results = signInResults(idToken);
    _events.add(AuthenticationEventSignIn(
      user: results.user,
      authenticationTokens: results.authenticationTokens,
    ));
  }

  /// Google's flow fails.
  void fail() => _events.add(AuthenticationEventException(
        const GoogleSignInException(code: GoogleSignInExceptionCode.unknownError),
      ));

  static AuthenticationResults signInResults(String idToken) =>
      AuthenticationResults(
        user: const GoogleSignInUserData(email: 'alice@example.com', id: 'g1'),
        authenticationTokens: AuthenticationTokenData(idToken: idToken),
      );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Installs a fresh [FakeGoogleSignIn], uninitialised.
FakeGoogleSignIn installFakeGoogleSignIn() {
  resetGoogleSignInInitialized();
  final fake = FakeGoogleSignIn();
  GoogleSignInPlatform.instance = fake;
  return fake;
}

/// The app against [server], with [store] holding the device's token.
({ApiClient api, AuthController auth, Widget app}) buildApp(
  FakeServer server, {
  MemoryTokenStore? store,
}) {
  final api = ApiClient(server.client, baseUrl: kApiBase);
  final auth = AuthController(api: api, store: store ?? MemoryTokenStore());
  return (
    api: api,
    auth: auth,
    app: WishlistApp(api: api, auth: auth, appVersion: 'v1.2.3'),
  );
}

/// [home] in a MaterialApp themed and localised as the app is.
Widget localizedApp(Widget home) => MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: ThemeMode.system,
      home: home,
    );
