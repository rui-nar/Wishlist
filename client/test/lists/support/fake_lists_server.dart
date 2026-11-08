/// The server's list, gift, occasion and join endpoints in memory, on top of
/// [FakeServer]'s account endpoints, and the app against both.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/shared/pending_join.dart';

import '../../support/fakes.dart';

/// A valid 8 x 8 PNG (two blue and two orange squares) every image of
/// [FakeListsServer] serves, whatever the variant.
final kTestImage = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAHElEQVR4nGOwbvoGR1/nccMR'
  'AxUlkDnIiqgoAQB9j2ohclFlTgAAAABJRU5ErkJggg==',
);

/// The signed-in user's display name, as the server gives it to others.
const kAliceName = 'Alice Martin';

/// Lists, gifts, occasions and joining for the signed-in user, Alice
/// (LISTS_GIFTS_SHARING_PLAN D8). Any other call goes to [accounts].
/// [status] forces an answer for `'<METHOD> <path>'`, with the error code in
/// [details] as its body when there is one; while [hold] is set, these calls
/// wait for it.
///
/// [lists] are Alice's own. [otherLists] belong to someone else, named in
/// [otherOwners]: Alice sees their occasions only as a member ([joined]).
class FakeListsServer {
  FakeListsServer() : accounts = FakeServer();

  final FakeServer accounts;

  /// Id → the list as `ListOut` gives it.
  final lists = <String, Map<String, dynamic>>{};

  /// Every gift, oldest first, as `GiftOut` gives it.
  final gifts = <Map<String, dynamic>>[];

  /// Lists Alice does not own, by id, as `ListOut` gives them.
  final otherLists = <String, Map<String, dynamic>>{};

  /// The owners' names of each of [otherLists].
  final otherOwners = <String, List<String>>{};

  /// Id → the occasion: `id`, `list_id`, `name`, `date`, `join_token`.
  final occasions = <String, Map<String, dynamic>>{};

  /// Occasion id → its invitees (`user_id`, `display_name`), in the order
  /// they joined. Alice is not among them: see [joined].
  final members = <String, List<Map<String, String>>>{};

  /// Every invitee ever added, by user id → display name: the server still
  /// knows someone who left.
  final names = <String, String>{};

  /// Occasion id → the people its owner removed.
  final removed = <String, List<Map<String, String>>>{};

  /// The occasions Alice joined.
  final joined = <String>{};

  /// The occasions whose owner removed Alice.
  final aliceRemoved = <String>{};

  /// Gift id → its claim (RESERVING_PLAN D1, D2): `occasion_id` (null once
  /// its occasion was deleted), `kind` (`reservation` or `group`), `bought`
  /// and `participants`, each as [giver] makes it, by when they joined.
  final claims = <String, Map<String, dynamic>>{};

  /// The occasions whose date has passed (D8).
  final passed = <String>{};

  final status = <String, int>{};

  /// `'<METHOD> <path>'` → the `detail` code of the answer [status] forces
  /// (GIFT_IMAGES D11).
  final details = <String, String>{};

  /// Image id → its `{id, width, height}`: pending ones (uploaded, not yet
  /// attached) and attached ones. The paths are made when it is shown, as
  /// the server does (GIFT_IMAGES D7).
  final images = <String, Map<String, dynamic>>{};

  /// The bytes of every `POST /api/images`.
  final uploads = <Uint8List>[];

  /// Every call to these endpoints, as `'<METHOD> <path>'`.
  final calls = <String>[];

  /// The JSON body of every call to these endpoints, by
  /// `'<METHOD> <path>'`.
  final bodies = <String, Map<String, dynamic>>{};

  Completer<void>? hold;
  int _next = 0;

  late final http.Client client = MockClient(_handle);

  /// A list of Alice's; someone else's, owned by [ownerNames], when given.
  String addList(
    String title, {
    String? recipientName,
    List<String>? ownerNames,
  }) {
    final id = 'list-${_next++}';
    final list = <String, dynamic>{
      'id': id,
      'title': title,
      'recipient_kind': recipientName == null ? 'self' : 'other',
      'recipient_name': recipientName,
    };
    if (ownerNames == null) {
      lists[id] = list;
    } else {
      otherLists[id] = list;
      otherOwners[id] = ownerNames;
    }
    return id;
  }

