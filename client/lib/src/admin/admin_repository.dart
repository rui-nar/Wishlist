/// The admin panel's calls (admin panel plan D5–D9). Counts and sizes only,
/// as the server gives them: the client adds nothing up and decides nothing.
library;

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';

const kAdminPath = '/admin';

/// The page of one user in the panel.
String adminUserPath(String id) => '$kAdminPath/users/${Uri.encodeComponent(id)}';

const _kPath = '/api/admin/users';

/// The refusal codes the panel tells apart (`server/app/admin/router.py`).
const kEmailMismatch = 'email_mismatch';
const kUseAccountScreen = 'use_account_screen';
const kNoManualGrant = 'no_manual_grant';
const kInvalidCursor = 'invalid_cursor';
const kPeriodEndOutOfRange = 'period_end_out_of_range';
const kBillingUnavailable = 'billing_unavailable';

/// The `code` of a refusal, when the server named one.
String? refusalCode(Object? error) =>
    error is ApiException ? (error.body?['code'] as String?) : null;

DateTime? _date(Object? value) =>
    value == null ? null : DateTime.parse(value as String);

/// The plan as `GET /api/billing` reads it for that person.
class AdminPlan {
  const AdminPlan({required this.isPremium, this.source, this.until});

  factory AdminPlan.fromJson(Map<String, dynamic> json) => AdminPlan(
        isPremium: json['plan'] == 'premium',
        source: json['source'] as String?,
        until: _date(json['until']),
      );

  final bool isPremium;

  /// `stripe`, `apple`, `google`, `manual`; null on the free plan.
  final String? source;

  /// When it renews or ends; null on the free plan.
  final DateTime? until;
}

/// The photos the person sent that a list's owners can see (D7).
class AdminPhotos {
  const AdminPhotos({
    required this.count,
    required this.bytes,
    required this.measuring,
  });

  factory AdminPhotos.fromJson(Map<String, dynamic> json) => AdminPhotos(
        count: (json['count'] as num).toInt(),
        bytes: (json['bytes'] as num).toInt(),
        measuring: json['measuring'] as bool,
      );

  final int count;

  /// Of the photos measured so far.
  final int bytes;

  /// Some are not measured yet: [bytes] is not the whole.
  final bool measuring;
}

/// The person's Stripe subscription, shown apart from a grant by hand.
class AdminSubscription {
  const AdminSubscription({
    required this.status,
    this.startedAt,
    this.periodEnd,
  });

  factory AdminSubscription.fromJson(Map<String, dynamic> json) =>
      AdminSubscription(
        status: json['status'] as String,
        startedAt: _date(json['started_at']),
        periodEnd: _date(json['period_end']),
      );

  /// `active`, `past_due`, `canceling` (set to stop at [periodEnd]),
  /// `incomplete` or `ended`.
  final String status;
  final DateTime? startedAt;

  /// When it renews while `active` or `past_due`, when it ends otherwise.
  final DateTime? periodEnd;
}

/// A user as the users list shows them (D5).
class AdminUserRow {
  const AdminUserRow({
    required this.id,
    required this.email,
    required this.displayName,
    required this.createdAt,
    required this.signIn,
    required this.plan,
    this.subscription,
    this.manualGrantEnd,
    required this.listsOwned,
    required this.photos,
  });

