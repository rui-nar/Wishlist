import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shushgift/src/shared/pending_join.dart';

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

  group('a mailed link in another tab (sign-in plan D19)', () {
    final t0 = DateTime.utc(2026, 11, 10, 12);

    setUp(() => SharedPreferences.setMockInitialValues({}));

    PendingJoin pendingOf(String? token) =>
        PendingJoin(MemoryJoinBrowser(token), token);

    test('the other tab finds the token, kept for that tab', () async {
      await pendingOf('abc').handOverForEmailLink(now: t0);

      // Another tab: its own session storage, nothing pending.
      final browser = MemoryJoinBrowser();
      final otherTab = PendingJoin(browser);
      await otherTab.resumeAfterEmailLink(now: t0.add(const Duration(minutes: 5)));

      expect(otherTab.token, 'abc');
      expect(browser.stored, 'abc');
    });

    test('the copy works once', () async {
      await pendingOf('abc').handOverForEmailLink(now: t0);
      final first = pendingOf(null);
      await first.resumeAfterEmailLink(now: t0);

      final second = pendingOf(null);
      await second.resumeAfterEmailLink(now: t0);

      expect(first.token, 'abc');
      expect(second.token, isNull);
    });

    test('after an hour it is gone', () async {
      await pendingOf('abc').handOverForEmailLink(now: t0);

      final otherTab = pendingOf(null);
      await otherTab.resumeAfterEmailLink(
        now: t0.add(kJoinHandoverLifetime),
      );

      expect(otherTab.token, isNull);
    });

    test('what this tab has pending wins, and the copy still goes', () async {
      await pendingOf('old').handOverForEmailLink(now: t0);

      final thisTab = pendingOf('mine');
      await thisTab.resumeAfterEmailLink(now: t0);
      expect(thisTab.token, 'mine');

      final later = pendingOf(null);
      await later.resumeAfterEmailLink(now: t0);
      expect(later.token, isNull);
    });

    test('asking again with nothing pending removes an earlier copy', () async {
      await pendingOf('abc').handOverForEmailLink(now: t0);

      await pendingOf(null).handOverForEmailLink(now: t0);

      final otherTab = pendingOf(null);
      await otherTab.resumeAfterEmailLink(now: t0);
      expect(otherTab.token, isNull);
    });

    test('an unreadable copy is the same as none', () async {
      SharedPreferences.setMockInitialValues({
        'flutter.shushgift.join_handover': 'not json',
      });

      final otherTab = pendingOf(null);
      await otherTab.resumeAfterEmailLink(now: t0);

      expect(otherTab.token, isNull);
    });
  });
}