  String addGift(
    String listId,
    String title, {
    String description = '',
    List<String> links = const [],
    String? priceAmount,
    String? priceCurrency,
    bool image = false,
  }) {
    final id = 'gift-${_next++}';
    gifts.add({
      'id': id,
      'list_id': listId,
      'title': title,
      'description': description,
      'links': links,
      'price_amount': priceAmount,
      'price_currency': priceCurrency,
      if (image) 'image': _ownerImage(addImage()),
    });
    return id;
  }

  /// A new image on the server; returns its id.
  String addImage() {
    final id = 'image-${_next++}';
    images[id] = {'id': id, 'width': 8, 'height': 8};
    return id;
  }

  /// An image as its list's owners see it: `/api/images/...` paths.
  Map<String, dynamic> _ownerImage(String id) => {
        ...images[id]!,
        'url': '/api/images/$id/full',
        'thumb_url': '/api/images/$id/thumb',
      };

  /// An image as an occasion's invitees see it.
  Map<String, dynamic> _inviteeImage(String occasionId, String id) => {
        ...images[id]!,
        'url': '/api/occasions/$occasionId/images/$id/full',
        'thumb_url': '/api/occasions/$occasionId/images/$id/thumb',
      };

  /// Applies `image_id` of a gift create or update: absent leaves the image,
  /// `null` removes it, an id attaches that image.
  void _applyImageId(Map<String, dynamic> gift, Map<String, dynamic> body) {
    gift.remove('image_id');
    if (!body.containsKey('image_id')) return;
    final id = body['image_id'] as String?;
    if (id == null) {
      gift.remove('image');
    } else {
      gift['image'] = _ownerImage(id);
    }
  }

  /// The gift as an invitee of [occasionId] sees it.
  Map<String, dynamic> _sharedGift(String occasionId, Map<String, dynamic> gift) {
    final image = gift['image'] as Map<String, dynamic>?;
    return {
      ...gift,
      if (image != null) 'image': _inviteeImage(occasionId, image['id'] as String),
    }..remove('list_id');
  }

  http.Response _imageResponse(String id) => images.containsKey(id)
      ? http.Response.bytes(
          kTestImage,
          200,
          headers: {'content-type': 'image/png'},
        )
      : http.Response('{"detail":"Not found"}', 404);

  /// An occasion of [listId] on [date] (`2026-12-24`), with a link when
  /// [token] is given, and [invitees] (display names) who joined it.
  String addOccasion(
    String listId,
    String name,
    String date, {
    String? token,
    List<String> invitees = const [],
  }) {
    final id = 'occasion-${_next++}';
    occasions[id] = <String, dynamic>{
      'id': id,
      'list_id': listId,
      'name': name,
      'date': date,
      'join_token': token,
    };
    members[id] = [
      for (final invitee in invitees)
        {'user_id': 'user-${_next++}', 'display_name': invitee},
    ];
    for (final member in members[id]!) {
      names[member['user_id']!] = member['display_name']!;
    }
    removed[id] = [];
    return id;
  }

  Map<String, dynamic>? gift(String id) =>
      gifts.where((gift) => gift['id'] == id).firstOrNull;

  /// A participant of a claim: [name], Alice when [mine], with an optional
  /// pledge.
  static Map<String, dynamic> giver(
    String name, {
    bool mine = false,
    String? amount,
    String? currency,
  }) =>
      {
        'display_name': name,
        'mine': mine,
        'pledge_amount': amount,
        'pledge_currency': currency,
      };

  /// [giftId] reserved in [occasionId] by [participants] (one), or a group
  /// gift of theirs when [group].
  void addClaim(
    String giftId,
    String? occasionId,
    List<Map<String, dynamic>> participants, {
    bool group = false,
    bool bought = false,
  }) {
    claims[giftId] = {
      'occasion_id': occasionId,
      'kind': group ? 'group' : 'reservation',
      'bought': bought,
      'participants': [...participants],
    };
  }

  /// A claim stops being live when its occasion has passed, unless bought
  /// (D8).
  bool _live(Map<String, dynamic> claim) =>
      claim['bought'] == true || !passed.contains(claim['occasion_id']);

  /// The claim as a giver of [occasionId] sees it (`GiftClaimOut`).
  Map<String, dynamic> _claimOut(
    String occasionId,
    String giftId,
    Map<String, dynamic> claim,
  ) =>
      claim['occasion_id'] == occasionId
          ? {
              'gift_id': giftId,
              'state': claim['kind'] == 'group' ? 'group' : 'reserved',
              'bought': claim['bought'],
              'participants': claim['participants'],
            }
          : {
              'gift_id': giftId,
              'state': 'taken',
              'bought': false,
              'participants': const <Object>[],
            };

