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

  test('patchJson sends a PATCH with a JSON body and reads the object',
      () async {
    final seen = <http.Request>[];
    final api = ApiClient(
      MockClient((request) async {
        seen.add(request);
        return http.Response('{"id": "g1"}', 200);
      }),
      baseUrl: 'http://api.test',
    )..token = 'secret';

    final answer = await api.patchJson('/api/gifts/g1', {'title': 'Book'});

    expect(answer, {'id': 'g1'});
    expect(seen.single.method, 'PATCH');
    expect(seen.single.url, Uri.parse('http://api.test/api/gifts/g1'));
    expect(seen.single.headers['Authorization'], 'Bearer secret');
    expect(seen.single.headers['Content-Type'], startsWith('application/json'));
    expect(jsonDecode(seen.single.body), {'title': 'Book'});
  });

  test('getJsonList reads an array; an object where an array is expected '
      'is not a usable answer, nor the reverse', () async {
    ApiClient answering(String body) => ApiClient(
          MockClient((request) async => http.Response(body, 200)),
          baseUrl: '',
        );

    expect(await answering('[{"id": "l1"}]').getJsonList('/api/lists'), [
      {'id': 'l1'},
    ]);
    await expectLater(
      answering('{"id": "l1"}').getJsonList('/api/lists'),
      throwsA(isA<ApiUnreachableException>()),
    );
    await expectLater(
      answering('[]').getJson('/api/me'),
      throwsA(isA<ApiUnreachableException>()),
    );
  });

  test('getJsonList and patchJson report errors as the other calls do',
      () async {
    final reported = <String>[];
    final api = ApiClient(
      MockClient((request) async =>
          http.Response('', request.method == 'PATCH' ? 422 : 401)),
      baseUrl: '',
    )
      ..token = 't'
      ..onUnauthorized = reported.add;

    await expectLater(
      api.getJsonList('/api/lists'),
      throwsA(isA<UnauthorizedException>()),
    );
    expect(reported, ['t']);
    await expectLater(
      api.patchJson('/api/lists/l1', {}),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 422)),
    );
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

  test('an error keeps its JSON object body, for documented fields',
      () async {
    Future<ApiException> failure(http.Response response) async {
      try {
        await ApiClient(MockClient((request) async => response), baseUrl: '')
            .postJson('/api/join', {'token': 't'});
      } on ApiException catch (e) {
        return e;
      }
      throw StateError('no ApiException');
    }

    final conflict = await failure(http.Response(
      '{"detail": "You own this list", "list_id": "l1"}',
      409,
    ));
    expect(conflict.statusCode, 409);
    expect(conflict.body?['list_id'], 'l1');
    expect((await failure(http.Response('<html>', 502))).body, isNull);
    expect((await failure(http.Response('[1]', 400))).body, isNull);
    expect((await failure(http.Response('', 404))).body, isNull);
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

    test('reads the share links base URL; null or empty means none',
        () async {
      expect(
        (await fetchClientConfig(answering({
          'google_client_id': 'abc',
          'public_base_url': 'https://wishlist.example',
        })))
            .publicBaseUrl,
        'https://wishlist.example',
      );
      for (final none in [null, '']) {
        expect(
          (await fetchClientConfig(
            answering({'google_client_id': 'abc', 'public_base_url': none}),
          ))
              .publicBaseUrl,
          isNull,
        );
      }
      // An older server without the field.
      expect(
        (await fetchClientConfig(answering({'google_client_id': 'abc'})))
            .publicBaseUrl,
        isNull,
      );
    });

    test('a field that is not a string is not a usable answer', () async {
      await expectLater(
        fetchClientConfig(
          answering({'google_client_id': 'abc', 'public_base_url': 1}),
        ),
        throwsA(isA<ApiUnreachableException>()),
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
