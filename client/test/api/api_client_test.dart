import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/api/config.dart';

void main() {
  test('sends the bearer token when there is one, and JSON bodies', () async {
    final seen = <http.Request>[];
    final api = ApiClient(
      MockClient((request) async {
        seen.add(request);
        return http.Response('{"ok": true}', 200);
      }),
      baseUrl: 'http://api.test',
    );

    await api.postJson('/api/auth/google', {'id_token': 'x'});
    api.token = 'secret';
    await api.getJson('/api/me');

    expect(seen[0].url, Uri.parse('http://api.test/api/auth/google'));
    expect(seen[0].headers.containsKey('Authorization'), isFalse);
    expect(seen[0].headers['Content-Type'], startsWith('application/json'));
    expect(jsonDecode(seen[0].body), {'id_token': 'x'});
    expect(seen[1].headers['Authorization'], 'Bearer secret');
  });

  test('a 401 to a call with a token throws and reports that token', () async {
    final reported = <String>[];
    final api = ApiClient(
      MockClient((request) async => http.Response('', 401)),
      baseUrl: '',
    )
      ..token = 'old'
      ..onUnauthorized = reported.add;

    await expectLater(api.getJson('/api/me'), throwsA(isA<UnauthorizedException>()));
    expect(reported, ['old']);
  });

  test('a 401 to a call without a token is not a session ending', () async {
    final reported = <String>[];
    final api = ApiClient(
      MockClient((request) async => http.Response('', 401)),
      baseUrl: '',
    )..onUnauthorized = reported.add;

    await expectLater(
      api.postJson('/api/auth/google', {'id_token': 'bad'}),
      throwsA(isA<UnauthorizedException>()),
    );
    expect(reported, isEmpty);
  });

  test('other failures are typed', () async {
    Future<Object?> failure(http.Client client) async {
      try {
        await ApiClient(client, baseUrl: '').getJson('/api/me');
      } catch (e) {
        return e;
      }
      return null;
    }

    final serverError =
        await failure(MockClient((request) async => http.Response('', 500)));
    expect(serverError, isA<ApiException>());
    expect((serverError as ApiException).statusCode, 500);
    expect(
      await failure(MockClient((request) async {
        throw http.ClientException('refused', request.url);
      })),
      isA<ApiUnreachableException>(),
    );
    expect(
      await failure(MockClient((request) async => http.Response('<html>', 200))),
      isA<ApiUnreachableException>(),
    );
  });

  test('gives up after 10 seconds', () {
    return withInstantTimers(() async {
      final api = ApiClient(
        MockClient((request) => Completer<http.Response>().future),
        baseUrl: '',
      );
      await expectLater(
        api.getJson('/api/me'),
        throwsA(isA<ApiUnreachableException>()),
      );
    });
  });

  group('fetchClientConfig', () {
    ApiClient answering(Object body) => ApiClient(
          MockClient((request) async => http.Response(jsonEncode(body), 200)),
          baseUrl: '',
        );

    test('reads the Google client ID', () async {
      final config =
          await fetchClientConfig(answering({'google_client_id': 'abc'}));
      expect(config.googleClientId, 'abc');
    });

    test('null or empty means not configured', () async {
      expect(
        (await fetchClientConfig(answering({'google_client_id': null})))
            .googleClientId,
        isNull,
      );
      expect(
        (await fetchClientConfig(answering({'google_client_id': ''})))
            .googleClientId,
        isNull,
      );
    });
  });
}

/// Runs [body] in a zone whose timers fire at once, so a 10-second timeout
/// does not take 10 seconds.
Future<void> withInstantTimers(Future<void> Function() body) {
  return runZoned(
    body,
    zoneSpecification: ZoneSpecification(
      createTimer: (self, parent, zone, duration, callback) =>
          parent.createTimer(zone, Duration.zero, callback),
    ),
  );
}