  /// Alice is in [claim], of [occasionId].
  bool _aliceIn(String occasionId, Map<String, dynamic>? claim) =>
      claim != null &&
      claim['occasion_id'] == occasionId &&
      (claim['participants'] as List).any((giver) => giver['mine'] == true);

  /// `/api/occasions/{id}/claims` and `…/gifts/{gift_id}/<action>` for a
  /// giver of the occasion, with the server's rules (D6, D8, D9); null for
  /// any other path.
  http.Response? _claims(
    http.Request request,
    String occasionId,
    String listId,
    List<String> segments,
    Map<String, dynamic>? body,
    http.Response Function(Object body, [int code]) json,
    http.Response notFound,
    http.Response noContent,
  ) {
    final ofList = [
      for (final gift in gifts)
        if (gift['list_id'] == listId) gift,
    ];
    if (request.method == 'GET' && segments.length == 4 && segments[3] == 'claims') {
      return json({
        'passed': passed.contains(occasionId),
        'gifts': [
          for (final gift in ofList)
            if (claims[gift['id']] case final claim? when _live(claim))
              _claimOut(occasionId, gift['id'] as String, claim),
        ],
      });
    }
    if (segments.length != 6 || segments[3] != 'gifts') return null;
    final gift = ofList.where((gift) => gift['id'] == segments[4]).firstOrNull;
    final action = (request.method, segments[5]);
    const actions = {
      ('POST', 'reservation'),
      ('DELETE', 'reservation'),
      ('POST', 'bought'),
      ('PUT', 'pledge'),
      ('DELETE', 'pledge'),
    };
    if (!actions.contains(action)) return null;
    if (gift == null) return notFound;
    final giftId = gift['id'] as String;
    http.Response conflict(String code) =>
        json({'detail': 'Refused', 'code': code}, 409);
    http.Response out() => json(_claimOut(occasionId, giftId, claims[giftId]!));
    final held = claims[giftId];
    final live = held != null && _live(held) ? held : null;
    final mine = _aliceIn(occasionId, live);
    final alice = giver(kAliceName, mine: true);
    if (passed.contains(occasionId)) {
      // The one write allowed: marking bought one's own claim, still there.
      if (action != ('POST', 'bought') || !_aliceIn(occasionId, held)) {
        return conflict('passed');
      }
      held!['bought'] = true;
      return out();
    }
    switch (action) {
      case ('POST', 'reservation'):
        if (live == null) {
          addClaim(giftId, occasionId, [alice]);
          return out();
        }
        return live['kind'] == 'reservation' && mine ? out() : conflict('taken');
      case ('DELETE', 'reservation'):
        if (live?['kind'] == 'reservation' && mine) {
          if (live!['bought'] == true) return conflict('bought');
          claims.remove(giftId);
        }
        return noContent;
      case ('POST', 'bought'):
        if (live == null) {
          addClaim(giftId, occasionId, [alice], bought: true);
          return out();
        }
        if (!mine) return conflict('taken');
        live['bought'] = true;
        return out();
      case ('PUT', 'pledge'):
        final amount = body!['amount'] as String?;
        final currency = gift['price_currency'] as String?;
        if (amount != null && currency == null) {
          return json({'detail': 'No currency'}, 422);
        }
        final pledge = giver(
          kAliceName,
          mine: true,
          amount: amount,
          currency: amount == null ? null : currency,
        );
        if (live == null) {
          addClaim(giftId, occasionId, [pledge], group: true);
          return out();
        }
        if (live['occasion_id'] != occasionId || live['kind'] != 'group') {
          return conflict('taken');
        }
        if (live['bought'] == true) return conflict('bought');
        final givers = live['participants'] as List<Map<String, dynamic>>;
        final index = givers.indexWhere((giver) => giver['mine'] == true);
        index < 0 ? givers.add(pledge) : givers[index] = pledge;
        return out();
      case ('DELETE', 'pledge'):
        if (live?['kind'] == 'group' && mine) {
          if (live!['bought'] == true) return conflict('bought');
          final givers = live['participants'] as List<Map<String, dynamic>>;
          givers.removeWhere((giver) => giver['mine'] == true);
          if (givers.isEmpty) claims.remove(giftId);
        }
        return noContent;
    }
    return null;
  }

  /// An occasion as its list's owners see it (`OccasionOut`).
  Map<String, dynamic> _ownerOccasion(Map<String, dynamic> occasion) => {
        ...occasion,
        'member_count': members[occasion['id']]!.length,
      };

