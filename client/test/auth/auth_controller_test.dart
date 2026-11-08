import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';

import '../support/fakes.dart';

void main() {
  late FakeServer server;
  late ApiClient api;

  setUp(() {
    server = FakeServer();
    api = ApiClient(server.client, baseUrl: kApiBase);
  });

  AuthController controller(MemoryTokenStore store) =>
      AuthController(api: api, store: store);

  group('restore', () {
    test('no stored token: signed out, without asking the server', () async {
      final auth = controller(MemoryTokenStore());
      expect(auth.status, AuthStatus.restoring);

      await auth.restore();

      expect(auth.status, AuthStatus.signedOut);
      expect(auth.user, isNull);
      expect(server.calls, isEmpty);
    });

    test('a valid token: signed in as the user /api/me names', () async {
      final store = MemoryTokenStore(server.addSession());
      final auth = controller(store);

      await auth.restore();

      expect(auth.status, AuthStatus.signedIn);
      expect(auth.user!.displayName, 'Alice Martin');
      expect(auth.user!.email, 'alice@example.com');
      expect(store.token, isNotNull);
    });

    test('an expired or revoked token (401): signed out, the store cleared',
        () async {
      final store = MemoryTokenStore('expired');
      final auth = controller(store);

      await auth.restore();

      expect(auth.status, AuthStatus.signedOut);
      expect(store.token, isNull);
      expect(api.token, isNull);
    });

    test('a server error keeps the token and can be retried (review R3-1)',
        () async {
      final token = server.addSession();
      final store = MemoryTokenStore(token);
      final auth = controller(store);
      server.status['GET /api/me'] = 500;

      await auth.restore();

      expect(auth.status, AuthStatus.unavailable);
      expect(store.token, token);

      server.status.remove('GET /api/me');
      await auth.restore();
      expect(auth.status, AuthStatus.signedIn);
    });

    test('an unreachable server keeps the token', () async {
      final store = MemoryTokenStore('kept');
      final auth = AuthController(
        api: ApiClient(
          MockClient((request) async {
            throw http.ClientException('refused', request.url);
          }),
          baseUrl: kApiBase,
        ),
        store: store,
      );

      await auth.restore();

      expect(auth.status, AuthStatus.unavailable);
      expect(store.token, 'kept');
    });
  });

  group('sign in', () {
    test('success: signed in, the token stored and sent from then on',
        () async {
      final store = MemoryTokenStore();
      final auth = controller(store)..restore();
      await pumpEventQueue();

      final statuses = <AuthStatus>[];
      auth.addListener(() => statuses.add(auth.status));
      await auth.signInWithGoogle(kValidIdToken);

      expect(statuses, [AuthStatus.signingIn, AuthStatus.signedIn]);
      expect(auth.user!.name, 'Alice Martin');
      expect(store.token, isNotNull);
      expect(server.sessions.keys, [store.token]);
      expect(api.token, store.token);
    });

    test('refused by the server (401): failed, rejected, nothing stored',
        () async {
      final store = MemoryTokenStore();
      final auth = controller(store);
      await auth.restore();

      await auth.signInWithGoogle('forged');

      expect(auth.status, AuthStatus.failed);
      expect(auth.failure, SignInFailure.rejected);
      expect(auth.user, isNull);
      expect(store.token, isNull);
    });

    test('503: failed, not configured; 500: failed, server error', () async {
      final auth = controller(MemoryTokenStore());
      await auth.restore();

      server.status['POST /api/auth/google'] = 503;
      await auth.signInWithGoogle(kValidIdToken);
      expect(auth.failure, SignInFailure.notConfigured);

      server.status['POST /api/auth/google'] = 500;
      await auth.signInWithGoogle(kValidIdToken);
      expect(auth.failure, SignInFailure.serverError);

      server.status.remove('POST /api/auth/google');
      await auth.signInWithGoogle(kValidIdToken);
      expect(auth.status, AuthStatus.signedIn);
      expect(auth.failure, isNull);
    });
  });

  test('sign-out ends the server session and clears the store', () async {
    final token = server.addSession();
    final store = MemoryTokenStore(token);
    final auth = controller(store);
    await auth.restore();

    await auth.signOut();

    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
    expect(api.token, isNull);
    expect(server.sessions, isEmpty);
    expect(server.calls.last, 'POST /api/auth/sign-out');
  });

  test('sign-out signs out here even when the server fails', () async {
    final store = MemoryTokenStore(server.addSession());
    final auth = controller(store);
    await auth.restore();
    server.status['POST /api/auth/sign-out'] = 500;

    await auth.signOut();

    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
  });

  test('deleting the account clears the store', () async {
    final store = MemoryTokenStore(server.addSession());
    final auth = controller(store);
    await auth.restore();

    await auth.deleteAccount();

    expect(server.deleted, isTrue);
    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
  });

  test('a failed deletion keeps the user signed in and says so', () async {
    final token = server.addSession();
    final store = MemoryTokenStore(token);
    final auth = controller(store);
    await auth.restore();
    server.status['DELETE /api/me'] = 500;

    await expectLater(auth.deleteAccount(), throwsA(isA<ApiException>()));

    expect(auth.status, AuthStatus.signedIn);
    expect(store.token, token);
  });

  test('a 401 on any call signs out', () async {
    final store = MemoryTokenStore(server.addSession());
    final auth = controller(store);
    await auth.restore();
    // Revoked elsewhere: another device deleted the account.
    server.sessions.clear();

    await expectLater(
      api.getJson('/api/anything-later'),
      throwsA(isA<UnauthorizedException>()),
    );
    await pumpEventQueue();

    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
  });

  test("a late 401 to an older session's call does not end the new one",
      () async {
    final store = MemoryTokenStore(server.addSession());
    final auth = controller(store);
    await auth.restore();

    api.onUnauthorized!('a-previous-token');
    await pumpEventQueue();

    expect(auth.status, AuthStatus.signedIn);
    expect(store.token, isNotNull);
  });
}
