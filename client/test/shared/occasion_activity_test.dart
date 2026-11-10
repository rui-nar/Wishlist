import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/status_chip.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/shared/shared_with_me_screen.dart';

import '../lists/support/fake_lists_server.dart';

/// Invitee activity on the occasion screen: the rose chips, the gift's sheet
/// and its actions (RESERVING_PLAN D13).
void main() {
  late FakeListsServer server;
  late String list;
  late String occasion;
  late String other;

  /// Carol and Dan give in Alice's occasion; Eve in another one.
  final carol = FakeListsServer.giver('Carol');
  final dan = FakeListsServer.giver('Dan');
  final eve = FakeListsServer.giver('Eve');
  final alice = FakeListsServer.giver(kAliceName, mine: true);

  setUp(() {
    server = FakeListsServer();
    list = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    occasion = server.addOccasion(
      list,
      'Christmas 2026',
      '2026-12-24',
      invitees: ['Carol', 'Dan'],
    );
    other = server.addOccasion(list, 'Birthday', '2027-03-02');
    server.joined.add(occasion);
  });

  String priced(String title) =>
      server.addGift(list, title, priceAmount: '149.00', priceCurrency: 'EUR');

  /// The activity chip of the gift titled [title], or null without one.
  StatusChip? roseChip(WidgetTester tester, String title) {
    final card = tester.widget<GiftCard>(find.widgetWithText(GiftCard, title));
    return card.chips
        .whereType<StatusChip>()
        .where((chip) => chip.variant == StatusChipVariant.inviteeActivity)
        .firstOrNull;
  }

  Future<void> openSheet(WidgetTester tester, String title) async {
    await tester.tap(find.widgetWithText(GiftCard, title));
    await tester.pumpAndSettle();
  }

  /// The buttons of the open sheet, in order.
  List<String> sheetActions(WidgetTester tester) => [
        for (final button in tester.widgetList<ButtonStyleButton>(
          find.descendant(
            of: find.byType(BottomSheet),
            matching: find.byWidgetPredicate(
              (widget) => widget is FilledButton || widget is OutlinedButton,
            ),
          ),
        ))
          ((button.child as Text).data!),
      ];

  Future<void> tapInSheet(WidgetTester tester, String label) async {
    await tester.tap(
      find.descendant(of: find.byType(BottomSheet), matching: find.text(label)),
    );
    await tester.pumpAndSettle();
  }

  Future<void> tapInDialog(WidgetTester tester, String label) async {
    await tester.tap(
      find.descendant(of: find.byType(AlertDialog), matching: find.text(label)),
    );
    await tester.pumpAndSettle();
  }

  int claimReads() => server.calls
      .where((call) => call == 'GET /api/occasions/$occasion/claims')
      .length;

  testWidgets('a rose chip per state; a free gift has none', (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final gifts = {
      for (final title in [
        'Gift: Free',
        'Gift: Reserved',
        'Gift: Mine',
        'Gift: Bought',
        'Gift: Nameless',
        'Gift: Group',
        'Gift: Group bought',
        'Gift: Taken',
        'Gift: Bought elsewhere',
      ])
        title: priced(title),
    };
    server
      ..addClaim(gifts['Gift: Reserved']!, occasion, [carol])
      ..addClaim(gifts['Gift: Mine']!, occasion, [alice])
      ..addClaim(gifts['Gift: Bought']!, occasion, [carol], bought: true)
      ..addClaim(gifts['Gift: Nameless']!, occasion, [], bought: true)
      ..addClaim(
        gifts['Gift: Group']!,
        occasion,
        [carol, dan, alice],
        group: true,
      )
      ..addClaim(
        gifts['Gift: Group bought']!,
        occasion,
        [carol, dan],
        group: true,
        bought: true,
      )
      ..addClaim(gifts['Gift: Taken']!, other, [eve])
      ..addClaim(gifts['Gift: Bought elsewhere']!, null, [eve], bought: true);
    await startApp(tester, server, '/shared/$occasion');

    expect(roseChip(tester, 'Gift: Free'), isNull);
    final expected = {
      'Gift: Reserved': 'Reserved by Carol',
      'Gift: Mine': 'Reserved by you',
      'Gift: Bought': 'Bought by Carol',
      'Gift: Nameless': 'Bought',
      'Gift: Group': 'Group gift · 3',
      'Gift: Group bought': 'Group gift · bought',
      'Gift: Taken': 'Taken',
      'Gift: Bought elsewhere': 'Taken',
    };
    for (final MapEntry(key: title, value: label) in expected.entries) {
      expect(roseChip(tester, title)?.label, label, reason: title);
    }
  });

  group('the sheet offers what the state allows', () {
    final table = <String, (void Function(String gift), List<String>)>{
      'free': ((_) {}, ['Reserve', 'Start a group gift', 'Mark as bought']),
      'reserved by me': (
        (gift) => server.addClaim(gift, occasion, [alice]),
        ['Mark as bought', 'Release'],
      ),
      'reserved by another': (
        (gift) => server.addClaim(gift, occasion, [carol]),
        [],
      ),
      'group with me': (
        (gift) => server.addClaim(gift, occasion, [carol, alice], group: true),
        ['Change my amount', 'Mark as bought', 'Leave the group gift'],
      ),
      'group without me': (
        (gift) => server.addClaim(gift, occasion, [carol], group: true),
        ['Join the group gift'],
      ),
      'bought by me': (
        (gift) => server.addClaim(gift, occasion, [alice], bought: true),
        [],
      ),
      'group bought': (
        (gift) => server.addClaim(
              gift,
              occasion,
              [carol, alice],
              group: true,
              bought: true,
            ),
        [],
      ),
      'taken': ((gift) => server.addClaim(gift, other, [eve]), []),
      'passed, free': ((_) => server.passed.add(occasion), []),
      'passed, bought': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [carol], bought: true);
        },
        [],
      ),
      // Expired: the user's own may still be marked bought (D8, R3-1);
      // anyone else's is gone.
      'passed, reserved by me': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [alice]);
        },
        ['Mark as bought'],
      ),
      'passed, group with me': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [carol, alice], group: true);
        },
        ['Mark as bought'],
      ),
      'passed, bought by me': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [alice], bought: true);
        },
        [],
      ),
      'passed, reserved by another': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [carol]);
        },
        [],
      ),
      'passed, group without me': (
        (gift) {
          server.passed.add(occasion);
          server.addClaim(gift, occasion, [carol], group: true);
        },
        [],
      ),
    };
    for (final MapEntry(key: state, value: (arrange, actions))
        in table.entries) {
      testWidgets(state, (tester) async {
        arrange(priced('Headphones'));
        await startApp(tester, server, '/shared/$occasion');
        await openSheet(tester, 'Headphones');

        final passed = state.startsWith('passed');
        expect(sheetActions(tester), actions);
        expect(
          find.text('This occasion has passed: nothing can be reserved any more.'),
          passed && actions.isEmpty ? findsOneWidget : findsNothing,
        );
        expect(
          find.text(
            'This occasion has passed, so this gift is no longer held for '
            'you. If you gave it, mark it as bought so nobody else gives it.',
          ),
          passed && actions.isNotEmpty ? findsOneWidget : findsNothing,
        );
      });
    }

    testWidgets('a group gift without a price has no amount to change',
        (tester) async {
      final gift = server.addGift(list, 'Socks');
      server.addClaim(gift, occasion, [alice], group: true);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Socks');

      expect(sheetActions(tester), ['Mark as bought', 'Leave the group gift']);
    });

    testWidgets('taken says only that it is given for another occasion',
        (tester) async {
      server.addClaim(priced('Headphones'), other, [eve]);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');

      expect(
        find.text('This gift is already being given for another occasion.'),
        findsOneWidget,
      );
      expect(find.textContaining('Eve'), findsNothing);
      expect(find.textContaining('Birthday'), findsNothing);
    });

    testWidgets('taken by the caller in another occasion names nobody',
        (tester) async {
      server.addClaim(priced('Headphones'), other, [alice]);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');

      expect(
        find.text('This gift is already being given for another occasion.'),
        findsOneWidget,
      );
      expect(find.textContaining('Someone else'), findsNothing);
    });
  });

  testWidgets('the sheet lists the group with its pledges and their total',
      (tester) async {
    final gift = priced('Headphones');
    server.addClaim(gift, occasion, [
      FakeListsServer.giver('Carol', amount: '50.00', currency: 'EUR'),
      dan,
      FakeListsServer.giver(kAliceName, mine: true, amount: '20.50', currency: 'EUR'),
    ], group: true);
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');

    expect(find.text('Carol'), findsOneWidget);
    expect(find.text('€50.00'), findsOneWidget);
    expect(find.text('Dan'), findsOneWidget);
    expect(find.text('You'), findsOneWidget);
    expect(find.text('€20.50'), findsOneWidget);
    expect(find.text('€70.50 pledged of €149.00'), findsOneWidget);
  });

  testWidgets('no total when a pledge is in another currency', (tester) async {
    final gift = priced('Headphones');
    server.addClaim(gift, occasion, [
      FakeListsServer.giver('Carol', amount: '50.00', currency: 'EUR'),
      FakeListsServer.giver('Dan', amount: '30.00', currency: 'USD'),
    ], group: true);
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');

    expect(find.text('\$30.00'), findsOneWidget);
    expect(find.textContaining('pledged of'), findsNothing);
  });

  group('each action calls its route, then loads the claims again', () {
    testWidgets('reserve', (tester) async {
      final gift = priced('Headphones');
      await startApp(tester, server, '/shared/$occasion');
      final reads = claimReads();
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Reserve');

      expect(
        server.calls,
        contains('POST /api/occasions/$occasion/gifts/$gift/reservation'),
      );
      expect(claimReads(), reads + 1);
      expect(roseChip(tester, 'Headphones')!.label, 'Reserved by you');
    });

    testWidgets('release asks first, then frees the gift', (tester) async {
      final gift = priced('Headphones');
      server.addClaim(gift, occasion, [alice]);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Release');

      expect(find.text('Release this gift?'), findsOneWidget);
      expect(find.text('Someone else can then reserve it.'), findsOneWidget);
      final reads = claimReads();
      await tapInDialog(tester, 'Release');

      expect(
        server.calls,
        contains('DELETE /api/occasions/$occasion/gifts/$gift/reservation'),
      );
      expect(claimReads(), reads + 1);
      expect(roseChip(tester, 'Headphones'), isNull);
    });

    testWidgets('mark as bought says it is final', (tester) async {
      final gift = priced('Headphones');
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Mark as bought');

      expect(find.text('Mark as bought?'), findsOneWidget);
      expect(
        find.text(
          "This is final: it can't be undone, and nobody else can take this gift.",
        ),
        findsOneWidget,
      );
      final reads = claimReads();
      await tapInDialog(tester, 'Mark as bought');

      expect(
        server.calls,
        contains('POST /api/occasions/$occasion/gifts/$gift/bought'),
      );
      expect(claimReads(), reads + 1);
      expect(roseChip(tester, 'Headphones')!.label, 'Bought by you');
    });

    testWidgets('cancelling a confirmation sends nothing', (tester) async {
      final gift = priced('Headphones');
      server.addClaim(gift, occasion, [alice]);
      await startApp(tester, server, '/shared/$occasion');
      // Opening the sheet loads its thread, which is no write.
      final thread = 'GET /api/occasions/$occasion/gifts/$gift/comments';
      int calls() => server.calls.where((call) => call != thread).length;
      final before = calls();
      for (final action in ['Release', 'Mark as bought']) {
        await openSheet(tester, 'Headphones');
        await tapInSheet(tester, action);
        await tapInDialog(tester, 'Cancel');
      }

      expect(calls(), before);
      expect(roseChip(tester, 'Headphones')!.label, 'Reserved by you');
    });

    testWidgets('start a group gift with an amount in the gift currency',
        (tester) async {
      final gift = priced('Headphones');
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Start a group gift');

      expect(find.widgetWithText(AlertDialog, 'Start a group gift'), findsOneWidget);
      expect(find.text('EUR'), findsOneWidget);
      await tester.enterText(fieldLabelled('My amount (optional)'), '40');
      final reads = claimReads();
      await tapInDialog(tester, 'Start');

      final call = 'PUT /api/occasions/$occasion/gifts/$gift/pledge';
      expect(server.calls, contains(call));
      expect(server.bodies[call], {'amount': '40'});
      expect(claimReads(), reads + 1);
      expect(roseChip(tester, 'Headphones')!.label, 'Group gift · 1');
    });

    testWidgets('join a group gift without an amount', (tester) async {
      final gift = priced('Headphones');
      server.addClaim(gift, occasion, [carol], group: true);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Join the group gift');
      await tapInDialog(tester, 'Join');

      final call = 'PUT /api/occasions/$occasion/gifts/$gift/pledge';
      expect(server.bodies[call], {'amount': null});
      expect(roseChip(tester, 'Headphones')!.label, 'Group gift · 2');
    });

    testWidgets('change my amount starts from it', (tester) async {
      final gift = priced('Headphones');
      server.addClaim(gift, occasion, [
        FakeListsServer.giver(kAliceName, mine: true, amount: '40.00', currency: 'EUR'),
      ], group: true);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Change my amount');

      expect(find.text('40.00'), findsOneWidget);
      await tester.enterText(fieldLabelled('My amount (optional)'), '55,5');
      await tapInDialog(tester, 'Save');

      final call = 'PUT /api/occasions/$occasion/gifts/$gift/pledge';
      expect(server.bodies[call], {'amount': '55.5'});
      await openSheet(tester, 'Headphones');
      expect(find.text('€55.50'), findsOneWidget);
    });

    testWidgets('an amount must be above zero; nothing is sent until it is',
        (tester) async {
      priced('Headphones');
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Start a group gift');
      final calls = server.calls.length;
      for (final wrong in ['0', '-5', '19.999', 'ten']) {
        await tester.enterText(fieldLabelled('My amount (optional)'), wrong);
        await tapInDialog(tester, 'Start');
        expect(
          find.text('Enter an amount such as 50 or 49.90'),
          findsOneWidget,
          reason: wrong,
        );
      }
      expect(server.calls.length, calls);
    });

    testWidgets('a gift without a price: no amount field', (tester) async {
      final gift = server.addGift(list, 'Socks');
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Socks');
      await tapInSheet(tester, 'Start a group gift');

      expect(find.byType(TextField), findsNothing);
      expect(
        find.text(
          'The others giving for this occasion see your name. This gift has '
          'no price, so there is no amount to give.',
        ),
        findsOneWidget,
      );
      await tapInDialog(tester, 'Start');

      expect(
        server.bodies['PUT /api/occasions/$occasion/gifts/$gift/pledge'],
        {'amount': null},
      );
    });

    testWidgets('leave the group gift asks first; the last one out frees it',
        (tester) async {
      final gift = priced('Headphones');
      server.addClaim(gift, occasion, [alice], group: true);
      await startApp(tester, server, '/shared/$occasion');
      await openSheet(tester, 'Headphones');
      await tapInSheet(tester, 'Leave the group gift');

      expect(find.text('Leave the group gift?'), findsOneWidget);
      final reads = claimReads();
      await tapInDialog(tester, 'Leave');

      expect(
        server.calls,
        contains('DELETE /api/occasions/$occasion/gifts/$gift/pledge'),
      );
      expect(claimReads(), reads + 1);
      expect(roseChip(tester, 'Headphones'), isNull);
    });
  });

  group('passed: my own expired claim can still be marked bought', () {
    for (final (kind, group, chip, bought) in [
      ('a reservation', false, 'Reserved by you', 'Bought by you'),
      ('a group gift', true, 'Group gift · 2', 'Group gift · bought'),
    ]) {
      testWidgets(kind, (tester) async {
        final gift = priced('Headphones');
        server
          ..passed.add(occasion)
          ..addClaim(
            gift,
            occasion,
            group ? [carol, alice] : [alice],
            group: group,
          );
        await startApp(tester, server, '/shared/$occasion');

        expect(roseChip(tester, 'Headphones')!.label, chip);
        await openSheet(tester, 'Headphones');
        await tapInSheet(tester, 'Mark as bought');
        expect(find.text('Mark as bought?'), findsOneWidget);
        final reads = claimReads();
        await tapInDialog(tester, 'Mark as bought');

        expect(
          server.calls,
          contains('POST /api/occasions/$occasion/gifts/$gift/bought'),
        );
        expect(claimReads(), reads + 1);
        expect(roseChip(tester, 'Headphones')!.label, bought);
        await openSheet(tester, 'Headphones');
        expect(sheetActions(tester), isEmpty);
      });
    }

    testWidgets("someone else's expired claim shows nothing", (tester) async {
      server
        ..passed.add(occasion)
        ..addClaim(priced('Headphones'), occasion, [carol])
        ..addClaim(priced('Book'), occasion, [carol, dan], group: true)
        ..addClaim(priced('Lamp'), other, [eve]);
      await startApp(tester, server, '/shared/$occasion');

      expect(roseChip(tester, 'Headphones'), isNull);
      expect(roseChip(tester, 'Book'), isNull);
      expect(roseChip(tester, 'Lamp')!.label, 'Taken');
    });
  });

  group('an action on its way', () {
    /// Taps [label] in the open sheet, the server holding every answer.
    Future<void> sendHeld(WidgetTester tester, String label) async {
      server.hold = Completer();
      await tester.tap(
        find.descendant(of: find.byType(BottomSheet), matching: find.text(label)),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
    }

    Future<void> release(WidgetTester tester) async {
      server.hold!.complete();
      server.hold = null;
      await tester.pumpAndSettle();
    }

    /// The occasion, opened from Shared with me, so that back leaves it.
    Future<void> openFromShared(WidgetTester tester) async {
      await startApp(tester, server, '/shared');
      await tester.tap(find.text('Christmas 2026'));
      await tester.pumpAndSettle();
    }

    testWidgets('shows progress; a tap meanwhile says to wait',
        (tester) async {
      final gift = priced('Headphones');
      priced('Book');
      await startApp(tester, server, '/shared/$occasion');
      expect(find.byType(LinearProgressIndicator), findsNothing);
      await openSheet(tester, 'Headphones');
      await sendHeld(tester, 'Reserve');

      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      await tester.tap(find.widgetWithText(GiftCard, 'Book'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(
        find.text('Wait a moment: your last change is still being saved.'),
        findsOneWidget,
      );
      expect(find.byType(BottomSheet), findsNothing);

      await release(tester);
      expect(
        server.calls,
        contains('POST /api/occasions/$occasion/gifts/$gift/reservation'),
      );
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(roseChip(tester, 'Headphones')!.label, 'Reserved by you');
    });

    testWidgets('leaving before it is done says nothing of a write that '
        'went through', (tester) async {
      final gift = priced('Headphones');
      await openFromShared(tester);
      await openSheet(tester, 'Headphones');
      await sendHeld(tester, 'Reserve');
      await tester.pageBack();
      await tester.pump();
      await release(tester);

      expect(find.byType(SharedWithMeScreen), findsOneWidget);
      expect(server.claims[gift], isNotNull);
      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('leaving before it fails still says it failed',
        (tester) async {
      final gift = priced('Headphones');
      server.status['POST /api/occasions/$occasion/gifts/$gift/reservation'] =
          500;
      await openFromShared(tester);
      await openSheet(tester, 'Headphones');
      await sendHeld(tester, 'Reserve');
      await tester.pageBack();
      await tester.pump();
      await release(tester);

      expect(find.byType(SharedWithMeScreen), findsOneWidget);
      expect(
        find.text('The server could not complete the request. Try again.'),
        findsOneWidget,
      );
    });
  });

  testWidgets('taken meanwhile: says so and shows who has it now',
      (tester) async {
    final gift = priced('Headphones');
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');
    // Carol reserves it while Alice's sheet is open.
    server.addClaim(gift, occasion, [carol]);
    final reads = claimReads();
    await tapInSheet(tester, 'Reserve');

    expect(find.text('Someone else has just taken this gift.'), findsOneWidget);
    expect(claimReads(), reads + 1);
    expect(roseChip(tester, 'Headphones')!.label, 'Reserved by Carol');
  });

  testWidgets('passed meanwhile: says so and offers nothing more',
      (tester) async {
    priced('Headphones');
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');
    server.passed.add(occasion);
    await tapInSheet(tester, 'Reserve');

    expect(
      find.text('This occasion has passed: nothing can be changed any more.'),
      findsOneWidget,
    );
    await openSheet(tester, 'Headphones');
    expect(sheetActions(tester), isEmpty);
  });

  testWidgets('a gift deleted meanwhile: says so and loads the page again',
      (tester) async {
    final gift = priced('Headphones');
    priced('Book');
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');
    server.gifts.remove(server.gift(gift));
    await tapInSheet(tester, 'Reserve');

    expect(
      find.text('This gift changed meanwhile. Check it and try again.'),
      findsOneWidget,
    );
    expect(find.widgetWithText(GiftCard, 'Headphones'), findsNothing);
    expect(find.widgetWithText(GiftCard, 'Book'), findsOneWidget);
  });

  testWidgets('a failure says so and changes nothing shown', (tester) async {
    final gift = priced('Headphones');
    server.status['POST /api/occasions/$occasion/gifts/$gift/reservation'] = 500;
    await startApp(tester, server, '/shared/$occasion');
    await openSheet(tester, 'Headphones');
    await tapInSheet(tester, 'Reserve');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );
    expect(roseChip(tester, 'Headphones'), isNull);
  });

  testWidgets('the activity failing to load says why and retries',
      (tester) async {
    priced('Headphones');
    server.status['GET /api/occasions/$occasion/claims'] = 500;
    await startApp(tester, server, '/shared/$occasion');

    expect(
      find.text('The server could not complete the request. Try again.'),
      findsOneWidget,
    );
    server.status.remove('GET /api/occasions/$occasion/claims');
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(GiftCard, 'Headphones'), findsOneWidget);
  });

  testWidgets('an owner is sent to the list; the activity is never asked',
      (tester) async {
    final mine = server.addList('Birthday');
    server.addGift(mine, 'Bike');
    final own = server.addOccasion(mine, 'Birthday 2026', '2026-06-01');
    await startApp(tester, server, '/shared/$own');

    expect(find.byType(ListDetailScreen), findsOneWidget);
    expect(server.calls.where((call) => call.endsWith('/claims')), isEmpty);
    expect(find.byType(StatusChip), findsNothing);
  });

  testWidgets('the sheet in French', (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    final gift = server.addGift(
      list,
      'Casque',
      priceAmount: '149.00',
      priceCurrency: 'EUR',
    );
    server.addClaim(gift, occasion, [
      FakeListsServer.giver('Carol', amount: '50.00', currency: 'EUR'),
      dan,
    ], group: true);
    await startApp(tester, server, '/shared/$occasion');

    expect(roseChip(tester, 'Casque')!.label, 'Cadeau commun · 2');
    await openSheet(tester, 'Casque');

    expect(sheetActions(tester), ['Rejoindre le cadeau commun']);
    expect(find.textContaining('promis sur'), findsOneWidget);
    await tapInSheet(tester, 'Rejoindre le cadeau commun');
    expect(find.text('Mon montant (facultatif)'), findsOneWidget);
    await tapInDialog(tester, 'Rejoindre');
    expect(roseChip(tester, 'Casque')!.label, 'Cadeau commun · 3');
  });
}