  /// The list of [occasion], who owns it, and whether Alice does.
  ({Map<String, dynamic> list, List<String> owners, bool mine}) _listOf(
    Map<String, dynamic> occasion,
  ) {
    final id = occasion['list_id'] as String;
    final mine = lists[id];
    return mine != null
        ? (list: mine, owners: const [kAliceName], mine: true)
        : (list: otherLists[id]!, owners: otherOwners[id]!, mine: false);
  }

  /// An occasion as an invitee sees it (`SharedOccasion`).
  Map<String, dynamic> _sharedOccasion(Map<String, dynamic> occasion) {
    final of = _listOf(occasion);
    return {
      'id': occasion['id'],
      'name': occasion['name'],
      'date': occasion['date'],
      'list_title': of.list['title'],
      'recipient_name': of.list['recipient_kind'] == 'other'
          ? of.list['recipient_name']
          : of.owners.join(', '),
      'owner_names': of.owners,
    };
  }

  Map<String, dynamic>? _byToken(Object? token) => token == null
      ? null
      : occasions.values
          .where((occasion) => occasion['join_token'] == token)
          .firstOrNull;

  static const _roots = [
    '/api/lists',
    '/api/gifts',
    '/api/occasions',
    '/api/shared',
    '/api/join',
    '/api/images',
  ];

  Future<http.Response> _handle(http.Request request) async {
    final path = request.url.path;
    if (!_roots.any(path.startsWith)) {
      // A copy: the request MockClient hands over is already finalized.
      final copy = http.Request(request.method, request.url)
        ..headers.addAll(request.headers)
        ..bodyBytes = request.bodyBytes;
      return http.Response.fromStream(await accounts.client.send(copy));
    }
    final call = '${request.method} $path';
    calls.add(call);
    final isJson =
        (request.headers['content-type'] ?? '').startsWith('application/json');
    if (isJson && request.body.isNotEmpty) {
      bodies[call] = jsonDecode(request.body) as Map<String, dynamic>;
    }
    await hold?.future;
    final forced = status[call];
    if (forced != null) {
      final detail = details[call];
      return detail == null
          ? http.Response('', forced)
          : http.Response(jsonEncode({'detail': detail}), forced);
    }
    final auth = request.headers['Authorization'] ?? '';
    if (!accounts.sessions.containsKey(auth.replaceFirst('Bearer ', ''))) {
      return http.Response('{"detail":"Not authenticated"}', 401);
    }
    http.Response json(Object body, [int code = 200]) =>
        http.Response.bytes(
          utf8.encode(jsonEncode(body)),
          code,
          headers: {'content-type': 'application/json'},
        );
    final notFound = http.Response('{"detail":"Not Found"}', 404);
    final noContent = http.Response('', 204);
    final body = bodies[call];
    final segments = request.url.pathSegments;

    if (call == 'GET /api/lists') {
      return json([
        for (final list in lists.values)
          {
            ...list,
            'gift_count':
                gifts.where((gift) => gift['list_id'] == list['id']).length,
          },
      ]);
    }
    if (call == 'GET /api/shared') {
      return json([
        for (final occasion in occasions.values)
          if (joined.contains(occasion['id'])) _sharedOccasion(occasion),
      ]);
    }
    if (call == 'POST /api/join/preview' || call == 'POST /api/join') {
      return _join(call, body?['token'], json, notFound);
    }
    if (call == 'POST /api/images') {
      uploads.add(request.bodyBytes);
      return json(_ownerImage(addImage()), 201);
    }
    if (call == 'POST /api/images/from-url') {
      return json(_ownerImage(addImage()), 201);
    }
    if (request.method == 'GET' &&
        segments[1] == 'images' &&
        segments.length == 4) {
      return _imageResponse(segments[2]);
    }
    if (segments[1] == 'occasions') {
      return _occasion(request, segments, body, json, notFound, noContent);
    }
    if (call == 'POST /api/lists') {
      final id = addList(
        body!['title'] as String,
        recipientName: body['recipient_name'] as String?,
      );
      return json(lists[id]!, 201);
    }
    if (segments[1] == 'lists') {
      final list = lists[segments[2]];
      if (list == null) return notFound;
      if (segments.length == 4 &&
          segments[3] == 'occasions' &&
          request.method == 'POST') {
        final id = addOccasion(
          list['id'] as String,
          body!['name'] as String,
          body['date'] as String,
        );
        return json(_ownerOccasion(occasions[id]!), 201);
      }
      if (segments.length == 4 && request.method == 'POST') {
        final id = addGift(list['id'] as String, body!['title'] as String);
        gift(id)!.addAll(body);
        _applyImageId(gift(id)!, body);
        return json(gift(id)!, 201);
      }
      switch (request.method) {
        case 'GET':
          final ofList = occasions.values
              .where((occasion) => occasion['list_id'] == list['id'])
              .toList()
            ..sort(
              (a, b) => (a['date'] as String).compareTo(b['date'] as String),
            );
          return json({
            ...list,
            'gifts': gifts.where((gift) => gift['list_id'] == list['id']).toList(),
            'occasions': ofList.map(_ownerOccasion).toList(),
          });
        case 'PATCH':
          list.addAll(body!);
          return json(list);
        case 'DELETE':
          lists.remove(list['id']);
          gifts.removeWhere((gift) => gift['list_id'] == list['id']);
          occasions.removeWhere(
            (_, occasion) => occasion['list_id'] == list['id'],
          );
          return noContent;
      }
    }
    final found = gift(segments[2]);
    if (found == null) return notFound;
    switch (request.method) {
      case 'PATCH':
        found.addAll(body!);
        _applyImageId(found, body);
        return json(found);
      case 'DELETE':
        gifts.remove(found);
        return noContent;
    }
    return notFound;
  }