  factory AdminUserRow.fromJson(Map<String, dynamic> json) {
    final subscription = json['subscription'] as Map<String, dynamic>?;
    final grant = json['manual_grant'] as Map<String, dynamic>?;
    return AdminUserRow(
      id: json['id'] as String,
      email: json['email'] as String,
      displayName: json['display_name'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      signIn: (json['sign_in'] as List<dynamic>).cast<String>(),
      plan: AdminPlan.fromJson(json['plan'] as Map<String, dynamic>),
      subscription: subscription == null
          ? null
          : AdminSubscription.fromJson(subscription),
      manualGrantEnd: grant == null ? null : _date(grant['period_end']),
      listsOwned: (json['lists_owned'] as num).toInt(),
      photos: AdminPhotos.fromJson(json['photos'] as Map<String, dynamic>),
    );
  }

  final String id;
  final String email;
  final String displayName;
  final DateTime createdAt;

  /// The providers: `google`, `apple`, `email`.
  final List<String> signIn;

  /// The effective plan, whatever its source.
  final AdminPlan plan;

  /// The one in force, else the latest; null if they never subscribed. Shown
  /// apart from [manualGrantEnd]: neither hides the other.
  final AdminSubscription? subscription;

  /// When the admin's grant ends; null when there is none to end (D8).
  final DateTime? manualGrantEnd;

  final int listsOwned;
  final AdminPhotos photos;
}

class AdminUsersPage {
  const AdminUsersPage({required this.users, required this.nextCursor});

  factory AdminUsersPage.fromJson(Map<String, dynamic> json) => AdminUsersPage(
        users: [
          for (final user in json['users'] as List<dynamic>)
            AdminUserRow.fromJson(user as Map<String, dynamic>),
        ],
        nextCursor: json['next_cursor'] as String?,
      );

  final List<AdminUserRow> users;

  /// Null on the last page.
  final String? nextCursor;
}

/// A list the user owns, as counts (D6).
class AdminList {
  const AdminList({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.giftCount,
    required this.ownerCount,
  });

  factory AdminList.fromJson(Map<String, dynamic> json) => AdminList(
        id: json['id'] as String,
        title: json['title'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        giftCount: (json['gift_count'] as num).toInt(),
        ownerCount: (json['owner_count'] as num).toInt(),
      );

  final String id;
  final String title;
  final DateTime createdAt;
  final int giftCount;
  final int ownerCount;
}

/// One user (D6): the row, with the lists they own.
class AdminUserDetail {
  const AdminUserDetail({required this.user, required this.lists});

  factory AdminUserDetail.fromJson(Map<String, dynamic> json) =>
      AdminUserDetail(
        user: AdminUserRow.fromJson(json),
        lists: [
          for (final list in json['lists'] as List<dynamic>)
            AdminList.fromJson(list as Map<String, dynamic>),
        ],
      );

  final AdminUserRow user;
  final List<AdminList> lists;
}

/// `/api/admin/users`. A change on a session over 12 hours old throws
/// [ReauthRequiredException] (D3); the server's other refusals are
/// [ApiException]s whose [refusalCode] names them.
class AdminRepository {
  AdminRepository(this._api);

  factory AdminRepository.of(BuildContext context) =>
      AdminRepository(context.read<ApiClient>());

  final ApiClient _api;

  /// A page of users, newest first, those whose address contains [query].
  Future<AdminUsersPage> users({String? query, String? cursor}) async {
    final uri = Uri(path: _kPath, queryParameters: {
      if (query != null && query.isNotEmpty) 'q': query,
      'cursor': ?cursor,
    });
    return AdminUsersPage.fromJson(await _api.getJson(uri.toString()));
  }

  Future<AdminUserDetail> user(String id) async =>
      AdminUserDetail.fromJson(await _api.getJson(_userPath(id)));

  /// Premium until [until], a calendar day (D8).
  Future<AdminUserDetail> grantPremium(String id, DateTime until) async =>
      AdminUserDetail.fromJson(await _api.postJson(
        '${_userPath(id)}/premium',
        {'period_end': _day(until)},
      ));

  /// Ends the admin's grant, then reads the user again: the client's DELETE
  /// does not return the answer's body.
  Future<AdminUserDetail> endPremium(String id) async {
    await _api.delete('${_userPath(id)}/premium');
    return user(id);
  }

  /// Deletes the account, confirmed by its address as the admin typed it (D9).
  Future<void> deleteUser(String id, String typedEmail) =>
      _api.delete(_userPath(id), body: {'email': typedEmail});

  static String _userPath(String id) => '$_kPath/${Uri.encodeComponent(id)}';

  static String _day(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';
}
