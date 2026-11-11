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

    test('email sign-in: the session, stored', () async {
      final store = MemoryTokenStore();
      final auth = controller(store);
      await auth.restore();

      await auth.signInWithEmail('alice@example.com', kEmailPassword);

      expect(auth.status, AuthStatus.signedIn);
      expect(store.token, isNotNull);
      expect(server.emailBodies['POST /api/auth/email/sign-in'], {
        'email': 'alice@example.com',
        'password': kEmailPassword,
      });
    });

    test('email sign-in refused (401): wrong credentials, nothing stored',
        () async {
      final store = MemoryTokenStore();
      final auth = controller(store);
      await auth.restore();

      await auth.signInWithEmail('alice@example.com', 'wrong password');

      expect(auth.status, AuthStatus.failed);
      expect(auth.failure, SignInFailure.wrongCredentials);
      expect(store.token, isNull);
    });

    test('email sign-in: 429 too many attempts, 422 refused like a wrong pair',
        () async {
      final auth = controller(MemoryTokenStore());
      await auth.restore();

      server.status['POST /api/auth/email/sign-in'] = 429;
      await auth.signInWithEmail('alice@example.com', kEmailPassword);
      expect(auth.failure, SignInFailure.tooManyAttempts);

      server.status['POST /api/auth/email/sign-in'] = 422;
      await auth.signInWithEmail('alice@example.com', kEmailPassword);
      expect(auth.failure, SignInFailure.wrongCredentials);

      server.status['POST /api/auth/email/sign-in'] = 500;
      await auth.signInWithEmail('alice@example.com', kEmailPassword);
      expect(auth.failure, SignInFailure.serverError);
    });

    test('a Google 422 stays a server error', () async {
      final auth = controller(MemoryTokenStore());
      await auth.restore();

      server.status['POST /api/auth/google'] = 422;
      await auth.signInWithGoogle(kValidIdToken);

      expect(auth.failure, SignInFailure.serverError);
    });

    group('a mailed link', () {
      Future<EmailLinkFailure?> complete(
        AuthController auth, {
        String token = kEmailLinkToken,
      }) =>
          auth.completeEmailLink(
            token: token,
            password: kEmailPassword,
            displayName: 'Alice',
          );

      test('signs in, with the name, and stores the session', () async {
        final store = MemoryTokenStore();
        final auth = controller(store);
        await auth.restore();

        expect(await complete(auth), isNull);

        expect(auth.status, AuthStatus.signedIn);
        expect(store.token, isNotNull);
        expect(server.emailBodies['POST /api/auth/email/complete'], {
          'token': kEmailLinkToken,
          'password': kEmailPassword,
          'display_name': 'Alice',
        });
      });

      test('a reset sends no name', () async {
        final auth = controller(MemoryTokenStore());
        await auth.restore();

        await auth.completeEmailLink(
          token: kEmailLinkToken,
          password: kEmailPassword,
        );

        expect(
          server.emailBodies['POST /api/auth/email/complete'],
          isNot(contains('display_name')),
        );
      });

      test('says why it failed', () async {
        final auth = controller(MemoryTokenStore());
        await auth.restore();

        expect(await complete(auth, token: 'used'), EmailLinkFailure.expired);
        for (final (code, failure) in [
          (410, EmailLinkFailure.expired),
          (429, EmailLinkFailure.tooManyAttempts),
          (422, EmailLinkFailure.notAccepted),
          (500, EmailLinkFailure.serverError),
        ]) {
          server.status['POST /api/auth/email/complete'] = code;
          expect(await complete(auth), failure, reason: '$code');
        }
      });

      test('a failure leaves the session it found alone', () async {
        final store = MemoryTokenStore(server.addSession());
        final auth = controller(store);
        await auth.restore();
        final session = store.token;
        final statuses = <AuthStatus>[];
        auth.addListener(() => statuses.add(auth.status));

        expect(await complete(auth, token: 'used'), EmailLinkFailure.expired);

        expect(statuses, isEmpty);
        expect(auth.status, AuthStatus.signedIn);
        expect(store.token, session);
        expect(api.token, session);
      });
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

  group('isAdmin (admin panel plan D2)', () {
    test('restore reads it from /api/me', () async {
      server.isAdmin = true;
      final auth = controller(MemoryTokenStore(server.addSession()));
      expect(auth.isAdmin, isFalse);

      await auth.restore();

      expect(auth.isAdmin, isTrue);
    });

    test('false for anyone else', () async {
      final auth = controller(MemoryTokenStore(server.addSession()));
      await auth.restore();

      expect(auth.status, AuthStatus.signedIn);
      expect(auth.isAdmin, isFalse);
    });

    test('a sign-in reads /api/me, which its answer does not say', () async {
      server.isAdmin = true;
      final auth = controller(MemoryTokenStore());
      await auth.restore();

      await auth.signInWithGoogle(kValidIdToken);

      expect(
        server.calls.sublist(server.calls.length - 2),
        ['POST /api/auth/google', 'GET /api/me'],
      );
      expect(auth.status, AuthStatus.signedIn);
      expect(auth.isAdmin, isTrue);
    });

    test('a failed read signs in all the same, not as the admin', () async {
      server.isAdmin = true;
      server.status['GET /api/me'] = 500;
      final auth = controller(MemoryTokenStore());
      await auth.restore();

      await auth.signInWithEmail('alice@example.com', kEmailPassword);

      expect(auth.status, AuthStatus.signedIn);
      expect(auth.user!.email, 'alice@example.com');
      expect(auth.isAdmin, isFalse);
    });

    test('an unreachable read signs in all the same, not as the admin (R4-3)',
        () async {
      server.isAdmin = true;
      final auth = AuthController(
        api: ApiClient(
          MockClient((request) async {
            if (request.method == 'GET' && request.url.path == '/api/me') {
              throw http.ClientException('refused', request.url);
            }
            final copy = http.Request(request.method, request.url)
              ..headers.addAll(request.headers)
              ..bodyBytes = request.bodyBytes;
            return http.Response.fromStream(await server.client.send(copy));
          }),
          baseUrl: kApiBase,
        ),
        store: MemoryTokenStore(),
      );
      await auth.restore();

      await auth.signInWithEmail('alice@example.com', kEmailPassword);

      expect(auth.status, AuthStatus.signedIn);
      expect(auth.user!.email, 'alice@example.com');
      expect(auth.isAdmin, isFalse);
    });

    test('a 401 to that read leaves the user signed out', () async {
      server.status['GET /api/me'] = 401;
      final store = MemoryTokenStore();
      final auth = controller(store);
      await auth.restore();

      await auth.signInWithGoogle(kValidIdToken);
      await pumpEventQueue();

      expect(auth.status, AuthStatus.signedOut);
      expect(auth.isAdmin, isFalse);
      expect(store.token, isNull);
    });

    test('signing out forgets it', () async {
      server.isAdmin = true;
      final auth = controller(MemoryTokenStore(server.addSession()));
      await auth.restore();

      await auth.signOut();

      expect(auth.isAdmin, isFalse);
    });
  });
}
