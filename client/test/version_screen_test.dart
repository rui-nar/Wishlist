import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/server_version.dart';

void main() {
  Future<void> pumpApp(WidgetTester tester, http.Client client) async {
    await tester.pumpWidget(WishlistApp(
      httpClient: client,
      apiBaseUrl: 'http://api.test',
      appVersion: 'v1.2.3',
    ));
    await tester.pumpAndSettle();
  }

  // Answers /api/version with v1.2.0 on validation.
  final okClient = MockClient((request) async => http.Response(
        jsonEncode({'version': 'v1.2.0', 'env': 'validation'}),
        200,
      ));

  // Makes the device language [locales] for the rest of the test.
  void setDeviceLocales(WidgetTester tester, List<Locale> locales) {
    tester.platformDispatcher.localesTestValue = locales;
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
  }

  testWidgets('shows the app version and the server version and env',
      (tester) async {
    Uri? requested;
    final client = MockClient((request) async {
      requested = request.url;
      return http.Response(
        jsonEncode({'version': 'v1.2.0', 'env': 'validation'}),
        200,
      );
    });

    await pumpApp(tester, client);

    expect(requested, Uri.parse('http://api.test/api/version'));
    expect(find.text('App v1.2.3'), findsOneWidget);
    expect(find.text('Server v1.2.0 (validation)'), findsOneWidget);
  });

  testWidgets('says the server is unreachable when the call fails',
      (tester) async {
    final client = MockClient((request) async {
      throw http.ClientException('Connection refused', request.url);
    });

    await pumpApp(tester, client);

    expect(find.text('App v1.2.3'), findsOneWidget);
    expect(find.text('Server unreachable'), findsOneWidget);
  });

  testWidgets('names the status when the server answers an error',
      (tester) async {
    final client = MockClient((request) async => http.Response('', 503));

    await pumpApp(tester, client);

    expect(find.text('Server answered HTTP 503'), findsOneWidget);
  });

  testWidgets('says so when the server answers unexpected JSON',
      (tester) async {
    final client = MockClient((request) async => http.Response('{}', 200));

    await pumpApp(tester, client);

    expect(find.text('Unexpected answer from the server'), findsOneWidget);
  });
  testWidgets('says so when the server does not answer in time',
      (tester) async {
    final client = MockClient((request) => Completer<http.Response>().future);

    await tester.pumpWidget(WishlistApp(
      httpClient: client,
      apiBaseUrl: 'http://api.test',
      appVersion: 'v1.2.3',
    ));
    await tester.pump(const Duration(seconds: 11));

    expect(find.text('Server unreachable (timed out)'), findsOneWidget);
  });

  testWidgets('shows the versions in French on a French device',
      (tester) async {
    setDeviceLocales(tester, const [Locale('fr', 'FR')]);

    await pumpApp(tester, okClient);

    expect(find.text('Application v1.2.3'), findsOneWidget);
    expect(find.text('Serveur v1.2.0 (validation)'), findsOneWidget);
  });

  testWidgets('falls back to English on a device in another language',
      (tester) async {
    setDeviceLocales(tester, const [Locale('de', 'DE')]);

    await pumpApp(tester, okClient);

    expect(find.text('App v1.2.3'), findsOneWidget);
    expect(find.text('Server v1.2.0 (validation)'), findsOneWidget);
  });

  group('fetchServerVersion', () {
    Future<ServerVersionException> failure(http.Client client) async {
      try {
        await fetchServerVersion(client, baseUrl: 'http://api.test');
      } on ServerVersionException catch (e) {
        return e;
      }
      fail('expected a ServerVersionException');
    }

    test('gives the reason, and the status of an HTTP error', () async {
      final unreachable = await failure(MockClient((request) async {
        throw http.ClientException('Connection refused', request.url);
      }));
      expect(unreachable.reason, ServerVersionFailure.unreachable);

      final httpError =
          await failure(MockClient((request) async => http.Response('', 503)));
      expect(httpError.reason, ServerVersionFailure.httpError);
      expect(httpError.statusCode, 503);

      final unexpected = await failure(
          MockClient((request) async => http.Response('{}', 200)));
      expect(unexpected.reason, ServerVersionFailure.unexpectedAnswer);
    });
  });
}
