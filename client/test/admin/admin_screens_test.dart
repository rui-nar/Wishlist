import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/admin/admin_user_screen.dart';
import 'package:wishlist/src/admin/admin_users_screen.dart';
import 'package:wishlist/src/app_router.dart';
import 'package:wishlist/src/auth/account_screen.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/auth/sign_in_screen.dart';

import '../support/fakes.dart';
import 'support/fake_admin.dart';

const _phone = Size(390, 844);
const _wide = Size(1440, 900);

void main() {
  late FakeServer server;
  late FakeAdmin admin;
  late MemoryTokenStore store;

  setUp(() {
    server = FakeServer();
    admin = FakeAdmin(server);
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
  });

  Future<AuthController> start(
    WidgetTester tester,
    String location, {
    Size size = _phone,
    Locale locale = const Locale('en'),
  }) async {
    tester.platformDispatcher.localesTestValue = [locale];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    tester.platformDispatcher.defaultRouteNameTestValue = location;
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  Iterable<String> adminCalls() =>
      server.calls.where((call) => call.contains('/api/admin'));

  String bobPath() => '/admin/users/$kBobId';

  group('who sees the panel', () {
    testWidgets('a non-admin opening /admin sees the not-found page',
        (tester) async {
      server.isAdmin = false;
      await start(tester, '/admin');

      expect(find.byType(NotFoundScreen), findsOneWidget);
      expect(find.text('Page not found'), findsOneWidget);
      expect(find.text('Admin panel'), findsNothing);
      expect(adminCalls(), isEmpty);
    });

    testWidgets('the same page as an address that does not exist',
        (tester) async {
      server.isAdmin = false;
      await start(tester, '/nowhere');
      expect(find.byType(NotFoundScreen), findsOneWidget);

      await tester.tap(find.text('Go to home'));
      await tester.pumpAndSettle();
      expect(find.byType(NotFoundScreen), findsNothing);
    });

    testWidgets('a non-admin opening an account page sees not found',
        (tester) async {
      server.isAdmin = false;
      await start(tester, bobPath());

      expect(find.byType(NotFoundScreen), findsOneWidget);
      expect(find.byType(AdminUserScreen), findsNothing);
      expect(adminCalls(), isEmpty);
    });

    testWidgets('the account screen shows the entry to the admin only',
        (tester) async {
      server.isAdmin = false;
      await start(tester, '/account');
      expect(find.byType(AccountScreen), findsOneWidget);
      expect(find.text('Admin panel'), findsNothing);
    });

    testWidgets('the admin reaches the panel from the account screen',
        (tester) async {
      await start(tester, '/account');

      await tester.tap(find.text('Admin panel'));
      await tester.pumpAndSettle();

      expect(find.byType(AdminUsersScreen), findsOneWidget);
      expect(find.text('bob@example.com'), findsOneWidget);
    });

    testWidgets('signed out, /admin goes to sign-in and back after it',
        (tester) async {
      store = MemoryTokenStore();
      final auth = await start(tester, '/admin');
      expect(find.byType(SignInScreen), findsOneWidget);

      await auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();

      expect(find.byType(AdminUsersScreen), findsOneWidget);
    });

    testWidgets('a 404 from the server shows the not-found page',
        (tester) async {
      server.status['GET /api/admin/users'] = 404;
      await start(tester, '/admin');

      expect(find.byType(NotFoundScreen), findsOneWidget);
    });
  });

  group('the users', () {
    testWidgets('on a phone, cards with the plan, counts and photo space',
        (tester) async {
      await start(tester, '/admin');

      expect(find.byType(DataTable), findsNothing);
      expect(find.text('bob@example.com'), findsOneWidget);
      expect(find.text('Bob Durand'), findsOneWidget);
      expect(find.text('Premium until Mar 12, 2027 · Stripe'), findsOneWidget);
      expect(find.text('2 lists · 3 photos · 1.5 MB'), findsOneWidget);
      expect(find.text('Created May 2, 2026 · Apple, Email and password'),
          findsOneWidget);
      // Carol's older photo is not measured yet.
      expect(find.text('1 list · 1 photo · measuring'), findsOneWidget);
      expect(find.text('No lists · No photos'), findsOneWidget);
    });

    testWidgets('on a wide screen, a table', (tester) async {
      await start(tester, '/admin', size: _wide);

      expect(find.byType(DataTable), findsOneWidget);
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('bob@example.com'), findsOneWidget);
      expect(find.text('3 photos · 1.5 MB'), findsOneWidget);
      expect(find.text('Premium until Mar 12, 2027 · Stripe'), findsOneWidget);

      await tester.tap(find.text('bob@example.com'));
      await tester.pumpAndSettle();
      expect(find.byType(AdminUserScreen), findsOneWidget);
    });

    testWidgets('in French, sizes read with a comma and French units',
        (tester) async {
      await start(tester, '/admin', locale: const Locale('fr'));

      expect(find.text('2 listes · 3 photos · 1,5 Mo'), findsOneWidget);
      expect(find.text('1 liste · 1 photo · mesure en cours'), findsOneWidget);
    });

    testWidgets('search sends the text, says when nothing matches, and clears',
        (tester) async {
      await start(tester, '/admin');

      await tester.enterText(find.byType(TextField), ' carol ');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();

      expect(admin.queries.last, {'q': 'carol'});
      expect(find.text('carol@example.com'), findsOneWidget);
      expect(find.text('bob@example.com'), findsNothing);

      await tester.enterText(find.byType(TextField), 'zed');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      expect(find.text('No address contains “zed”.'), findsOneWidget);

      await tester.tap(find.byTooltip('Clear search'));
      await tester.pumpAndSettle();
      expect(admin.queries.last, isEmpty);
      expect(find.text('bob@example.com'), findsOneWidget);
    });

    testWidgets('pages: show more adds the next accounts until the last',
        (tester) async {
      admin.pageSize = 2;
      await start(tester, '/admin');

      expect(find.text('alice@example.com'), findsNothing);
      await tester.ensureVisible(find.text('Show more'));
      await tester.tap(find.text('Show more'));
      await tester.pumpAndSettle();

      expect(admin.queries.last, {'cursor': '2'});
      expect(find.text('bob@example.com'), findsOneWidget);
      expect(find.text('alice@example.com'), findsOneWidget);
      expect(find.text('Show more'), findsNothing);
    });

    testWidgets('at 1440 wide every column shows without scrolling',
        (tester) async {
      // The longest a row gets: a long address, every way of signing in, a
      // grant, and photos in the gigabytes.
      admin.rows.insert(
        0,
        adminRow(
          id: '7b0c2f1e-0000-4000-8000-000000000009',
          email: 'a.very.long.address.for.someone@subdomain.example-company.com',
          displayName: 'Someone With A Long Name',
          signIn: const ['apple', 'email', 'google'],
          plan: const {
            'plan': 'premium',
            'source': 'manual',
            'until': '2027-12-28T12:00:00Z',
          },
          listsOwned: 120,
          photos: const {'count': 120, 'bytes': 1234567890, 'measuring': false},
        ),
      );
      await start(tester, '/admin', size: _wide);

      final scrollable = tester.state<ScrollableState>(find
          .ancestor(
            of: find.byType(DataTable),
            matching: find.byType(Scrollable),
          )
          .first);
      expect(scrollable.position.maxScrollExtent, 0);
      expect(find.text('Name'), findsNothing);
      final photos = tester.getRect(find.text('Photos'));
      expect(photos.right, lessThanOrEqualTo(_wide.width));
      expect(find.text('120 photos · 1.2 GB'), findsOneWidget);
      expect(find.text('Apple, Email, Google'), findsOneWidget);
      final address = tester.widget<Text>(find.text(
        'a.very.long.address.for.someone@subdomain.example-company.com',
      ));
      expect(address.overflow, TextOverflow.ellipsis);
    });

    testWidgets('a cursor the server refuses starts the list again',
        (tester) async {
      admin.pageSize = 2;
      await start(tester, '/admin');
      admin.refusals['GET /api/admin/users'] = (422, 'invalid_cursor');

      await tester.ensureVisible(find.text('Show more'));
      await tester.tap(find.text('Show more'));
      await tester.pump();
      admin.refusals.clear();
      await tester.pumpAndSettle();

      expect(admin.queries.last, isEmpty);
      expect(find.text('bob@example.com'), findsOneWidget);
    });

    testWidgets('a failed load offers to try again', (tester) async {
      server.status['GET /api/admin/users'] = 500;
      await start(tester, '/admin');
      expect(find.text('Try again'), findsOneWidget);

      server.status.remove('GET /api/admin/users');
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();
      expect(find.text('bob@example.com'), findsOneWidget);
    });

    testWidgets('no accounts', (tester) async {
      admin.rows.clear();
      await start(tester, '/admin');
      expect(find.text('No accounts yet.'), findsOneWidget);
    });
  });

  group('one account', () {
    testWidgets('its lists as counts, and its figures', (tester) async {
      await start(tester, bobPath());

      expect(find.text('bob@example.com'), findsOneWidget);
      expect(find.text('Premium until Mar 12, 2027 · Stripe'), findsOneWidget);
      expect(find.text('Birthday'), findsOneWidget);
      expect(find.text('Created May 3, 2026 · 4 gifts · 1 owner'),
          findsOneWidget);
      expect(find.text('Created Jun 1, 2026 · 12 gifts · 2 owners'),
          findsOneWidget);
    });

    testWidgets('on a wide screen, the lists in a table', (tester) async {
      await start(tester, bobPath(), size: _wide);

      expect(find.byType(DataTable), findsOneWidget);
      expect(find.text('Wedding'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
    });

    testWidgets('an account gone meanwhile says so', (tester) async {
      await start(tester, '/admin/users/unknown');

      expect(find.text('This account no longer exists.'), findsOneWidget);
      await tester.tap(find.text('Back to the admin panel'));
      await tester.pumpAndSettle();
      expect(find.byType(AdminUsersScreen), findsOneWidget);
    });

    testWidgets('granting Premium asks, a year ahead by default',
        (tester) async {
      await start(tester, '/admin/users/$kCarolId');

      await tester.tap(find.text('Grant Premium').first);
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      // Cancelled: nothing changes.
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(admin.bodies, isEmpty);

      await tester.tap(find.text('Grant Premium').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Grant'));
      await tester.pumpAndSettle();

      final today = DateTime.now();
      final inAYear = DateTime(today.year + 1, today.month, today.day);
      final day = '${inAYear.year}-'
          '${inAYear.month.toString().padLeft(2, '0')}-'
          '${inAYear.day.toString().padLeft(2, '0')}';
      expect(admin.bodies['POST /api/admin/users/$kCarolId/premium'], [
        {'period_end': day},
      ]);
      expect(find.textContaining('Premium granted until'), findsOneWidget);
      expect(find.textContaining('· granted here'), findsOneWidget);
      expect(find.text('Change the end date'), findsOneWidget);
      expect(find.text('End granted Premium'), findsOneWidget);
    });

    testWidgets('ending a grant asks, then reads the account again',
        (tester) async {
      admin.grants[kCarolId] = '2027-01-10T12:00:00Z';
      await start(tester, '/admin/users/$kCarolId');

      await tester.tap(find.text('End granted Premium'));
      await tester.pumpAndSettle();
      expect(find.text('End granted Premium?'), findsOneWidget);
      await tester.tap(find.text('End it'));
      await tester.pumpAndSettle();

      final calls = server.calls.where((c) => c.contains(kCarolId)).toList();
      expect(calls.sublist(calls.length - 2), [
        'DELETE /api/admin/users/$kCarolId/premium',
        'GET /api/admin/users/$kCarolId',
      ]);
      expect(find.text('Granted Premium ended.'), findsOneWidget);
      expect(find.text('End granted Premium'), findsNothing);
    });

    testWidgets('a grant already ended says so', (tester) async {
      admin.grants[kCarolId] = '2027-01-10T12:00:00Z';
      await start(tester, '/admin/users/$kCarolId');
      admin.grants.clear();

      await tester.tap(find.text('End granted Premium'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('End it'));
      await tester.pumpAndSettle();

      expect(find.text('There is no granted Premium to end.'), findsOneWidget);
      expect(find.text('End granted Premium'), findsNothing);
    });

    testWidgets('the admin sees no delete button on their own account',
        (tester) async {
      await start(tester, '/admin/users/${kAlice['id']}');

      expect(find.text('Delete this account'), findsNothing);
      expect(
        find.text('Delete your own account from your account screen.'),
        findsOneWidget,
      );
    });
  });

  group('deleting an account', () {
    TextButton deleteButton(WidgetTester tester) => tester.widget<TextButton>(
          find.widgetWithText(TextButton, 'Delete the account'),
        );

    testWidgets('waits for the address, then deletes and goes back',
        (tester) async {
      await start(tester, bobPath());

      await tester.tap(find.text('Delete this account'));
      await tester.pumpAndSettle();
      expect(deleteButton(tester).onPressed, isNull);

      await tester.enterText(find.byType(TextField), 'bob@example.co');
      await tester.pump();
      expect(deleteButton(tester).onPressed, isNull);

      // Case and surrounding spaces do not count, as on the server.
      await tester.enterText(find.byType(TextField), '  BOB@example.com ');
      await tester.pump();
      expect(deleteButton(tester).onPressed, isNotNull);

      await tester.tap(find.text('Delete the account'));
      await tester.pumpAndSettle();

      expect(admin.bodies['DELETE /api/admin/users/$kBobId'], [
        {'email': 'BOB@example.com'},
      ]);
      expect(find.text('Account deleted.'), findsOneWidget);
      expect(find.byType(AdminUsersScreen), findsOneWidget);
      expect(find.text('bob@example.com'), findsNothing);
    });

    testWidgets('cancelling deletes nothing', (tester) async {
      await start(tester, bobPath());

      await tester.tap(find.text('Delete this account'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(admin.bodies, isEmpty);
      expect(find.byType(AdminUserScreen), findsOneWidget);
    });

    Future<void> deleteBob(WidgetTester tester) async {
      await start(tester, bobPath());
      await tester.tap(find.text('Delete this account'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'bob@example.com');
      await tester.pump();
      await tester.tap(find.text('Delete the account'));
      await tester.pumpAndSettle();
    }

    testWidgets("the server's address check is still handled",
        (tester) async {
      admin.refusals['DELETE /api/admin/users/$kBobId'] =
          (422, 'email_mismatch');
      await deleteBob(tester);

      expect(find.text('The address does not match. Nothing was deleted.'),
          findsOneWidget);
      expect(find.byType(AdminUserScreen), findsOneWidget);
    });

    testWidgets('a subscription that cannot be stopped deletes nothing',
        (tester) async {
      admin.refusals['DELETE /api/admin/users/$kBobId'] =
          (409, 'billing_unavailable');
      await deleteBob(tester);

      expect(
        find.text('The subscription could not be stopped, so nothing was '
            'deleted. Try again later.'),
        findsOneWidget,
      );
      expect(find.byType(AdminUserScreen), findsOneWidget);
    });

    testWidgets('Stripe failing (502) says the same', (tester) async {
      admin.refusals['DELETE /api/admin/users/$kBobId'] =
          (502, 'billing_unavailable');
      await deleteBob(tester);

      expect(find.textContaining('could not be stopped'), findsOneWidget);
    });
  });

  group('a change on a session over 12 hours old', () {
    testWidgets('says to sign in again, then signs out to come back',
        (tester) async {
      admin.reauth = true;
      final auth = await start(tester, bobPath());

      await tester.tap(find.text('Grant Premium').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Grant'));
      await tester.pumpAndSettle();

      // Still signed in: the 401 is not a lost session.
      expect(auth.status, AuthStatus.signedIn);
      expect(find.text(
        'Changes in the admin panel need a sign-in from the last 12 hours. '
        'Sign in again, then make the change.',
      ), findsOneWidget);

      await tester.tap(find.widgetWithText(TextButton, 'Sign in again'));
      await tester.pumpAndSettle();

      expect(auth.status, AuthStatus.signedOut);
      expect(server.calls, contains('POST /api/auth/sign-out'));
      expect(store.token, isNull);
      final signIn = tester.widget<SignInScreen>(find.byType(SignInScreen));
      expect(signIn.from, '/admin');

      admin.reauth = false;
      await auth.signInWithGoogle(kValidIdToken);
      await tester.pumpAndSettle();
      expect(find.byType(AdminUsersScreen), findsOneWidget);
    });

    testWidgets('cancelled, the admin stays signed in on the page',
        (tester) async {
      admin.reauth = true;
      final auth = await start(tester, bobPath());

      await tester.tap(find.text('Delete this account'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'bob@example.com');
      await tester.pump();
      await tester.tap(find.text('Delete the account'));
      await tester.pumpAndSettle();
      expect(find.text('Sign in again'), findsNWidgets(2));

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(auth.status, AuthStatus.signedIn);
      expect(find.byType(AdminUserScreen), findsOneWidget);
      expect(admin.rows.map((row) => row['id']), contains(kBobId));
    });
  });
}
