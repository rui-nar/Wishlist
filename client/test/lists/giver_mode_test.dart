import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/design/widgets/gift_card.dart';
import 'package:wishlist/src/design/widgets/privacy_banner.dart';
import 'package:wishlist/src/design/widgets/status_chip.dart';
import 'package:wishlist/src/lists/list_detail_screen.dart';
import 'package:wishlist/src/lists/occasion_members_screen.dart';
import 'package:wishlist/src/shared/occasion_screen.dart';

import 'support/fake_lists_server.dart';

/// The owners of a list for someone else give like invitees, from each
/// occasion of the list; the owner of a list for themselves, the recipient,
/// sees and asks for nothing of it (RESERVING_PLAN D4, D14).
void main() {
  late FakeListsServer server;

  final carol = FakeListsServer.giver('Carol');
  final alice = FakeListsServer.giver(kAliceName, mine: true);

  setUp(() => server = FakeListsServer());

  /// The activity routes: an occasion's claims and every write on a gift of
  /// it (D6).
  List<String> activityCalls() => [
        for (final call in server.calls)
          if (RegExp(r'^\w+ /api/occasions/[^/]+/(claims$|gifts/)')
              .hasMatch(call))
            call,
      ];

  /// Every rose chip on screen: invitee activity.
  Iterable<StatusChip> roseChips(WidgetTester tester) => tester
      .widgetList<StatusChip>(find.byType(StatusChip))
      .where((chip) => chip.variant == StatusChipVariant.inviteeActivity);

  /// The activity chip of the gift titled [title], or null without one.
  StatusChip? roseChip(WidgetTester tester, String title) {
    final card = tester.widget<GiftCard>(find.widgetWithText(GiftCard, title));
    return card.chips
        .whereType<StatusChip>()
        .where((chip) => chip.variant == StatusChipVariant.inviteeActivity)
        .firstOrNull;
  }

  Future<void> tapVisible(WidgetTester tester, Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
  }

  final giftsButton = find.widgetWithText(
    OutlinedButton,
    'Gifts and reservations',
  );

  group('a list for someone else', () {
    late String list;
    late String occasion;
    late String headphones;
    late String book;

    setUp(() {
      list = server.addList('Christmas', recipientName: 'Léa');
      headphones = server.addGift(
        list,
        'Headphones',
        priceAmount: '149.00',
        priceCurrency: 'EUR',
      );
      book = server.addGift(list, 'Book');
      occasion = server.addOccasion(
        list,
        'Christmas 2026',
        '2026-12-24',
        invitees: ['Carol'],
      );
      server.addOccasion(list, 'Birthday', '2027-03-02');
      server.addClaim(book, occasion, [carol]);
    });

    testWidgets('each occasion card opens its gifts and reservations',
        (tester) async {
      await startApp(tester, server, '/lists/$list');

      expect(giftsButton, findsNWidgets(2));
      // The list detail itself shows no activity (Open decisions).
      expect(activityCalls(), isEmpty);
      expect(roseChips(tester), isEmpty);

      await tapVisible(tester, giftsButton.first);

      expect(find.byType(OccasionScreen), findsOneWidget);
      expect(
        server.calls,
        contains('GET /api/occasions/$occasion/claims'),
      );
    });

    testWidgets('giver mode: who it is for, the banner, the chips, no leave',
        (tester) async {
      server.addClaim(headphones, occasion, [carol, alice], group: true);
      await startApp(tester, server, '/lists/$list/occasions/$occasion');

      expect(find.text('Christmas'), findsOneWidget);
      expect(find.text('Christmas 2026'), findsOneWidget);
      expect(find.text('For Léa'), findsOneWidget);
      expect(
        find.widgetWithText(PrivacyBanner, "Léa doesn't see what you do here"),
        findsOneWidget,
      );
      expect(roseChip(tester, 'Book')!.label, 'Reserved by Carol');
      expect(roseChip(tester, 'Headphones')!.label, 'Group gift · 2');
      // An owner is no member: nothing to leave.
      expect(find.byIcon(Icons.more_vert), findsNothing);
      expect(find.text('Leave the occasion'), findsNothing);
    });

    testWidgets('giver mode acts like an invitee and loads the claims again',
        (tester) async {
      await startApp(tester, server, '/lists/$list/occasions/$occasion');
      await tester.tap(find.widgetWithText(GiftCard, 'Headphones'));
      await tester.pumpAndSettle();
      final reads = server.calls
          .where((call) => call == 'GET /api/occasions/$occasion/claims')
          .length;
      await tester.tap(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.text('Reserve'),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        server.calls,
        contains('POST /api/occasions/$occasion/gifts/$headphones/reservation'),
      );
      expect(
        server.calls
            .where((call) => call == 'GET /api/occasions/$occasion/claims')
            .length,
        reads + 1,
      );
      expect(roseChip(tester, 'Headphones')!.label, 'Reserved by you');

      // A group gift, from the same sheet and dialog.
      final socks = server.addGift(list, 'Socks');
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tapVisible(tester, giftsButton.first);
      await tapVisible(tester, find.widgetWithText(GiftCard, 'Socks'));
      await tester.tap(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.text('Start a group gift'),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Start'),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        server.bodies['PUT /api/occasions/$occasion/gifts/$socks/pledge'],
        {'amount': null},
      );
      expect(roseChip(tester, 'Socks')!.label, 'Group gift · 1');
    });

    testWidgets('/shared/:id still sends an owner to the list',
        (tester) async {
      await startApp(tester, server, '/shared/$occasion');

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(activityCalls(), isEmpty);
    });

    testWidgets('an occasion of another list is not found there',
        (tester) async {
      final other = server.addList('Birthday', recipientName: 'Tom');
      await startApp(tester, server, '/lists/$other/occasions/$occasion');

      expect(find.text('This occasion no longer exists.'), findsOneWidget);
      expect(roseChips(tester), isEmpty);
      expect(activityCalls(), isEmpty);
    });

    testWidgets('an occasion that is gone says so and goes back to the list',
        (tester) async {
      await startApp(tester, server, '/lists/$list/occasions/missing');

      expect(find.text('This occasion no longer exists.'), findsOneWidget);
      await tester.tap(find.text('Back to the list'));
      await tester.pumpAndSettle();
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await startApp(tester, server, '/lists/$list');

      expect(
        find.widgetWithText(OutlinedButton, 'Cadeaux et réservations'),
        findsNWidgets(2),
      );
      await tapVisible(
        tester,
        find.widgetWithText(OutlinedButton, 'Cadeaux et réservations').first,
      );
      expect(roseChip(tester, 'Book')!.label, 'Réservé par Carol');
    });
  });

  group('a list for me: nothing of the activity', () {
    late String list;
    late String occasion;

    setUp(() {
      list = server.addList('Birthday');
      final gift = server.addGift(list, 'Bike');
      final group = server.addGift(list, 'Tent');
      occasion = server.addOccasion(
        list,
        'Birthday 2026',
        '2026-06-01',
        token: 'tok',
        invitees: ['Carol', 'Dan'],
      );
      final other = server.addOccasion(list, 'Christmas', '2026-12-24');
      // Activity the recipient must never see nor ask for.
      server
        ..addClaim(gift, occasion, [carol], bought: true)
        ..addClaim(group, other, [carol], group: true);
    });

    testWidgets('no action, no request, no rose chip on the list, its '
        'occasion cards and /shared/:id', (tester) async {
      await startApp(tester, server, '/lists/$list');

      expect(giftsButton, findsNothing);
      expect(roseChips(tester), isEmpty);

      // Each occasion card's own screens.
      await tapVisible(
        tester,
        find.widgetWithText(OutlinedButton, 'Invitees').first,
      );
      expect(find.byType(OccasionMembersScreen), findsOneWidget);
      expect(roseChips(tester), isEmpty);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tapVisible(tester, find.byTooltip('Occasion actions').first);
      expect(find.text('Gifts and reservations'), findsNothing);
      await tester.tapAt(Offset.zero);
      await tester.pumpAndSettle();

      await startApp(tester, server, '/shared/$occasion');
      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(roseChips(tester), isEmpty);

      expect(activityCalls(), isEmpty);
    });

    testWidgets('the giver route goes to the list without asking',
        (tester) async {
      await startApp(tester, server, '/lists/$list/occasions/$occasion');

      expect(find.byType(ListDetailScreen), findsOneWidget);
      expect(find.byType(OccasionScreen), findsNothing);
      expect(find.byType(PrivacyBanner), findsNothing);
      expect(roseChips(tester), isEmpty);
      expect(activityCalls(), isEmpty);
    });
  });

  testWidgets("an invitee on an owner's location goes to the occasion",
      (tester) async {
    final list = server.addList(
      'Christmas',
      recipientName: 'Léa',
      ownerNames: ['Bob Durand'],
    );
    final book = server.addGift(list, 'Book');
    final occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
    server
      ..joined.add(occasion)
      ..addClaim(book, occasion, [carol]);
    await startApp(tester, server, '/lists/$list/occasions/$occasion');

    expect(find.byType(OccasionScreen), findsOneWidget);
    expect(find.text('For Léa · shared by Bob Durand'), findsOneWidget);
    expect(roseChip(tester, 'Book')!.label, 'Reserved by Carol');
    // The invitee's page, with its menu to leave.
    expect(find.byIcon(Icons.more_vert), findsOneWidget);
    // Asked once, from the occasion under Shared with me.
    expect(
      server.calls.where((call) => call.endsWith('/claims')).length,
      1,
    );
  });
}