  /// `POST /api/join/preview` and `POST /api/join`.
  http.Response _join(
    String call,
    Object? token,
    http.Response Function(Object body, [int code]) json,
    http.Response notFound,
  ) {
    if (token is String && token.length > 64) {
      return http.Response('{"detail":"too long"}', 422);
    }
    final occasion = _byToken(token);
    if (occasion == null) return notFound;
    final id = occasion['id'] as String;
    final of = _listOf(occasion);
    if (call == 'POST /api/join') {
      if (of.mine) {
        return json({'detail': 'You own this list', 'list_id': of.list['id']}, 409);
      }
      if (aliceRemoved.contains(id)) return notFound;
      joined.add(id);
      return json({'occasion_id': id});
    }
    final common = _sharedOccasion(occasion)..remove('id');
    if (of.mine) {
      return json({
        ...common,
        'role': 'owner',
        'list_id': of.list['id'],
        'occasion_id': null,
      });
    }
    if (aliceRemoved.contains(id)) return notFound;
    final member = joined.contains(id);
    return json({
      ...common,
      'role': member ? 'member' : 'none',
      'list_id': null,
      'occasion_id': member ? id : null,
    });
  }

  /// `/api/occasions/{id}` and the paths under it.
  http.Response _occasion(
    http.Request request,
    List<String> segments,
    Map<String, dynamic>? body,
    http.Response Function(Object body, [int code]) json,
    http.Response notFound,
    http.Response noContent,
  ) {
    final occasion = occasions[segments[2]];
    if (occasion == null) return notFound;
    final id = occasion['id'] as String;
    final of = _listOf(occasion);
    final rest = segments.skip(3).join('/');
    if (!of.mine) {
      if (!joined.contains(id)) return notFound;
      if (request.method == 'GET' && segments.length == 6 && segments[3] == 'images') {
        return _imageResponse(segments[4]);
      }
      final claims = _claims(request, id, of.list['id'] as String, segments,
          body, json, notFound, noContent);
      if (claims != null) return claims;
      switch ((request.method, rest)) {
        case ('GET', ''):
          return json({
            ..._sharedOccasion(occasion),
            'role': 'invitee',
            'gifts': [
              for (final gift in gifts)
                if (gift['list_id'] == of.list['id']) _sharedGift(id, gift),
            ],
          });
        case ('DELETE', 'membership'):
          joined.remove(id);
          return noContent;
      }
      return notFound;
    }
    if (request.method == 'GET' && segments.length == 6 && segments[3] == 'images') {
      return _imageResponse(segments[4]);
    }
    // Owners of a list for someone else give too; a recipient gets the
    // random-id 404 (RESERVING_PLAN D4).
    if (of.list['recipient_kind'] == 'other') {
      final claims = _claims(request, id, of.list['id'] as String, segments,
          body, json, notFound, noContent);
      if (claims != null) return claims;
    }
    switch ((request.method, rest)) {
      case ('GET', ''):
        return json({
          ..._ownerOccasion(occasion),
          'role': 'owner',
          'list': of.list,
          'gifts': gifts
              .where((gift) => gift['list_id'] == of.list['id'])
              .toList(),
        });
      case ('PATCH', ''):
        occasion.addAll(body!);
        return json(_ownerOccasion(occasion));
      case ('DELETE', ''):
        occasions.remove(id);
        return noContent;
      case ('POST', 'link'):
        occasion['join_token'] = 'token-${_next++}';
        return json(_ownerOccasion(occasion));
      case ('DELETE', 'link'):
        occasion['join_token'] = null;
        return noContent;
      case ('GET', 'members'):
        return json([
          for (final member in members[id]!) {...member, 'removed': false},
          for (final member in removed[id]!) {...member, 'removed': true},
        ]);
    }
    if (request.method == 'DELETE' && segments.length == 5) {
      final userId = segments[4];
      // An unknown user, as on the server; owners are not invitees either.
      if (!names.containsKey(userId)) return notFound;
      if (segments[3] == 'members') {
        // Member or not: someone who left a moment ago is kept out all the
        // same, once.
        members[id]!.removeWhere((member) => member['user_id'] == userId);
        if (!removed[id]!.any((member) => member['user_id'] == userId)) {
          removed[id]!.add({'user_id': userId, 'display_name': names[userId]!});
        }
        return noContent;
      }
      if (segments[3] == 'removals') {
        removed[id]!.removeWhere((member) => member['user_id'] == userId);
        return noContent;
      }
    }
    return notFound;
  }
}

