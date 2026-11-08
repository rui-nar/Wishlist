import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/shared/shared_repository.dart';

import '../lists/support/fake_lists_server.dart';
import '../support/fakes.dart';

const _shared = {
  'id': 'o1',
  'name': 'Christmas 2026',
  'date': '2026-12-24',
  'list_title': 'Christmas',
  'recipient_name': 'Léa',
  'owner_names': ['Bob Durand'],
};

void main() {
  late List<http.Request> seen;
  late Object answer;
  late int code;

  SharedRepository repository() => SharedRepository(
        ApiClient(
          MockClient((request) async {
            seen.add(request);
            return http.Response.bytes(
              utf8.encode(code == 204 ? '' : jsonEncode(answer)),
              code,
              headers: {'content-type': 'application/json'},
            );
          }),
          baseUrl: 'http://api.test',
        )..token = 't',
      );

  String sent(int index) => '${seen[index].method} ${seen[index].url.path}';

  setUp(() {
    seen = [];
    answer = {};
    code = 200;
  });

  test('shared reads the occasions joined', () async {
    answer = [_shared];

    final occasions = await repository().shared();

    expect(sent(0), 'GET /api/shared');
    final occasion = occasions.single;
    expect(occasion.id, 'o1');
    expect(occasion.date, DateTime(2026, 12, 24));
    expect(occasion.listTitle, 'Christmas');
    expect(occasion.recipientName, 'Léa');
    expect(occasion.ownerNames, ['Bob Durand']);
  });

  test('occasion: the invitee model, with its gifts', () async {
    answer = {
      ..._shared,
      'role': 'invitee',
      'gifts': [
        {
          'id': 'g1',
          'title': 'Headphones',
          'description': '',
          'links': ['https://shop.example/h'],
          'price_amount': '149.00',
          'price_currency': 'EUR',
        },
      ],
    };

    final view = await repository().occasion('o1');

    expect(sent(0), 'GET /api/occasions/o1');
    expect(view, isA<InviteeOccasion>());
    final invitee = view as InviteeOccasion;
    expect(invitee.occasion.name, 'Christmas 2026');
    expect(invitee.gifts.single.title, 'Headphones');
    expect(invitee.gifts.single.priceAmount, '149.00');
  });

  test('occasion: a gift keeps the occasion paths of its image, or none',
      () async {
    const gift = {
      'id': 'g1',
      'title': 'Headphones',
      'description': '',
      'links': <String>[],
      'price_amount': null,
      'price_currency': null,
    };
    answer = {
      ..._shared,
      'role': 'invitee',
      'gifts': [
        {
          ...gift,
          'image': {
            'id': 'i1',
            'width': 800,
            'height': 600,
            'url': '/api/occasions/o1/images/i1/full',
            'thumb_url': '/api/occasions/o1/images/i1/thumb',
          },
        },
        {...gift, 'id': 'g2', 'image': null},
        {...gift, 'id': 'g3'},
      ],
    };

    final view = await repository().occasion('o1') as InviteeOccasion;

    expect(view.gifts[0].image!.url, '/api/occasions/o1/images/i1/full');
    expect(view.gifts[0].image!.thumbUrl, '/api/occasions/o1/images/i1/thumb');
    expect(view.gifts[1].image, isNull);
    expect(view.gifts[2].image, isNull);
  });

  test("occasion: an owner's answer names the list to open", () async {
    answer = {
      'id': 'o1',
      'list_id': 'l1',
      'name': 'Christmas 2026',
      'date': '2026-12-24',
      'join_token': 'tok',
      'member_count': 2,
      'role': 'owner',
      'list': {
        'id': 'l1',
        'title': 'Christmas',
        'recipient_kind': 'other',
        'recipient_name': 'Léa',
      },
      'gifts': [],
    };

    final view = await repository().occasion('o1');

    expect(view, isA<OwnedOccasion>());
    expect((view as OwnedOccasion).listId, 'l1');
  });

  test('the token goes in the body, never in the URL', () async {
    answer = {
      ..._shared,
      'role': 'none',
      'list_id': null,
      'occasion_id': null,
    }..remove('id');
    final preview = await repository().preview('secret-token');
    answer = {'occasion_id': 'o1'};
    final joined = await repository().join('secret-token');

    expect(sent(0), 'POST /api/join/preview');
    expect(sent(1), 'POST /api/join');
    for (final request in seen) {
      expect(request.url.toString(), isNot(contains('secret-token')));
      expect(jsonDecode(request.body), {'token': 'secret-token'});
    }
    expect(preview.role, JoinRole.none);
    expect(preview.listId, isNull);
    expect(preview.occasionId, isNull);
    expect(preview.ownerNames, ['Bob Durand']);
    expect((joined as Joined).occasionId, 'o1');
  });

  test('preview roles: owner with the list, member with the occasion',
      () async {
    final common = {..._shared}..remove('id');
    answer = {...common, 'role': 'owner', 'list_id': 'l1', 'occasion_id': null};
    final owner = await repository().preview('t');
    answer = {...common, 'role': 'member', 'list_id': null, 'occasion_id': 'o1'};
    final member = await repository().preview('t');

    expect(owner.role, JoinRole.owner);
    expect(owner.listId, 'l1');
    expect(member.role, JoinRole.member);
    expect(member.occasionId, 'o1');
  });

  test('a 409 on join: the user owns the list, which it names', () async {
    code = 409;
    answer = {'detail': 'You own this list', 'list_id': 'l1'};

    final outcome = await repository().join('t');

    expect(outcome, isA<OwnsList>());
    expect((outcome as OwnsList).listId, 'l1');
  });

  test('a 404 on join is an error, for the screen to explain', () async {
    code = 404;
    answer = {'detail': 'Not Found'};

    await expectLater(
      repository().join('t'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 404)),
    );
  });

  test('leave deletes the membership; ids are one path segment', () async {
    code = 204;

    await repository().leave('a/../b');

    expect(seen.single.method, 'DELETE');
    expect(seen.single.url.path, '/api/occasions/a%2F..%2Fb/membership');
  });

  test('a 409 with a code no client knows stays an ApiException', () async {
    code = 409;
    answer = {'detail': 'Something new', 'code': 'later'};

    await expectLater(
      repository().reserve('o1', 'g1'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 409)),
    );
  });

  test('claim ids are one path segment each', () async {
    code = 204;

    await repository().release('a/b', 'c?d');

    expect(
      seen.single.url.path,
      '/api/occasions/a%2Fb/gifts/c%3Fd/reservation',
    );
  });

  group('activity, against the fake server (RESERVING_PLAN D6)', () {
    late FakeListsServer server;
    late SharedRepository shared;
    late String occasion;
    late String other;
    late String priced;
    late String unpriced;

    String path(String gift, String action) =>
        '/api/occasions/$occasion/gifts/$gift/$action';

    setUp(() {
      server = FakeListsServer();
      final list = server.addList(
        'Christmas',
        recipientName: 'Léa',
        ownerNames: ['Bob Durand'],
      );
      priced = server.addGift(
        list,
        'Headphones',
        priceAmount: '149.00',
        priceCurrency: 'EUR',
      );
      unpriced = server.addGift(list, 'Socks');
      occasion = server.addOccasion(list, 'Christmas 2026', '2026-12-24');
      other = server.addOccasion(list, 'Birthday', '2027-03-02');
      server.joined.add(occasion);
      shared = SharedRepository(
        ApiClient(server.client, baseUrl: kApiBase)
          ..token = server.accounts.addSession(),
      );
    });

    test('claims: passed, the states, the participants and their pledges',
        () async {
      server
        ..addClaim(priced, occasion, [
          FakeListsServer.giver('Carol', amount: '50.00', currency: 'EUR'),
          FakeListsServer.giver(kAliceName, mine: true),
        ], group: true)
        ..addClaim(unpriced, other, [FakeListsServer.giver('Eve')]);

      final claims = await shared.claims(occasion);

      expect(server.calls.single, 'GET /api/occasions/$occasion/claims');
      expect(claims.passed, isFalse);
      final group = claims.gifts[priced]!;
      expect(group.state, ClaimState.group);
      expect(group.bought, isFalse);
      expect(group.mine, isTrue);
      expect(group.participants.first.displayName, 'Carol');
      expect(group.participants.first.mine, isFalse);
      expect(group.participants.first.pledgeAmount, '50.00');
      expect(group.participants.first.pledgeCurrency, 'EUR');
      expect(group.participants.last.pledgeAmount, isNull);
      final taken = claims.gifts[unpriced]!;
      expect(taken.state, ClaimState.taken);
      expect(taken.participants, isEmpty);
      expect(taken.mine, isFalse);
    });

    test('a free gift is absent; a passed occasion says so', () async {
      server.passed.add(occasion);

      final claims = await shared.claims(occasion);

      expect(claims.passed, isTrue);
      expect(claims.gifts, isEmpty);
    });

    test('each write: its method and path, a body only for the pledge',
        () async {
      final pledge = 'PUT ${path(priced, 'pledge')}';
      await shared.reserve(occasion, priced);
      await shared.release(occasion, priced);
      await shared.markBought(occasion, unpriced);
      await shared.pledge(occasion, priced, '50.00');
      expect(server.bodies[pledge], {'amount': '50.00'});
      await shared.pledge(occasion, priced, null);
      expect(server.bodies[pledge], {'amount': null});
      await shared.leaveGroup(occasion, priced);

      expect(server.calls, [
        'POST ${path(priced, 'reservation')}',
        'DELETE ${path(priced, 'reservation')}',
        'POST ${path(unpriced, 'bought')}',
        pledge,
        pledge,
        'DELETE ${path(priced, 'pledge')}',
      ]);
      expect(server.bodies.keys, [pledge]);
      expect(server.claims.containsKey(priced), isFalse);
      expect(server.claims[unpriced]!['bought'], isTrue);
    });

    test('a 409 surfaces its code: taken, bought, passed', () async {
      server
        ..addClaim(priced, occasion, [FakeListsServer.giver('Carol')])
        ..addClaim(
          unpriced,
          occasion,
          [FakeListsServer.giver(kAliceName, mine: true)],
          bought: true,
        );
      Matcher conflict(ClaimConflictCode code) =>
          throwsA(isA<ClaimConflict>().having((e) => e.code, 'code', code));

      await expectLater(
        shared.reserve(occasion, priced),
        conflict(ClaimConflictCode.taken),
      );
      await expectLater(
        shared.pledge(occasion, priced, null),
        conflict(ClaimConflictCode.taken),
      );
      await expectLater(
        shared.release(occasion, unpriced),
        conflict(ClaimConflictCode.bought),
      );
      server.passed.add(occasion);
      await expectLater(
        shared.leaveGroup(occasion, priced),
        conflict(ClaimConflictCode.passed),
      );
    });

    test('release and leave hold nothing: done all the same', () async {
      await shared.release(occasion, priced);
      await shared.leaveGroup(occasion, priced);

      expect(server.claims, isEmpty);
    });

    test('an amount on a gift without a price is an ApiException 422',
        () async {
      await expectLater(
        shared.pledge(occasion, unpriced, '10.00'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 422)),
      );
    });
  });
}
