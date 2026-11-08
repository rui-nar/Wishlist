/// What invitees see and do: the occasions shared with them, an occasion's
/// list and gifts, joining by link and leaving (LISTS_GIFTS_SHARING_PLAN D5,
/// D6, D8).
library;

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../lists/lists_repository.dart';

/// An occasion as one of its invitees sees it (`GET /api/shared`). Never a
/// join token, a member or another occasion of the list: the server's
/// invitee model has none.
class SharedOccasion {
  const SharedOccasion({
    required this.id,
    required this.name,
    required this.date,
    required this.listTitle,
    required this.recipientName,
    required this.ownerNames,
  });

  factory SharedOccasion.fromJson(Map<String, dynamic> json) => SharedOccasion(
        id: json['id'] as String,
        name: json['name'] as String,
        date: parseDate(json['date'] as String),
        listTitle: json['list_title'] as String,
        recipientName: json['recipient_name'] as String,
        ownerNames: _names(json['owner_names']),
      );

  final String id;
  final String name;
  final DateTime date;
  final String listTitle;

  /// Who the gifts are for: the list's recipient, or its owners' names for a
  /// list they made for themselves.
  final String recipientName;
  final List<String> ownerNames;
}

/// A gift as an invitee sees it.
class SharedGift extends GiftDraft {
  const SharedGift({
    required this.id,
    required super.title,
    super.description,
    super.links,
    super.priceAmount,
    super.priceCurrency,
  });

  factory SharedGift.fromJson(Map<String, dynamic> json) => SharedGift(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String,
        links: [for (final link in json['links'] as List<dynamic>) link as String],
        priceAmount: json['price_amount'] as String?,
        priceCurrency: json['price_currency'] as String?,
      );

  final String id;
}

/// `GET /api/occasions/{id}`, told apart by its `role`.
sealed class OccasionView {
  const OccasionView();
}

/// The caller owns the occasion's list: the list is where they manage it.
class OwnedOccasion extends OccasionView {
  const OwnedOccasion(this.listId);

  final String listId;
}

/// The caller is an invitee: the occasion, its list and its gifts.
class InviteeOccasion extends OccasionView {
  const InviteeOccasion({required this.occasion, required this.gifts});

  final SharedOccasion occasion;

  /// Oldest first.
  final List<SharedGift> gifts;
}

/// Who opens a link, for the join screen.
enum JoinRole {
  /// Owns the list: opens it instead of joining (D6).
  owner,

  /// Already joined: opens the occasion.
  member,

  /// May join, once they confirm.
  none,
}

/// What a link would join (`POST /api/join/preview`), for the confirmation.
class JoinPreview {
  const JoinPreview({
    required this.name,
    required this.date,
    required this.listTitle,
    required this.recipientName,
    required this.ownerNames,
    required this.role,
    this.listId,
    this.occasionId,
  });

  factory JoinPreview.fromJson(Map<String, dynamic> json) => JoinPreview(
        name: json['name'] as String,
        date: parseDate(json['date'] as String),
        listTitle: json['list_title'] as String,
        recipientName: json['recipient_name'] as String,
        ownerNames: _names(json['owner_names']),
        role: JoinRole.values.byName(json['role'] as String),
        listId: json['list_id'] as String?,
        occasionId: json['occasion_id'] as String?,
      );

  final String name;
  final DateTime date;
  final String listTitle;
  final String recipientName;
  final List<String> ownerNames;
  final JoinRole role;

  /// The list to open, for an owner.
  final String? listId;

  /// The occasion to open, for a member.
  final String? occasionId;
}

/// How a join ended.
sealed class JoinOutcome {
  const JoinOutcome();
}

/// The user is a member of the occasion, now or from before.
class Joined extends JoinOutcome {
  const Joined(this.occasionId);

  final String occasionId;
}

/// The user owns the list (409): they open it instead (D6).
class OwnsList extends JoinOutcome {
  const OwnsList(this.listId);

  final String listId;
}

/// The invitee calls. Errors are [ApiClient]'s: an occasion that is gone or
/// not shared with the user, and a link that is unknown, regenerated,
/// revoked or refused to this user, are an [ApiException] with status 404.
class SharedRepository {
  SharedRepository(this._api);

  /// Over the app's [ApiClient], from the providers.
  factory SharedRepository.of(BuildContext context) =>
      SharedRepository(context.read<ApiClient>());

  final ApiClient _api;

  /// The occasions I joined, by date.
  Future<List<SharedOccasion>> shared() async => [
        for (final occasion in await _api.getJsonList('/api/shared'))
          SharedOccasion.fromJson(occasion as Map<String, dynamic>),
      ];

  Future<OccasionView> occasion(String id) async {
    final json = await _api.getJson('/api/occasions/${_segment(id)}');
    if (json['role'] == 'owner') {
      return OwnedOccasion((json['list'] as Map<String, dynamic>)['id'] as String);
    }
    return InviteeOccasion(
      occasion: SharedOccasion.fromJson(json),
      gifts: [
        for (final gift in json['gifts'] as List<dynamic>)
          SharedGift.fromJson(gift as Map<String, dynamic>),
      ],
    );
  }

  /// Leaves the occasion; a current link lets me join again.
  Future<void> leave(String occasionId) =>
      _api.delete('/api/occasions/${_segment(occasionId)}/membership');

  /// The token is in the body, never in the URL (D5).
  Future<JoinPreview> preview(String token) async =>
      JoinPreview.fromJson(await _api.postJson('/api/join/preview', {
        'token': token,
      }));

  Future<JoinOutcome> join(String token) async {
    try {
      final joined = await _api.postJson('/api/join', {'token': token});
      return Joined(joined['occasion_id'] as String);
    } on ApiException catch (error) {
      final listId = error.body?['list_id'];
      if (error.statusCode == 409 && listId is String) return OwnsList(listId);
      rethrow;
    }
  }

  /// Ids come from the location bar too: encoded, so one cannot add a path
  /// or a query to the call.
  static String _segment(String id) => Uri.encodeComponent(id);
}

List<String> _names(Object? names) =>
    [for (final name in names as List<dynamic>) name as String];
