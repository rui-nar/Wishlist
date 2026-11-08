/// The server's list, gift, occasion and join endpoints in memory, on top of
/// [FakeServer]'s account endpoints, and the app against both.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';
import 'package:wishlist/main.dart';
import 'package:wishlist/src/api/api_client.dart';
import 'package:wishlist/src/auth/auth_controller.dart';
import 'package:wishlist/src/shared/pending_join.dart';

import '../../support/fakes.dart';

/// The signed-in user's display name, as the server gives it to others.
const kAliceName = 'Alice Martin';

/// Lists, gifts, occasions and joining for the signed-in user, Alice
/// (LISTS_GIFTS_SHARING_PLAN D8). Any other call goes to [accounts].
/// [status] forces an answer for `'<METHOD> <path>'`; while [hold] is set,
/// these calls wait for it.
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

  final status = <String, int>{};

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
    });
    return id;
  }

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
    if (request.body.isNotEmpty) {
      bodies[call] = jsonDecode(request.body) as Map<String, dynamic>;
    }
    await hold?.future;
    final forced = status[call];
    if (forced != null) return http.Response('', forced);
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
      switch ((request.method, rest)) {
        case ('GET', ''):
          return json({
            ..._sharedOccasion(occasion),
            'role': 'invitee',
            'gifts': [
              for (final gift in gifts)
                if (gift['list_id'] == of.list['id'])
                  {...gift}..remove('list_id'),
            ],
          });
        case ('DELETE', 'membership'):
          joined.remove(id);
          return noContent;
      }
      return notFound;
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

/// The text field labelled [label].
Finder fieldLabelled(String label) =>
    find.widgetWithText(TextFormField, label);
