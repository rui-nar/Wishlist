import 'dart:async';

import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/api/api_image.dart';

void main() {
  ApiClient answering(int status) => ApiClient(
        MockClient((request) async => http.Response('', status)),
        baseUrl: '',
      );

  test('providers with equal paths are equal, others are not', () {
    final api = answering(200);
    expect(ApiImage(api, '/api/images/a/thumb'),
        ApiImage(answering(200), '/api/images/a/thumb'));
    expect(ApiImage(api, '/api/images/a/thumb').hashCode,
        ApiImage(api, '/api/images/a/thumb').hashCode);
    expect(ApiImage(api, '/api/images/a/thumb'),
        isNot(ApiImage(api, '/api/images/b/thumb')));
  });

  test('a 404 resolves to an error', () async {
    final provider = ApiImage(answering(404), '/api/images/a/thumb');
    final stream = provider.resolve(ImageConfiguration.empty);
    final error = Completer<Object>();
    stream.addListener(ImageStreamListener(
      (_, _) => error.completeError(StateError('loaded')),
      onError: (e, _) => error.complete(e),
    ));
    expect(await error.future, isA<ApiException>());
  });
}
