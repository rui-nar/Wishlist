/// The app's routes and the sign-in guard (ACCOUNTS_PLAN D10).
library;

import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'auth/account_screen.dart';
import 'auth/auth_controller.dart';
import 'auth/sign_in_screen.dart';
import 'home/home_screen.dart';
import 'lists/common.dart';
import 'lists/gift_form_screen.dart';
import 'lists/list_detail_screen.dart';
import 'lists/list_form_screen.dart';
import 'lists/occasion_form_screen.dart';
import 'lists/occasion_members_screen.dart';
import 'shared/join_screen.dart';
import 'legal/legal_placeholder_screen.dart';
import 'shared/occasion_screen.dart';
import 'shared/pending_join.dart';
import 'unsubscribe/unsubscribe_screen.dart';
import 'version_screen.dart';
import 'welcome/welcome_screen.dart';

const kSignInPath = '/sign-in';
const kWelcomePath = '/welcome';
const kAboutPath = '/about';

/// The sign-in screen's `mode` that opens it to create an account
/// (WEB_LAYOUT_PLAN D7). Any other value is the normal sign-in.
const kRegisterMode = 'register';

/// Locations shown signed out as well as signed in: they show no user data
/// (WEB_LAYOUT_PLAN D6, review R1-1). The unsubscribe link has to work without
/// a session (COMMENTS_NOTIFICATIONS_PLAN D18).
const _publicPaths = {
  kWelcomePath,
  kAboutPath,
  kUnsubscribePath,
  kLegalTermsPath,
  kLegalPrivacyPath,
  kLegalWithdrawalPath,
};

