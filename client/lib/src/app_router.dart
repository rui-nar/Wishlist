/// The app's routes and the sign-in guard (ACCOUNTS_PLAN D10).
library;

import 'package:go_router/go_router.dart';

import 'api/api_client.dart';
import 'auth/account_screen.dart';
import 'auth/auth_controller.dart';
import 'auth/sign_in_screen.dart';
import 'home/home_screen.dart';
import 'lists/common.dart';
import 'lists/gift_form_screen.dart';
import 'lists/list_detail_screen.dart';
import 'lists/list_form_screen.dart';
import 'version_screen.dart';

const kSignInPath = '/sign-in';

/// Where the guard sends a request for [uri], or null to let it through.
///
/// Signed out, every location but the sign-in screen goes to
/// `/sign-in?from=<location>`. Signed in, the sign-in screen goes to `from`
/// when [safeFrom] accepts it, `/` otherwise. A later plan's share links
/// (`/join`) rely on this return.
String? authRedirect(AuthStatus status, Uri uri) {
  // The start gate shows no route until the stored session is known.
  if (status == AuthStatus.restoring || status == AuthStatus.unavailable) {
    return null;
  }
  final onSignIn = uri.path == kSignInPath;
  if (status == AuthStatus.signedIn) {
    return onSignIn ? safeFrom(uri.queryParameters['from']) ?? '/' : null;
  }
  if (onSignIn) return null;
  final location = uri.toString();
  return Uri(
    path: kSignInPath,
    queryParameters: location == '/' ? null : {'from': location},
  ).toString();
}

/// [from] when it is a location inside the app: a path starting with one
/// `/`, with no scheme or host, so a crafted link cannot send the user to
/// another site after signing in. Browsers read `//host` and `/\host` as
/// another host, and drop tabs and line breaks, so those are refused too, as
/// is the sign-in screen itself.
String? safeFrom(String? from) {
  if (from == null || !from.startsWith('/') || from.startsWith('//')) {
    return null;
  }
  if (from.contains(r'\') || from.codeUnits.any((c) => c <= 0x20 || c == 0x7f)) {
    return null;
  }
  final uri = Uri.tryParse(from);
  if (uri == null || uri.hasScheme || uri.hasAuthority) return null;
  if (uri.path == kSignInPath) return null;
  return from;
}

/// The routes: sign-in, home with the lists and gifts under it, account and
/// the version screen (`/about`). The guard runs again whenever [auth]
/// changes, and covers every route but sign-in.
///
/// The lists' routes are under home, so a list opened from a link still has
/// My lists to go back to.
GoRouter buildRouter({
  required AuthController auth,
  required ApiClient api,
  required String appVersion,
}) {
  return GoRouter(
    refreshListenable: auth,
    observers: [listsRouteObserver],
    redirect: (context, state) => authRedirect(auth.status, state.uri),
    routes: [
      GoRoute(
        path: kSignInPath,
        builder: (context, state) => const SignInScreen(),
      ),
      GoRoute(
        path: '/',
        builder: (context, state) => const HomeScreen(),
        routes: [
          // Before lists/:id, which would take "new" for an id.
          GoRoute(
            path: 'lists/new',
            builder: (context, state) => const ListFormScreen(),
          ),
          GoRoute(
            path: 'lists/:id',
            builder: (context, state) =>
                ListDetailScreen(listId: state.pathParameters['id']!),
            routes: [
              GoRoute(
                path: 'edit',
                builder: (context, state) =>
                    ListFormScreen(listId: state.pathParameters['id']),
              ),
              GoRoute(
                path: 'gifts/new',
                builder: (context, state) =>
                    GiftFormScreen(listId: state.pathParameters['id']!),
              ),
              GoRoute(
                path: 'gifts/:giftId/edit',
                builder: (context, state) => GiftFormScreen(
                  listId: state.pathParameters['id']!,
                  giftId: state.pathParameters['giftId'],
                ),
              ),
            ],
          ),
        ],
      ),
      GoRoute(
        path: '/account',
        builder: (context, state) => const AccountScreen(),
      ),
      GoRoute(
        path: '/about',
        builder: (context, state) => VersionScreen(
          httpClient: api.httpClient,
          apiBaseUrl: api.baseUrl,
          appVersion: appVersion,
        ),
      ),
    ],
  );
}
