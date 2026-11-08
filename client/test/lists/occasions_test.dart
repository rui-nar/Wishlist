import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:share_plus_platform_interface/share_plus_platform_interface.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/lists/lists_repository.dart';
import 'package:wishlist/src/lists/occasion_form_screen.dart';
import 'package:wishlist/src/lists/occasion_members_screen.dart';
import 'package:wishlist/src/lists/share_link.dart';

import 'support/fake_lists_server.dart';

/// share_plus's platform side: records what it is asked to share.
class FakeSharePlatform extends SharePlatform {
  final shared = <ShareParams>[];

  /// Set when the platform has no share sheet.
  bool unavailable = false;

  @override
  Future<ShareResult> share(ShareParams params) async {
    if (unavailable) throw Exception('Navigator.canShare() is unavailable');
    shared.add(params);
    return const ShareResult('', ShareResultStatus.success);
  }
}

void main() {
  // Before anything reads SharePlus.instance, which keeps the platform it
  // first sees.
  final share = FakeSharePlatform();
  setUpAll(() => SharePlatform.instance = share);

  late FakeListsServer server;
  late String listId;

  setUp(() {
    share
      ..shared.clear()
      ..unavailable = false;
    server = FakeListsServer();
    server.accounts.publicBaseUrl = 'https://wishlist.example';
    listId = server.addList('Christmas', recipientName: 'Léa');
  });

  /// What the app puts on the clipboard.
  List<String> clipboard(WidgetTester tester) {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          copied.add((call.arguments as Map<Object?, Object?>)['text'] as String);
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null),
    );
    return copied;
  }

  Future<void> openMenu(WidgetTester tester) async {
    await tester.ensureVisible(find.byTooltip('Occasion actions'));
    await tester.tap(find.byTooltip('Occasion actions'));
    await tester.pumpAndSettle();
  }

  Future<void> tapVisible(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  group('share links', () {
    test('the server base URL first, then the web origin, else none', () {
      expect(
        shareLinkBase(
          publicBaseUrl: 'https://wishlist.example',
          webOrigin: 'http://localhost:5500',
        ),
        'https://wishlist.example',
      );
      expect(
        shareLinkBase(publicBaseUrl: null, webOrigin: 'http://localhost:5500'),
        'http://localhost:5500',
      );
      expect(shareLinkBase(publicBaseUrl: null, webOrigin: null), isNull);
    });

    test('the token is in the fragment, never in the path', () {
      final link = Uri.parse(shareLink('https://wishlist.example', 'a-b_c'));
      expect(link.path, '/join');
      expect(link.fragment, 'a-b_c');
      expect(link.query, isEmpty);
    });
  });

  group('the occasions section', () {
    testWidgets('empty: the heading and the button creating one',
        (tester) async {
      await startApp(tester, server, '/lists/$listId');

      expect(find.text('Occasions'), findsOneWidget);
      expect(find.text('New occasion'), findsOneWidget);
      expect(find.byTooltip('Occasion actions'), findsNothing);
    });

    testWidgets('each occasion: its date, invitee count and link state',
        (tester) async {
      server.addOccasion(
        listId,
        'Christmas 2026',
        '2026-12-24',
        token: 'tok',
        invitees: ['Carol', 'Dan'],
      );
      server.addOccasion(listId, 'Birthday', '2027-03-02');
      await startApp(tester, server, '/lists/$listId');

      expect(find.text('Christmas 2026'), findsOneWidget);
      expect(find.text('Dec 24, 2026 · 2 invitees'), findsOneWidget);
      expect(find.text('Anyone with the link can join'), findsOneWidget);
      expect(find.text('Birthday'), findsOneWidget);
      expect(find.text('Mar 2, 2027 · No invitees'), findsOneWidget);
      expect(find.text('No link: nobody new can join'), findsOneWidget);
    });

    testWidgets('copy link puts the link on the clipboard', (tester) async {
      server.addOccasion(listId, 'Christmas 2026', '2026-12-24', token: 'tok');
      await startApp(tester, server, '/lists/$listId');
      final copied = clipboard(tester);

      await tapVisible(tester, find.text('Copy link'));

      expect(copied, ['https://wishlist.example/join#tok']);
      expect(find.text('Link copied'), findsOneWidget);
    });

    testWidgets('share opens the share sheet with the link', (tester) async {
      server.addOccasion(listId, 'Christmas 2026', '2026-12-24', token: 'tok');
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, find.text('Share'));

      expect(share.shared.single.uri, Uri.parse('https://wishlist.example/join#tok'));
      expect(share.shared.single.subject, 'Christmas 2026');
      expect(share.shared.single.mailToFallbackEnabled, isFalse);
    });

    testWidgets('without a share sheet, share copies the link', (tester) async {
      share.unavailable = true;
      server.addOccasion(listId, 'Christmas 2026', '2026-12-24', token: 'tok');
      await startApp(tester, server, '/lists/$listId');
      final copied = clipboard(tester);

      await tapVisible(tester, find.text('Share'));

      expect(copied, ['https://wishlist.example/join#tok']);
      expect(find.text('Link copied'), findsOneWidget);
    });

    testWidgets('no host for a link (an app without a base URL): no copy',
        (tester) async {
      server.accounts.publicBaseUrl = null;
      server.addOccasion(listId, 'Christmas 2026', '2026-12-24', token: 'tok');
      await startApp(tester, server, '/lists/$listId');

      expect(find.text('Anyone with the link can join'), findsOneWidget);
      expect(find.text('Copy link'), findsNothing);
      expect(find.text('Share'), findsNothing);
    });

    testWidgets('create a link', (tester) async {
      final id = server.addOccasion(listId, 'Christmas 2026', '2026-12-24');
      await startApp(tester, server, '/lists/$listId');

      expect(find.text('Copy link'), findsNothing);
      await tapVisible(tester, find.widgetWithText(FilledButton, 'Create a link'));

      expect(server.calls, contains('POST /api/occasions/$id/link'));
      expect(server.occasions[id]!['join_token'], isNotNull);
      expect(find.text('Copy link'), findsOneWidget);
      expect(find.text('Anyone with the link can join'), findsOneWidget);
    });

    testWidgets('replacing the link warns first; cancel changes nothing',
        (tester) async {
      final id = server.addOccasion(
        listId,
        'Christmas 2026',
        '2026-12-24',
        token: 'tok',
      );
      await startApp(tester, server, '/lists/$listId');

      await openMenu(tester);
      await tester.tap(find.text('Replace the link'));
      await tester.pumpAndSettle();

      expect(find.text('Replace the link?'), findsOneWidget);
      expect(
        find.text(
          'The current link stops working. People who already joined keep '
          'their access.',
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(server.calls, isNot(contains('POST /api/occasions/$id/link')));

      await openMenu(tester);
      await tester.tap(find.text('Replace the link'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Replace'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('POST /api/occasions/$id/link'));
      expect(server.occasions[id]!['join_token'], isNot('tok'));

      final copied = clipboard(tester);
      await tapVisible(tester, find.text('Copy link'));
      expect(
        copied,
        ['https://wishlist.example/join#${server.occasions[id]!['join_token']}'],
      );
    });

    testWidgets('revoking the link asks first, then removes it',
        (tester) async {
      final id = server.addOccasion(
        listId,
        'Christmas 2026',
        '2026-12-24',
        token: 'tok',
      );
      await startApp(tester, server, '/lists/$listId');

      await openMenu(tester);
      await tester.tap(find.text('Revoke the link'));
      await tester.pumpAndSettle();
      expect(find.text('Revoke the link?'), findsOneWidget);
      await tester.tap(find.widgetWithText(TextButton, 'Revoke'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('DELETE /api/occasions/$id/link'));
      expect(find.text('No link: nobody new can join'), findsOneWidget);
      expect(find.text('Copy link'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Create a link'), findsOneWidget);
    });

    testWidgets('deleting an occasion asks first', (tester) async {
      final id = server.addOccasion(listId, 'Christmas 2026', '2026-12-24');
      await startApp(tester, server, '/lists/$listId');

      await openMenu(tester);
      await tester.tap(find.text('Delete occasion'));
      await tester.pumpAndSettle();
      expect(find.text('Delete this occasion?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(server.occasions, contains(id));

      await openMenu(tester);
      await tester.tap(find.text('Delete occasion'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Delete'));
      await tester.pumpAndSettle();

      expect(server.calls, contains('DELETE /api/occasions/$id'));
      expect(find.text('Christmas 2026'), findsNothing);
    });

    testWidgets('a failed change says so', (tester) async {
      final id = server.addOccasion(listId, 'Christmas 2026', '2026-12-24');
      server.status['POST /api/occasions/$id/link'] = 500;
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, find.widgetWithText(FilledButton, 'Create a link'));

      expect(
        find.text('Your changes could not be saved. Try again.'),
        findsOneWidget,
      );
    });
  });

  group('the occasion form', () {
    testWidgets('creating needs a name and a date', (tester) async {
      await startApp(tester, server, '/lists/$listId/occasions/new');

      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      expect(find.text('Enter the occasion'), findsOneWidget);
      expect(find.text('Choose a date'), findsOneWidget);
      expect(server.calls, isNot(contains('POST /api/lists/$listId/occasions')));
    });

    testWidgets('creating sends the name and the picked day, then goes back',
        (tester) async {
      await startApp(tester, server, '/lists/$listId');
      await tapVisible(tester, find.text('New occasion'));
      expect(find.byType(OccasionFormScreen), findsOneWidget);

      await tester.enterText(fieldLabelled('Occasion'), 'Christmas 2026');
      await tester.tap(find.text('Date'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('15'));
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Create'));
      await tester.pumpAndSettle();

      final now = DateTime.now();
      expect(server.bodies['POST /api/lists/$listId/occasions'], {
        'name': 'Christmas 2026',
        'date': formatJsonDate(DateTime(now.year, now.month, 15)),
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
    });

    testWidgets('editing shows the occasion and saves its changes',
        (tester) async {
      final id = server.addOccasion(listId, 'Christmas', '2026-12-24');
      await startApp(tester, server, '/lists/$listId');

      await openMenu(tester);
      await tester.tap(find.text('Rename or change the date'));
      await tester.pumpAndSettle();

      expect(find.text('Edit occasion'), findsOneWidget);
      expect(find.text('Dec 24, 2026'), findsOneWidget);
      await tester.enterText(fieldLabelled('Occasion'), 'Christmas 2026');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(server.bodies['PATCH /api/occasions/$id'], {
        'name': 'Christmas 2026',
        'date': '2026-12-24',
      });
      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
    });

    testWidgets('an occasion that is gone says so', (tester) async {
      await startApp(tester, server, '/lists/$listId/occasions/nope/edit');

      expect(find.text('This occasion no longer exists.'), findsOneWidget);
    });
  });

  group('invitees', () {
    late String occasion;

    setUp(() {
      occasion = server.addOccasion(
        listId,
        'Christmas 2026',
        '2026-12-24',
        token: 'tok',
        invitees: ['Carol', 'Dan'],
      );
    });

    String userId(String name) => server.members[occasion]!
        .firstWhere((member) => member['display_name'] == name)['user_id']!;

    testWidgets('the section opens who joined', (tester) async {
      await startApp(tester, server, '/lists/$listId');

      await tapVisible(tester, find.widgetWithText(OutlinedButton, 'Invitees'));

      expect(find.byType(OccasionMembersScreen), findsOneWidget);
      expect(find.text('Carol'), findsOneWidget);
      expect(find.text('Dan'), findsOneWidget);
      expect(find.text('Removed'), findsNothing);
    });

    testWidgets('nobody yet: says to share the link', (tester) async {
      server.members[occasion]!.clear();
      await startApp(
        tester,
        server,
        '/lists/$listId/occasions/$occasion/members',
      );

      expect(
        find.text('Nobody has joined yet. Share the link to invite people.'),
        findsOneWidget,
      );
    });

    testWidgets('removing asks first, saying they cannot come back',
        (tester) async {
      final carol = userId('Carol');
      await startApp(
        tester,
        server,
        '/lists/$listId/occasions/$occasion/members',
      );

      await tester.tap(find.widgetWithText(TextButton, 'Remove').first);
      await tester.pumpAndSettle();
      expect(find.text('Remove Carol?'), findsOneWidget);
      expect(
        find.text(
          'Carol loses access to this occasion at once, and cannot join it '
          'again, through any link, until you allow them again.',
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(
        server.calls,
        isNot(contains('DELETE /api/occasions/$occasion/members/$carol')),
      );

      await tester.tap(find.widgetWithText(TextButton, 'Remove').first);
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.widgetWithText(TextButton, 'Remove'),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        server.calls,
        contains('DELETE /api/occasions/$occasion/members/$carol'),
      );
      expect(find.text('Removed'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Allow again'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Remove'), findsOneWidget);
    });

    testWidgets('removing someone who just left shows them as removed (R6-2)',
        (tester) async {
      final carol = userId('Carol');
      await startApp(
        tester,
        server,
        '/lists/$listId/occasions/$occasion/members',
      );
      // Carol leaves while the owner still sees her among the invitees.
      final left = server.members[occasion]!.removeAt(0);

      await tester.tap(find.widgetWithText(TextButton, 'Remove').first);
      await tester.pumpAndSettle();
      server.hold = Completer();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.widgetWithText(TextButton, 'Remove'),
        ),
      );
      await tester.pump();
      // The server records the removal all the same, and answers 204.
      server.removed[occasion]!.add(left);
      server.hold!.complete();
      await tester.pumpAndSettle();

      expect(
        server.calls,
        contains('DELETE /api/occasions/$occasion/members/$carol'),
      );
      expect(find.text('This occasion no longer exists.'), findsNothing);
      expect(find.text('Removed'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Allow again'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Remove'), findsOneWidget);
    });

    testWidgets('a removed person can be allowed again', (tester) async {
      final carol = userId('Carol');
      server.removed[occasion]!.add(server.members[occasion]!.removeAt(0));
      await startApp(
        tester,
        server,
        '/lists/$listId/occasions/$occasion/members',
      );

      expect(find.text('Removed'), findsOneWidget);
      await tester.tap(find.widgetWithText(TextButton, 'Allow again'));
      await tester.pumpAndSettle();

      expect(
        server.calls,
        contains('DELETE /api/occasions/$occasion/removals/$carol'),
      );
      expect(
        find.text('Carol can join again with a current link.'),
        findsOneWidget,
      );
      expect(find.text('Removed'), findsNothing);
      expect(find.text('Carol'), findsNothing);
    });

    testWidgets('error: says why and retries', (tester) async {
      server.status['GET /api/occasions/$occasion/members'] = 500;
      await startApp(
        tester,
        server,
        '/lists/$listId/occasions/$occasion/members',
      );

      expect(
        find.text('The server could not complete the request. Try again.'),
        findsOneWidget,
      );
      server.status.remove('GET /api/occasions/$occasion/members');
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();
      expect(find.text('Carol'), findsOneWidget);
    });

    testWidgets('a deleted occasion says so, and goes back to the list',
        (tester) async {
      await startApp(tester, server, '/lists/$listId/occasions/nope/members');

      expect(find.text('This occasion no longer exists.'), findsOneWidget);
      await tester.tap(find.text('Back to the list'));
      await tester.pumpAndSettle();
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });
  });
}