/// Where the guard sends a request for [uri], or null to let it through.
///
/// Signed out, `/` goes to the welcome page whatever its query, the welcome
/// page, the sign-in screen, the version screen and the unsubscribe page
/// pass, and every other
/// location goes to `/sign-in?from=<location>` (WEB_LAYOUT_PLAN D6). Signed in, the welcome
/// page goes to `/`, and the sign-in screen goes to `from`
/// when [safeFrom] accepts it, `/` otherwise. Share links (`/join`) rely on
/// this return; their token waits in [PendingJoin], not in the location, so
/// a `from` of `/join` with no token pending ([joinPending] false) goes to
/// `/` too. That is the browser going back to the sign-in entry after the
/// join used the token, which would otherwise say the link is no longer
/// valid (review R6-1).
String? authRedirect(AuthStatus status, Uri uri, {required bool joinPending}) {
  // The start gate shows no route until the stored session is known.
  if (status == AuthStatus.restoring || status == AuthStatus.unavailable) {
    return null;
  }
  final onSignIn = uri.path == kSignInPath;
  if (status == AuthStatus.signedIn) {
    if (uri.path == kWelcomePath) return '/';
    if (!onSignIn) return null;
    final from = safeFrom(uri.queryParameters['from']);
    if (from == null) return '/';
    if (!joinPending && Uri.parse(from).path == kJoinPath) return '/';
    return from;
  }
  if (onSignIn || _publicPaths.contains(uri.path)) return null;
  // No route under `/` reads a query, so a home link with one (`?fbclid=…`)
  // is still home (review R2-2).
  if (uri.path == '/') return kWelcomePath;
  final location = uri.toString();
  return Uri(path: kSignInPath, queryParameters: {'from': location})
      .toString();
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

/// A giver's hidden-gift forms (HIDDEN_GIFTS_PLAN D14), under the occasion
/// page at [location]: both the one under Shared with me and the one under a
/// list for someone else.
List<RouteBase> _hiddenGiftRoutes(String Function(GoRouterState) location) => [
      GoRoute(
        path: 'hidden/new',
        builder: (context, state) => GiftFormScreen.hidden(
          occasionId: state.pathParameters['occasionId']!,
          occasionLocation: location(state),
        ),
      ),
      GoRoute(
        path: 'hidden/:giftId/edit',
        builder: (context, state) => GiftFormScreen.hidden(
          occasionId: state.pathParameters['occasionId']!,
          occasionLocation: location(state),
          giftId: state.pathParameters['giftId'],
        ),
      ),
    ];

/// The routes: the welcome page, sign-in, home with the lists, gifts and occasions under it,
/// Shared with me with the shared occasions under it, joining by link,
/// account, the version screen (`/about`) and the unsubscribe page. The guard
/// runs again whenever [auth] changes, and covers every route but the public
/// ones: sign-in, the welcome page, the version screen and the unsubscribe
/// page.
///
/// The lists' routes are under home and the shared occasions under Shared
/// with me, so one opened from a link still has its destination to go back
/// to. The two destinations switch without a transition, as tabs do.
GoRouter buildRouter({
  required AuthController auth,
  required ApiClient api,
  required String appVersion,
}) {
  // From the live address, before the router exists: the path URL strategy
  // never hands the link's fragment to the router, and the router's first
  // report rewrites the address without it (COMMENTS_NOTIFICATIONS_PLAN D18).
  final unsubscribeToken = unsubscribeTokenFrom(Uri.base);
  return GoRouter(
    refreshListenable: auth,
    observers: [listsRouteObserver],
    redirect: (context, state) => authRedirect(
      auth.status,
      state.uri,
      joinPending: context.read<PendingJoin>().token != null,
    ),
    routes: [
      GoRoute(
        path: kWelcomePath,
        builder: (context, state) => const WelcomeScreen(),
      ),
      GoRoute(
        path: kSignInPath,
        builder: (context, state) => SignInScreen(
          register: state.uri.queryParameters['mode'] == kRegisterMode,
          // Someone arriving from a share link or a deep link is mid-flow.
          offerWelcome: !state.uri.queryParameters.containsKey('from'),
        ),
      ),
      GoRoute(
        path: '/',
        pageBuilder: (context, state) => NoTransitionPage(
          key: state.pageKey,
          child: const HomeScreen(),
        ),
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
              GoRoute(
                path: 'occasions/new',
                builder: (context, state) =>
                    OccasionFormScreen(listId: state.pathParameters['id']!),
              ),
              // The occasion's gifts and their activity, for an owner who
              // gives (RESERVING_PLAN D14); after occasions/new.
              GoRoute(
                path: 'occasions/:occasionId',
                builder: (context, state) => OccasionScreen(
                  occasionId: state.pathParameters['occasionId']!,
                  listId: state.pathParameters['id'],
                  giftId: state.uri.queryParameters['gift'],
                ),
                routes: _hiddenGiftRoutes(
                  (state) => '/lists/${Uri.encodeComponent(state.pathParameters['id']!)}'
                      '/occasions/${Uri.encodeComponent(state.pathParameters['occasionId']!)}',
                ),
              ),
              GoRoute(
                path: 'occasions/:occasionId/edit',
                builder: (context, state) => OccasionFormScreen(
                  listId: state.pathParameters['id']!,
                  occasionId: state.pathParameters['occasionId'],
                ),
              ),
              GoRoute(
                path: 'occasions/:occasionId/members',
                builder: (context, state) => OccasionMembersScreen(
                  listId: state.pathParameters['id']!,
                  occasionId: state.pathParameters['occasionId']!,
                ),
              ),
            ],
          ),
        ],
      ),
      GoRoute(
        path: '/shared',
        pageBuilder: (context, state) => NoTransitionPage(
          key: state.pageKey,
          child: const HomeScreen(destination: HomeDestination.sharedWithMe),
        ),
        routes: [
          GoRoute(
            path: ':occasionId',
            builder: (context, state) => OccasionScreen(
              occasionId: state.pathParameters['occasionId']!,
              giftId: state.uri.queryParameters['gift'],
            ),
            routes: _hiddenGiftRoutes(
              (state) =>
                  '/shared/${Uri.encodeComponent(state.pathParameters['occasionId']!)}',
            ),
          ),
        ],
      ),
      GoRoute(
        path: kJoinPath,
        builder: (context, state) => const JoinScreen(),
      ),
      GoRoute(
        path: '/account',
        builder: (context, state) => const AccountScreen(),
      ),
      GoRoute(
        path: kAboutPath,
        builder: (context, state) => VersionScreen(
          httpClient: api.httpClient,
          apiBaseUrl: api.baseUrl,
          appVersion: appVersion,
        ),
      ),
      GoRoute(
        path: kUnsubscribePath,
        builder: (context, state) => UnsubscribeScreen(
          token: unsubscribeTokenFrom(state.uri) ?? unsubscribeToken,
        ),
      ),
      GoRoute(
        path: kLegalTermsPath,
        builder: (context, state) =>
            const LegalPlaceholderScreen(document: LegalDocument.terms),
      ),
      GoRoute(
        path: kLegalPrivacyPath,
        builder: (context, state) =>
            const LegalPlaceholderScreen(document: LegalDocument.privacy),
      ),
      GoRoute(
        path: kLegalWithdrawalPath,
        builder: (context, state) =>
            const LegalPlaceholderScreen(document: LegalDocument.withdrawal),
      ),
    ],
  );
}
