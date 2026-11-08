import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/shared/shared_repository.dart';

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
}