/// The app against [server], signed in unless [signedIn] is false, opened at
/// [location] and settled; only pumped once when [settle] is false, for a
/// screen still waiting on [FakeListsServer.hold]. [pendingJoin] is the
/// occasion link the app was opened with.
Future<({ApiClient api, AuthController auth})> startApp(
  WidgetTester tester,
  FakeListsServer server,
  String location, {
  bool signedIn = true,
  bool settle = true,
  PendingJoin? pendingJoin,
}) async {
  tester.platformDispatcher.defaultRouteNameTestValue = location;
  addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
  installFakeGoogleSignIn();
  final api = ApiClient(server.client, baseUrl: kApiBase);
  final auth = AuthController(
    api: api,
    store: MemoryTokenStore(signedIn ? server.accounts.addSession() : null),
  );
  await tester.pumpWidget(
    WishlistApp(api: api, auth: auth, pendingJoin: pendingJoin),
  );
  await auth.restore();
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump();
  }
  return (api: api, auth: auth);
}

/// url_launcher's platform side: records what it is asked to open.
class FakeUrlLauncher extends Fake
    with MockPlatformInterfaceMixin
    implements UrlLauncherPlatform {
  final launched = <(String, PreferredLaunchMode)>[];

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    launched.add((url, options.mode));
    return true;
  }
}

/// Installs a fresh [FakeUrlLauncher] for the test.
FakeUrlLauncher installFakeUrlLauncher() {
  final previous = UrlLauncherPlatform.instance;
  final fake = FakeUrlLauncher();
  UrlLauncherPlatform.instance = fake;
  addTearDown(() => UrlLauncherPlatform.instance = previous);
  return fake;
}

/// image_picker's platform side: hands over [picked] (null: the user
/// cancelled), and records how it was asked.
class FakeImagePicker extends Fake
    with MockPlatformInterfaceMixin
    implements ImagePickerPlatform {
  Uint8List? picked;
  final requests = <(ImageSource, ImagePickerOptions)>[];

  @override
  Future<XFile?> getImageFromSource({
    required ImageSource source,
    ImagePickerOptions options = const ImagePickerOptions(),
  }) async {
    requests.add((source, options));
    final bytes = picked;
    return bytes == null ? null : XFile.fromData(bytes, mimeType: 'image/png');
  }
}

/// Installs a fresh [FakeImagePicker] for the test, picking [picked].
FakeImagePicker installFakeImagePicker([Uint8List? picked]) {
  final previous = ImagePickerPlatform.instance;
  final fake = FakeImagePicker()..picked = picked;
  ImagePickerPlatform.instance = fake;
  addTearDown(() => ImagePickerPlatform.instance = previous);
  return fake;
}

/// The text field labelled [label].
Finder fieldLabelled(String label) =>
    find.widgetWithText(TextFormField, label);

/// Lets the images the screen asked for download and decode: decoding runs
/// off the test's fake clock, so it is waited for in real time.
Future<void> loadImages(WidgetTester tester) async {
  for (var i = 0; i < 3; i++) {
    await tester.pump();
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 100)),
    );
  }
  await tester.pumpAndSettle();
}
