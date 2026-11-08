import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/lists/lists_repository.dart';

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

  test('a list that is gone or not mine is a 404', () async {
    code = 404;

    await expectLater(
      repository().list('l1'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 404)),
    );
  });
}
