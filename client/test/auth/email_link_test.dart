import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/email_link.dart';
import 'package:wishlist/src/shared/pending_join.dart';

void main() {
  group('emailLinkTokenFrom', () {
    test('the fragment of the two link pages', () {
      expect(
        emailLinkTokenFrom(Uri.parse('https://app.example/create-account#abc')),
        'abc',
      );
      expect(
        emailLinkTokenFrom(Uri.parse('https://app.example/reset-password#t-_9')),
        't-_9',
      );
    });

    test('nothing for any other address, or without a fragment', () {
      for (final url in [
        'https://app.example/create-account',
        'https://app.example/create-account#',
        'https://app.example/reset-password',
        'https://app.example/join#abc',
        'https://app.example/email-sign-up#abc',
        'https://app.example/create-account/x#abc',
      ]) {
        expect(emailLinkTokenFrom(Uri.parse(url)), isNull, reason: url);
      }
    });
  });

  group('captureEmailLinkToken', () {
    test('returns the token and removes it from the address bar', () {
      final browser = MemoryJoinBrowser();

      final token = captureEmailLinkToken(
        Uri.parse('https://app.example/create-account#abc'),
        browser,
      );

      expect(token, 'abc');
      expect(browser.replaced, ['/create-account']);
    });

    test('the query stays, only the fragment goes', () {
      final browser = MemoryJoinBrowser();

      captureEmailLinkToken(
        Uri.parse('https://app.example/reset-password?a=1#abc'),
        browser,
      );

      expect(browser.replaced, ['/reset-password?a=1']);
    });

    test('keeps the token out of storage', () {
      final browser = MemoryJoinBrowser();

      captureEmailLinkToken(
        Uri.parse('https://app.example/create-account#abc'),
        browser,
      );

      expect(browser.stored, isNull);
    });

    test('any other address leaves the address bar alone', () {
      final browser = MemoryJoinBrowser();

      expect(
        captureEmailLinkToken(Uri.parse('https://app.example/join#abc'), browser),
        isNull,
      );
      expect(browser.replaced, isEmpty);
    });
  });

  test('isEmailAddress follows the server (D4)', () {
    for (final good in ['a@b', ' alice@example.com ', 'a.b+c@d-e.fr']) {
      expect(isEmailAddress(good), isTrue, reason: good);
    }
    for (final bad in [
      '',
      'alice',
      '@example.com',
      'alice@',
      'a@b@c',
      'a b@c',
      'a@b\tc',
      '${'a' * 250}@b.fr',
    ]) {
      expect(isEmailAddress(bad), isFalse, reason: bad);
    }
  });

  test('isAcceptablePassword counts characters as the server does (D11)', () {
    expect(isAcceptablePassword('a' * 9), isFalse);
    expect(isAcceptablePassword('a' * 10), isTrue);
    expect(isAcceptablePassword('a' * 128), isTrue);
    expect(isAcceptablePassword('a' * 129), isFalse);
    // Five characters, ten UTF-16 units.
    expect(isAcceptablePassword('\u{1F600}' * 5), isFalse);
    // 128 characters, 256 UTF-16 units.
    expect(isAcceptablePassword('\u{1F600}' * 128), isTrue);
  });

  group('startEmailLink', () {
    ApiClient answering(Future<http.Response> Function(http.Request) handler) =>
        ApiClient(MockClient(handler), baseUrl: 'http://api.test');

    test('a 202 with no body is success, with the JSON body sent', () async {
      http.Request? sent;
      await startEmailLink(
        answering((request) async {
          sent = request;
          return http.Response('', 202);
        }),
        email: 'alice@example.com',
        language: 'fr',
      );

      expect(sent!.url.toString(), 'http://api.test/api/auth/email/start');
      expect(sent!.headers['Content-Type'], startsWith('application/json'));
      expect(sent!.body, '{"email":"alice@example.com","language":"fr"}');
    });

    test('an error status throws its code', () async {
      await expectLater(
        startEmailLink(
          answering((request) async => http.Response('', 429)),
          email: 'alice@example.com',
          language: 'en',
        ),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 429)),
      );
    });

    test('a network failure is unreachable', () async {
      await expectLater(
        startEmailLink(
          answering((request) async => throw http.ClientException('down')),
          email: 'alice@example.com',
          language: 'en',
        ),
        throwsA(isA<ApiUnreachableException>()),
      );
    });
  });
}
