/// The server's list and gift endpoints in memory, on top of [FakeServer]'s
/// account endpoints, and the app against both.
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

import '../../support/fakes.dart';

/// Lists and gifts of the signed-in user (LISTS_GIFTS_SHARING_PLAN D8). Any
/// other call goes to [accounts]. [status] forces an answer for
/// `'<METHOD> <path>'`; while [hold] is set, list and gift calls wait for it.
class FakeListsServer {
  FakeListsServer() : accounts = FakeServer();

  final FakeServer accounts;

  /// Id → the list as `ListOut` gives it.
  final lists = <String, Map<String, dynamic>>{};

  /// Every gift, oldest first, as `GiftOut` gives it.
  final gifts = <Map<String, dynamic>>[];

  final status = <String, int>{};

  /// Every list and gift call, as `'<METHOD> <path>'`.
  final calls = <String>[];

  /// The JSON body of every list and gift call, by `'<METHOD> <path>'`.
  final bodies = <String, Map<String, dynamic>>{};

  Completer<void>? hold;
  int _next = 0;

  late final http.Client client = MockClient(_handle);

  String addList(String title, {String? recipientName}) {
    final id = 'list-${_next++}';
    lists[id] = {
      'id': id,
      'title': title,
      'recipient_kind': recipientName == null ? 'self' : 'other',
      'recipient_name': recipientName,
    };
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

  Map<String, dynamic>? gift(String id) =>
      gifts.where((gift) => gift['id'] == id).firstOrNull;

  Future<http.Response> _handle(http.Request request) async {
    final path = request.url.path;
    if (!path.startsWith('/api/lists') && !path.startsWith('/api/gifts')) {
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
      if (segments.length == 4 && request.method == 'POST') {
        final id = addGift(list['id'] as String, body!['title'] as String);
        gift(id)!.addAll(body);
        return json(gift(id)!, 201);
      }
      switch (request.method) {
        case 'GET':
          return json({
            ...list,
            'gifts': gifts.where((gift) => gift['list_id'] == list['id']).toList(),
          });
        case 'PATCH':
          list.addAll(body!);
          return json(list);
        case 'DELETE':
          lists.remove(list['id']);
          gifts.removeWhere((gift) => gift['list_id'] == list['id']);
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
}

/// The app against [server], signed in unless [signedIn] is false, opened at
/// [location] and settled; only pumped once when [settle] is false, for a
/// screen still waiting on [FakeListsServer.hold].
Future<({ApiClient api, AuthController auth})> startApp(
  WidgetTester tester,
  FakeListsServer server,
  String location, {
  bool signedIn = true,
  bool settle = true,
}) async {
  tester.platformDispatcher.defaultRouteNameTestValue = location;
  addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
  installFakeGoogleSignIn();
  final api = ApiClient(server.client, baseUrl: kApiBase);
  final auth = AuthController(
    api: api,
    store: MemoryTokenStore(signedIn ? server.accounts.addSession() : null),
  );
  await tester.pumpWidget(WishlistApp(api: api, auth: auth));
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
