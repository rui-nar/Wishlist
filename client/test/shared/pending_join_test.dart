import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/shared/pending_join.dart';

void main() {
  group('joinTokenFrom', () {
    test('the fragment of /join', () {
      expect(joinTokenFrom(Uri.parse('https://app.example/join#abc')), 'abc');
      expect(
        joinTokenFrom(Uri.parse('http://localhost:5500/join?x=1#t-_9')),
        't-_9',
      );
    });

    test('nothing for any other address, or without a fragment', () {
      for (final url in [
        'https://app.example/join',
        'https://app.example/join#',
        'https://app.example/#abc',
        'https://app.example/joined#abc',
        'https://app.example/join/abc',
        'https://app.example/sign-in?from=%2Fjoin',
        'https://app.example/lists/1#abc',
      ]) {
        expect(joinTokenFrom(Uri.parse(url)), isNull, reason: url);
      }
    });
  });

  group('PendingJoin.capture', () {
    test('/join#abc: pending abc, kept, and the fragment removed', () {
      final browser = MemoryJoinBrowser();

      final pending =
          PendingJoin.capture(Uri.parse('https://app.example/join#abc'), browser);

      expect(pending.token, 'abc');
      expect(browser.stored, 'abc');
      expect(browser.replaced, ['/join']);
    });

    test('the query stays, only the fragment goes', () {
      final browser = MemoryJoinBrowser();

      PendingJoin.capture(Uri.parse('https://app.example/join?a=1#abc'), browser);

      expect(browser.replaced, ['/join?a=1']);
    });

    test('a reload keeps the pending token, wherever it lands', () {
      final browser = MemoryJoinBrowser();
      PendingJoin.capture(Uri.parse('https://app.example/join#abc'), browser);

      // The tab reloads during sign-in, then lands on /join again: the
      // address has no fragment any more.
      final duringSignIn = PendingJoin.capture(
        Uri.parse('https://app.example/sign-in?from=%2Fjoin'),
        browser,
      );
      final back = PendingJoin.capture(
        Uri.parse('https://app.example/join'),
        browser,
      );

      expect(duringSignIn.token, 'abc');
      expect(back.token, 'abc');
      // Nothing to remove from those addresses.
      expect(browser.replaced, ['/join']);
    });

    test('a new link replaces the pending one', () {
      final browser = MemoryJoinBrowser('old');

      final pending =
          PendingJoin.capture(Uri.parse('https://app.example/join#new'), browser);

      expect(pending.token, 'new');
      expect(browser.stored, 'new');
    });

    test('once cleared, a load of /join without a fragment has none', () {
      final browser = MemoryJoinBrowser();
      final pending =
          PendingJoin.capture(Uri.parse('https://app.example/join#abc'), browser);

      pending.clear();

      expect(pending.token, isNull);
      expect(browser.stored, isNull);
      expect(
        PendingJoin.capture(Uri.parse('https://app.example/join'), browser)
            .token,
        isNull,
      );
    });

    test('no link and nothing kept: nothing pending', () {
      expect(
        PendingJoin.capture(Uri.parse('https://app.example/'), MemoryJoinBrowser())
            .token,
        isNull,
      );
    });
  });
}
