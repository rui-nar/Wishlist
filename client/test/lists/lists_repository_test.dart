import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shushgift/src/api/api_client.dart';
import 'package:shushgift/src/lists/lists_repository.dart';

const _gift = {
  'id': 'g1',
  'list_id': 'l1',
  'title': 'Headphones',
  'description': 'Black',
  'links': ['https://shop.example/h'],
  'price_amount': '149.00',
  'price_currency': 'EUR',
};

void main() {
  late List<http.Request> seen;
  late Object answer;
  late int code;

  ListsRepository repository() => ListsRepository(
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
  Object? body(int index) => jsonDecode(seen[index].body);

  setUp(() {
    seen = [];
    answer = {};
    code = 200;
  });

  test('myLists reads the summaries, an occasion count or not', () async {
    answer = [
      {
        'id': 'l1',
        'title': 'Birthday',
        'recipient_kind': 'self',
        'recipient_name': null,
        'gift_count': 3,
      },
      {
        'id': 'l2',
        'title': 'Léa',
        'recipient_kind': 'other',
        'recipient_name': 'Léa',
        'gift_count': 0,
        'occasion_count': 1,
      },
    ];

    final lists = await repository().myLists();

    expect(sent(0), 'GET /api/lists');
    expect(seen[0].headers['Authorization'], 'Bearer t');
    expect(lists.map((list) => list.id), ['l1', 'l2']);
    expect(lists[0].recipientKind, RecipientKind.self);
    expect(lists[0].recipientName, isNull);
    expect(lists[0].giftCount, 3);
    expect(lists[1].recipientKind, RecipientKind.other);
    expect(lists[1].recipientName, 'Léa');
  });

  test('createList sends the kind, and a name only for someone else',
      () async {
    code = 201;
    answer = {'id': 'new'};

    expect(
      await repository().createList(
        title: 'Mine',
        recipientKind: RecipientKind.self,
        recipientName: 'ignored',
      ),
      'new',
    );
    await repository().createList(
      title: 'Hers',
      recipientKind: RecipientKind.other,
      recipientName: 'Léa',
    );

    expect(sent(0), 'POST /api/lists');
    expect(body(0), {'title': 'Mine', 'recipient_kind': 'self'});
    expect(body(1), {
      'title': 'Hers',
      'recipient_kind': 'other',
      'recipient_name': 'Léa',
    });
  });

  test('list reads the list and its gifts, prices as strings', () async {
    answer = {
      'id': 'l1',
      'title': 'Birthday',
      'recipient_kind': 'self',
      'recipient_name': null,
      'gifts': [
        _gift,
        {..._gift, 'id': 'g2', 'links': [], 'price_amount': null,
          'price_currency': null},
      ],
      'occasions': [],
    };

    final list = await repository().list('l1');

    expect(sent(0), 'GET /api/lists/l1');
    expect(list.title, 'Birthday');
    expect(list.gifts.map((gift) => gift.id), ['g1', 'g2']);
    final gift = list.gifts.first;
    expect(gift.listId, 'l1');
    expect(gift.description, 'Black');
    expect(gift.links, ['https://shop.example/h']);
    expect(gift.priceAmount, '149.00');
    expect(gift.priceCurrency, 'EUR');
    expect(list.gifts[1].priceAmount, isNull);
    // A server older than hidden gifts sends neither.
    expect(list.received, isEmpty);
    expect(list.revealed, isEmpty);
  });

  test('list reads the received and revealed gifts, in their order',
      () async {
    answer = {
      'id': 'l1',
      'title': 'Birthday',
      'recipient_kind': 'self',
      'recipient_name': null,
      'gifts': [],
      'occasions': [],
      'received': [
        {..._gift, 'id': 'r2'},
        {..._gift, 'id': 'r1'},
      ],
      'revealed': [
        {..._gift, 'id': 'v1', 'title': 'A scarf'},
      ],
    };

    final list = await repository().list('l1');

    expect(list.received.map((gift) => gift.id), ['r2', 'r1']);
    expect(list.revealed.single.title, 'A scarf');
    expect(list.revealed.single.listId, 'l1');
  });

  group('received and revealed gifts', () {
    test('markReceived, putBack and keep: their paths, bodies and answers',
        () async {
      code = 204;
      await repository().markReceived('g1');
      await repository().putBack('g1');
      await repository().deleteGift('g2');
      code = 200;
      answer = {..._gift, 'id': 'g9'};
      final kept = await repository().keep('g3');

      expect(sent(0), 'POST /api/gifts/g1/received');
      expect(seen[0].body, isEmpty);
      expect(sent(1), 'DELETE /api/gifts/g1/received');
      expect(seen[1].body, isEmpty);
      expect(sent(2), 'DELETE /api/gifts/g2');
      expect(sent(3), 'POST /api/gifts/g3/keep');
      expect(body(3), <String, dynamic>{});
      expect(kept.id, 'g9');
      expect(kept.title, 'Headphones');
    });

    test('a 409 not_revealed on put back or keep is NotRevealed', () async {
      code = 409;
      answer = {'detail': 'Not revealed', 'code': 'not_revealed'};

      await expectLater(
        repository().putBack('g1'),
        throwsA(isA<NotRevealed>()),
      );
      await expectLater(repository().keep('g1'), throwsA(isA<NotRevealed>()));
    });

    group('the free plan limit (PREMIUM_PLAN D4)', () {
      Matcher limit(PlanLimitResource resource, int limit) => throwsA(
            isA<PlanLimitReached>()
                .having((e) => e.resource, 'resource', resource)
                .having((e) => e.limit, 'limit', limit),
          );

      const draft = GiftDraft(title: 'Book');

      Future<Object?> createList() => repository().createList(
            title: 'Birthday',
            recipientKind: RecipientKind.self,
          );

      test('a 402 plan_limit on the four growing calls is PlanLimitReached',
          () async {
        code = 402;
        answer = {
          'detail': "The free plan's limit is reached",
          'code': 'plan_limit',
          'resource': 'lists',
          'limit': 1,
        };
        await expectLater(createList(), limit(PlanLimitResource.lists, 1));

        answer = {
          'detail': "The free plan's limit is reached",
          'code': 'plan_limit',
          'resource': 'gifts',
          'limit': 20,
        };
        final gifts = limit(PlanLimitResource.gifts, 20);
        await expectLater(repository().addGift('l1', draft), gifts);
        await expectLater(repository().putBack('g1'), gifts);
        await expectLater(repository().keep('g1'), gifts);
      });

      for (final (name, refusal) in <(String, Object)>[
        ('another code', {'detail': 'Pay', 'code': 'other'}),
        ('no code', {'detail': 'Pay'}),
        (
          'a resource it does not know',
          {'detail': 'Pay', 'code': 'plan_limit', 'resource': 'x', 'limit': 1},
        ),
        (
          'no limit',
          {'detail': 'Pay', 'code': 'plan_limit', 'resource': 'gifts'},
        ),
      ]) {
        test('a 402 with $name stays the ApiClient one', () async {
          code = 402;
          answer = refusal;
          final failure = throwsA(
            isA<ApiException>().having((e) => e.statusCode, 'statusCode', 402),
          );
          await expectLater(createList(), failure);
          await expectLater(repository().addGift('l1', draft), failure);
          await expectLater(repository().putBack('g1'), failure);
          await expectLater(repository().keep('g1'), failure);
        });
      }

      test('plan_limit on another status stays the ApiClient one', () async {
        code = 403;
        answer = {'code': 'plan_limit', 'resource': 'lists', 'limit': 1};
        await expectLater(createList(), throwsA(isA<ApiException>()));
      });
    });

    test('any other error stays the ApiClient one', () async {
      code = 409;
      answer = {'detail': 'Refused', 'code': 'other'};
      await expectLater(
        repository().putBack('g1'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 409)),
      );
      code = 404;
      answer = {'detail': 'Not found'};
      await expectLater(
        repository().keep('g1'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 404)),
      );
    });

    test('ids are one path segment', () async {
      code = 204;
      await repository().markReceived('a/b');
      await repository().putBack('a/b');

      expect(seen[0].url.path, '/api/gifts/a%2Fb/received');
      expect(seen[1].url.path, '/api/gifts/a%2Fb/received');
    });
  });

  test('updateList patches the title, and the name when given', () async {
    answer = {};

    await repository().updateList('l1', title: 'New');
    await repository().updateList('l2', title: 'Hers', recipientName: 'Léa');

    expect(sent(0), 'PATCH /api/lists/l1');
    expect(body(0), {'title': 'New'});
    expect(body(1), {'title': 'Hers', 'recipient_name': 'Léa'});
  });

  test('gift calls send every field, so an edit can clear one', () async {
    code = 201;
    answer = _gift;
    const draft = GiftDraft(title: 'Book');

    final added = await repository().addGift('l1', draft);
    code = 200;
    await repository().updateGift('g1', draft);

    expect(added.id, 'g1');
    expect(sent(0), 'POST /api/lists/l1/gifts');
    expect(sent(1), 'PATCH /api/gifts/g1');
    for (final index in [0, 1]) {
      expect(body(index), {
        'title': 'Book',
        'description': '',
        'links': <String>[],
        'price_amount': null,
        'price_currency': null,
      });
    }
  });

  group('gift images', () {
    const image = {
      'id': 'i1',
      'width': 800,
      'height': 600,
      'url': '/api/images/i1/full',
      'thumb_url': '/api/images/i1/thumb',
    };

    test('a gift parses with and without an image', () async {
      answer = {
        'id': 'l1',
        'title': 'Birthday',
        'recipient_kind': 'self',
        'recipient_name': null,
        'gifts': [
          {..._gift, 'image': image},
          {..._gift, 'id': 'g2', 'image': null},
          {..._gift, 'id': 'g3'},
        ],
        'occasions': [],
      };

      final gifts = (await repository().list('l1')).gifts;

      expect(gifts[0].image!.id, 'i1');
      expect(gifts[0].image!.width, 800);
      expect(gifts[0].image!.height, 600);
      expect(gifts[0].image!.url, '/api/images/i1/full');
      expect(gifts[0].image!.thumbUrl, '/api/images/i1/thumb');
      expect(gifts[1].image, isNull);
      expect(gifts[2].image, isNull);
    });

    test('a draft sends no image_id when unchanged, null on remove, the id '
        'on attach', () async {
      code = 201;
      answer = _gift;
      const base = GiftDraft(title: 'Book');
      const attach = GiftDraft(title: 'Book', imageChange: AttachImage('i2'));
      const remove = GiftDraft(title: 'Book', imageChange: RemoveImage());

      await repository().addGift('l1', base);
      await repository().addGift('l1', attach);
      await repository().updateGift('g1', remove);

      expect((body(0) as Map).containsKey('image_id'), isFalse);
      expect((body(1) as Map)['image_id'], 'i2');
      expect((body(2) as Map).containsKey('image_id'), isTrue);
      expect((body(2) as Map)['image_id'], isNull);
    });

    test('a gift read from the server sends no image_id when saved again',
        () {
      expect(
        Gift.fromJson({..._gift, 'image': image}).toJson(),
        isNot(contains('image_id')),
      );
    });

    test('uploadImage sends the bytes and reads the pending image', () async {
      code = 201;
      answer = image;

      final pending =
          await repository().uploadImage(Uint8List.fromList([1, 2]));

      expect(sent(0), 'POST /api/images');
      expect(seen[0].bodyBytes, [1, 2]);
      expect(pending.id, 'i1');
      expect(pending.thumbUrl, '/api/images/i1/thumb');
    });

    test('an upload the server refuses carries its code', () async {
      code = 422;
      answer = {'detail': 'image_unsupported'};

      await expectLater(
        repository().uploadImage(Uint8List(1)),
        throwsA(isA<ApiException>()
            .having((e) => e.body?['detail'], 'detail', 'image_unsupported')),
      );
    });

    testWidgets('imageFromUrl waits past 10 s for the server (review R1-5)',
        (tester) async {
      final api = ApiClient(
        MockClient((request) async {
          seen.add(request);
          await Future<void>.delayed(const Duration(seconds: 25));
          return http.Response(jsonEncode(image), 201);
        }),
        baseUrl: 'http://api.test',
      );
      PendingImage? pending;
      ListsRepository(api)
          .imageFromUrl('https://shop.example/h.jpg')
          .then((value) => pending = value);

      await tester.pump(const Duration(seconds: 26));

      expect(pending?.id, 'i1');
      expect(sent(0), 'POST /api/images/from-url');
      expect(body(0), {'url': 'https://shop.example/h.jpg'});
    });
  });

  test('deletes answer 204', () async {
    code = 204;

    await repository().deleteList('l1');
    await repository().deleteGift('g1');

    expect(sent(0), 'DELETE /api/lists/l1');
    expect(sent(1), 'DELETE /api/gifts/g1');
  });

  test('an id is one path segment, whatever it holds', () async {
    answer = {};

    await repository().updateList('a/../b?x=1#y', title: 'T');

    expect(seen.single.url.path, '/api/lists/a%2F..%2Fb%3Fx%3D1%23y');
    expect(seen.single.url.query, isEmpty);
  });

  test('occasion calls: their paths, bodies and answers', () async {
    const occasion = {
      'id': 'o1',
      'list_id': 'l1',
      'name': 'Christmas 2026',
      'date': '2026-12-24',
      'join_token': 'tok',
      'member_count': 2,
    };
    code = 201;
    answer = occasion;
    final created = await repository().createOccasion(
      'l1',
      name: 'Christmas 2026',
      date: DateTime(2026, 12, 24),
    );
    code = 200;
    await repository().updateOccasion(
      'o1',
      name: 'Noël',
      date: DateTime(2026, 1, 5),
    );
    await repository().createLink('o1');
    answer = [
      {'user_id': 'u1', 'display_name': 'Carol', 'removed': false},
      {'user_id': 'u2', 'display_name': 'Dan', 'removed': true},
    ];
    final members = await repository().members('o1');
    code = 204;
    await repository().revokeLink('o1');
    await repository().removeMember('o1', 'u1');
    await repository().allowAgain('o1', 'u2');
    await repository().deleteOccasion('o1');

    expect(sent(0), 'POST /api/lists/l1/occasions');
    expect(body(0), {'name': 'Christmas 2026', 'date': '2026-12-24'});
    expect(created.date, DateTime(2026, 12, 24));
    expect(created.joinToken, 'tok');
    expect(created.memberCount, 2);
    expect(sent(1), 'PATCH /api/occasions/o1');
    expect(body(1), {'name': 'Noël', 'date': '2026-01-05'});
    expect(sent(2), 'POST /api/occasions/o1/link');
    expect(sent(3), 'GET /api/occasions/o1/members');
    expect(members.map((m) => (m.displayName, m.removed)), [
      ('Carol', false),
      ('Dan', true),
    ]);
    expect(sent(4), 'DELETE /api/occasions/o1/link');
    expect(sent(5), 'DELETE /api/occasions/o1/members/u1');
    expect(sent(6), 'DELETE /api/occasions/o1/removals/u2');
    expect(sent(7), 'DELETE /api/occasions/o1');
  });

  test('a list that is gone or not mine is a 404', () async {
    code = 404;

    await expectLater(
      repository().list('l1'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 404)),
    );
  });
}
