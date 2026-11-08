import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/main.dart';

void main() {
  Future<void> pumpApp(WidgetTester tester, http.Client client) async {
    await tester.pumpWidget(WishlistApp(
      httpClient: client,
      apiBaseUrl: 'http://api.test',
      appVersion: 'v1.2.3',
    ));
    await tester.pumpAndSettle();
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
}
