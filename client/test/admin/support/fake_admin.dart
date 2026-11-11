/// The admin routes (admin panel plan D5–D9) in memory, on [FakeServer].
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../support/fakes.dart';

/// A user row as `GET /api/admin/users` gives it.
Map<String, Object?> adminRow({
  required String id,
  required String email,
  String displayName = '',
  String createdAt = '2026-03-12T09:00:00Z',
  List<String> signIn = const ['google'],
  Map<String, Object?> plan = const {
    'plan': 'free',
    'source': null,
    'until': null,
  },
  Map<String, Object?>? subscription,
  // Apple's, and whether one can still charge (Apple IAP plan D9); left out
  // of the row when null, as a server from before them sends it.
  Map<String, Object?>? appleSubscription,
  bool? appleRenewing,
  int listsOwned = 0,
  Map<String, Object?> photos = const {
    'count': 0,
    'bytes': 0,
    'measuring': false,
  },
}) =>
    {
      'id': id,
      'email': email,
      'display_name': displayName,
      'created_at': createdAt,
      'sign_in': signIn,
      'plan': plan,
      'subscription': subscription,
      'apple_subscription': ?appleSubscription,
      'apple_renewing': ?appleRenewing,
      'lists_owned': listsOwned,
      'photos': photos,
    };

/// A Stripe or Apple subscription as a row gives it.
Map<String, Object?> stripeSubscription(
  String status, {
  String? startedAt = '2026-05-02T10:05:00Z',
  String? periodEnd = '2027-03-12T12:00:00Z',
}) =>
    {'status': status, 'started_at': startedAt, 'period_end': periodEnd};

const kBobId = '7b0c2f1e-0000-4000-8000-000000000002';
const kCarolId = '7b0c2f1e-0000-4000-8000-000000000003';

/// Bob: Premium through an active Stripe subscription, two lists, three
/// photos measured.
Map<String, Object?> bobRow() => adminRow(
      id: kBobId,
      email: 'bob@example.com',
      displayName: 'Bob Durand',
      createdAt: '2026-05-02T10:00:00Z',
      signIn: const ['apple', 'email'],
      plan: const {
        'plan': 'premium',
        'source': 'stripe',
        'until': '2027-03-12T12:00:00Z',
      },
      subscription: stripeSubscription('active'),
      listsOwned: 2,
      photos: const {'count': 3, 'bytes': 1500000, 'measuring': false},
    );

/// Carol: free, one photo still being measured.
Map<String, Object?> carolRow() => adminRow(
      id: kCarolId,
      email: 'carol@example.com',
      displayName: 'Carol',
      createdAt: '2026-04-20T10:00:00Z',
      listsOwned: 1,
      photos: const {'count': 1, 'bytes': 0, 'measuring': true},
    );

Map<String, Object?> aliceRow() => adminRow(
      id: kAlice['id']!,
      email: kAlice['email']!,
      displayName: kAlice['display_name']!,
      createdAt: '2026-01-05T10:00:00Z',
    );

/// The admin side of [server]: Alice is the admin, and [rows] the accounts,
/// newest first. Changes answer 401 `reauth_required` while [reauth] is set.
class FakeAdmin {
  FakeAdmin(this.server, {List<Map<String, Object?>>? rows})
      : rows = rows ?? [bobRow(), carolRow(), aliceRow()] {
    server.isAdmin = true;
    server.extra = _handle;
  }

  final FakeServer server;
  final List<Map<String, Object?>> rows;

  /// Accounts per page; the server's is 50.
  int pageSize = 50;

  /// The session is over 12 hours old (D3).
  bool reauth = false;

  /// The account id → its lists, as `GET /api/admin/users/{id}` gives them.
  final lists = <String, List<Map<String, Object?>>>{
    kBobId: [
      {
        'id': 'l1',
        'title': 'Birthday',
        'created_at': '2026-05-03T10:00:00Z',
        'gift_count': 4,
        'owner_count': 1,
      },
      {
        'id': 'l2',
        'title': 'Wedding',
        'created_at': '2026-06-01T10:00:00Z',
        'gift_count': 12,
        'owner_count': 2,
      },
    ],
  };

  /// The account id → the end of the admin's grant.
  final grants = <String, String>{};

  /// A refusal forced for `'<METHOD> <path>'`: its status and `code`.
  final refusals = <String, (int, String)>{};

  /// The body of every change, by its call.
  final bodies = <String, List<Map<String, dynamic>>>{};

  /// Every `q` and `cursor` the users list was asked with.
  final queries = <Map<String, String>>[];

  Map<String, Object?>? _row(String id) =>
      rows.where((row) => row['id'] == id).firstOrNull;

  /// [row] as the server gives it, with the admin's grant, on the list and
  /// on the account's page.
  Map<String, Object?> _withGrant(Map<String, Object?> row) {
    final grant = grants[row['id']];
    return {
      ...row,
      'manual_grant': grant == null ? null : {'period_end': grant},
    };
  }

  Map<String, Object?> _detail(Map<String, Object?> row) => {
        ..._withGrant(row),
        'lists': lists[row['id']] ?? const [],
      };

  Future<http.Response?> _handle(
    http.Request request,
    Map<String, String>? user,
  ) async {
    final path = request.url.path;
    if (!path.startsWith('/api/admin')) return null;
    final call = '${request.method} $path';
    // Anyone but the admin: an unknown path (D2).
    if (user == null || !server.isAdmin) return http.Response('', 404);
    http.Response json(Object body, [int status = 200]) =>
        http.Response(jsonEncode(body), status);
    final change = request.method != 'GET';
    if (change) {
      bodies.putIfAbsent(call, () => []).add(
            request.body.isEmpty
                ? {}
                : jsonDecode(request.body) as Map<String, dynamic>,
          );
      if (reauth) return json({'detail': 'reauth_required'}, 401);
    }
    if (refusals[call] case (final status, final code)) {
      return json({'detail': code, 'code': code}, status);
    }
    final segments = request.url.pathSegments; // api, admin, users, ...
    if (call == 'GET /api/admin/users') {
      queries.add(request.url.queryParameters);
      final q = request.url.queryParameters['q']?.toLowerCase();
      final matching = [
        for (final row in rows)
          if (q == null || (row['email'] as String).contains(q)) row,
      ];
      final start = int.parse(request.url.queryParameters['cursor'] ?? '0');
      final end = start + pageSize;
      return json({
        'users': [
          for (final row
              in matching.sublist(start, end.clamp(0, matching.length)))
            _withGrant(row),
        ],
        'next_cursor': end < matching.length ? '$end' : null,
      });
    }
    if (segments.length < 4 || segments[2] != 'users') {
      return http.Response('', 404);
    }
    final id = segments[3];
    final row = _row(id);
    if (row == null) return http.Response('', 404);
    if (segments.length == 4) {
      switch (request.method) {
        case 'GET':
          return json(_detail(row));
        case 'DELETE':
          if (id == user['id']) {
            return json({'code': 'use_account_screen'}, 409);
          }
          final typed = bodies[call]!.last['email'] as String?;
          if (typed?.trim().toLowerCase() !=
              (row['email'] as String).toLowerCase()) {
            return json({'code': 'email_mismatch'}, 422);
          }
          rows.remove(row);
          return http.Response('', 204);
      }
    }
    if (segments.length == 5 && segments[4] == 'premium') {
      switch (request.method) {
        case 'POST':
          final end = bodies[call]!.last['period_end'] as String;
          grants[id] = '${end}T12:00:00Z';
          row['plan'] = {
            'plan': 'premium',
            'source': 'manual',
            'until': grants[id],
          };
          return json(_detail(row));
        case 'DELETE':
          if (grants.remove(id) == null) {
            return json({'code': 'no_manual_grant'}, 409);
          }
          row['plan'] = const {'plan': 'free', 'source': null, 'until': null};
          return json(_detail(row));
      }
    }
    return http.Response('', 404);
  }
}
