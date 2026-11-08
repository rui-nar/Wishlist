/// What invitees see and do: the occasions shared with them, an occasion's
/// list and gifts, joining by link and leaving (LISTS_GIFTS_SHARING_PLAN D5,
/// D6, D8); reserving, group gifts and marking bought (RESERVING_PLAN D6).
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
    this.image,
  });

  factory SharedGift.fromJson(Map<String, dynamic> json) => SharedGift(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String,
        links: [for (final link in json['links'] as List<dynamic>) link as String],
        priceAmount: json['price_amount'] as String?,
        priceCurrency: json['price_currency'] as String?,
        image: GiftImage.fromJsonOrNull(json['image']),
      );

  final String id;

  /// Its paths are under the occasion; null when the gift has no picture.
  final GiftImage? image;
}

/// `GET /api/occasions/{id}`, told apart by its `role`.
sealed class OccasionView {
  const OccasionView();
}

/// The caller owns the occasion's list: the list is where they manage it.
/// When the list is for someone else, they give too, from the occasion
/// (RESERVING_PLAN D4, D14).
class OwnedOccasion extends OccasionView {
  const OwnedOccasion({
    required this.listId,
    required this.listTitle,
    required this.recipientKind,
    required this.recipientName,
    required this.name,
    required this.date,
    required this.gifts,
  });

  final String listId;
  final String listTitle;
  final RecipientKind recipientKind;

  /// Set exactly when [recipientKind] is [RecipientKind.other].
  final String? recipientName;
  final String name;
  final DateTime date;

  /// Oldest first; their image paths are the owners'.
  final List<SharedGift> gifts;

  /// The owner gives on this occasion; a recipient never does (D4).
  bool get givesHere => recipientKind == RecipientKind.other;
}

/// The caller is an invitee: the occasion, its list and its gifts.
class InviteeOccasion extends OccasionView {
  const InviteeOccasion({required this.occasion, required this.gifts});

  final SharedOccasion occasion;

  /// Oldest first.
  final List<SharedGift> gifts;
}

/// What holds a gift, as a giver of the occasion sees it (RESERVING_PLAN D6).
enum ClaimState {
  /// Reserved by one giver of this occasion.
  reserved,

  /// A group gift of this occasion.
  group,

  /// Held from another occasion: not by whom, nor where.
  taken,
}

/// Someone in a claim. No user id: [mine] says which one is the user.
class ClaimParticipant {
  const ClaimParticipant({
    required this.displayName,
    required this.mine,
    this.pledgeAmount,
    this.pledgeCurrency,
  });

  factory ClaimParticipant.fromJson(Map<String, dynamic> json) =>
      ClaimParticipant(
        displayName: json['display_name'] as String,
        mine: json['mine'] as bool,
        pledgeAmount: json['pledge_amount'] as String?,
        pledgeCurrency: json['pledge_currency'] as String?,
      );

  final String displayName;
  final bool mine;

  /// The server's decimal string, in [pledgeCurrency] (the gift's when it
  /// was pledged, D9); both null without an amount.
  final String? pledgeAmount;
  final String? pledgeCurrency;
}

/// A gift's claim. A gift with none is free.
class GiftClaim {
  const GiftClaim({
    required this.giftId,
    required this.state,
    required this.bought,
    required this.participants,
    this.expired = false,
  });

  factory GiftClaim.fromJson(Map<String, dynamic> json) => GiftClaim(
        giftId: json['gift_id'] as String,
        state: ClaimState.values.byName(json['state'] as String),
        bought: json['bought'] as bool,
        expired: json['expired'] as bool,
        participants: [
          for (final participant in json['participants'] as List<dynamic>)
            ClaimParticipant.fromJson(participant as Map<String, dynamic>),
        ],
      );

  final String giftId;
  final ClaimState state;

  /// Final; always false when [state] is [ClaimState.taken].
  final bool bought;

  /// The user's own unbought claim of an occasion that has passed: it no
  /// longer holds the gift, but they may still mark it bought (D8, review
  /// R3-1). Nobody else's expired claim is ever read.
  final bool expired;

  /// By when they joined; always empty when [state] is [ClaimState.taken].
  final List<ClaimParticipant> participants;

  /// Whether the user is in it.
  bool get mine => participants.any((participant) => participant.mine);
}

/// An occasion's activity (`GET /api/occasions/{id}/claims`).
class OccasionClaims {
  const OccasionClaims({required this.passed, required this.gifts});

  factory OccasionClaims.fromJson(Map<String, dynamic> json) => OccasionClaims(
        passed: json['passed'] as bool,
        gifts: {
          for (final gift in json['gifts'] as List<dynamic>)
            (gift as Map<String, dynamic>)['gift_id'] as String:
                GiftClaim.fromJson(gift),
        },
      );

  /// The occasion's date has passed: nothing can be done any more but
  /// marking bought the user's own [GiftClaim.expired] claims (D8).
  final bool passed;

  /// Gift id → its claim; a gift absent from it is free. Once [passed], it
  /// also has the user's own unbought claims, [GiftClaim.expired].
  final Map<String, GiftClaim> gifts;
}

/// Why the server refused a claim write (a 409).
enum ClaimConflictCode {
  /// Someone else holds the gift, here or in another occasion.
  taken,

  /// The gift is bought, which is final.
  bought,

  /// The occasion's date has passed.
  passed,
}

/// A claim write the server refused with a 409 and its [code].
class ClaimConflict implements Exception {
  const ClaimConflict(this.code);

  final ClaimConflictCode code;

  @override
  String toString() => 'ClaimConflict: ${code.name}';
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
    final gifts = [
      for (final gift in json['gifts'] as List<dynamic>)
        SharedGift.fromJson(gift as Map<String, dynamic>),
    ];
    if (json['role'] == 'owner') {
      final list = json['list'] as Map<String, dynamic>;
      return OwnedOccasion(
        listId: list['id'] as String,
        listTitle: list['title'] as String,
        recipientKind: RecipientKind.fromJson(list['recipient_kind'] as String),
        recipientName: list['recipient_name'] as String?,
        name: json['name'] as String,
        date: parseDate(json['date'] as String),
        gifts: gifts,
      );
    }
    return InviteeOccasion(
      occasion: SharedOccasion.fromJson(json),
      gifts: gifts,
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

  /// What the occasion's givers did, for a giver of it; a recipient is never
  /// asked (RESERVING_PLAN D4, D14).
  Future<OccasionClaims> claims(String occasionId) async =>
      OccasionClaims.fromJson(
        await _api.getJson('/api/occasions/${_segment(occasionId)}/claims'),
      );

  /// Reserves the gift; mine already is fine. [ClaimConflict] `taken` when
  /// someone else holds it.
  Future<void> reserve(String occasionId, String giftId) =>
      _claim(() => _api.post('${_gift(occasionId, giftId)}/reservation'));

  /// Releases my reservation; holding none is fine. [ClaimConflict]
  /// `bought` once bought.
  Future<void> release(String occasionId, String giftId) =>
      _claim(() => _api.delete('${_gift(occasionId, giftId)}/reservation'));

  /// Marks bought, for good: my reservation, a group gift I am in, or a free
  /// gift (reserved and bought at once).
  Future<void> markBought(String occasionId, String giftId) =>
      _claim(() => _api.post('${_gift(occasionId, giftId)}/bought'));

  /// Joins the group gift, starting it when the gift is free, or changes my
  /// [amount] (a decimal string in the gift's currency; null for none).
  Future<void> pledge(String occasionId, String giftId, String? amount) =>
      _claim(
        () => _api.putJson('${_gift(occasionId, giftId)}/pledge', {
          'amount': amount,
        }),
      );

  /// Leaves the group gift; not being in it is fine.
  Future<void> leaveGroup(String occasionId, String giftId) =>
      _claim(() => _api.delete('${_gift(occasionId, giftId)}/pledge'));

  /// A 409 with a known code becomes a [ClaimConflict]; anything else stays
  /// [ApiClient]'s.
  static Future<void> _claim(Future<Object?> Function() call) async {
    try {
      await call();
    } on ApiException catch (error) {
      final code = ClaimConflictCode.values.asNameMap()[error.body?['code']];
      if (error.statusCode == 409 && code != null) throw ClaimConflict(code);
      rethrow;
    }
  }

  static String _gift(String occasionId, String giftId) =>
      '/api/occasions/${_segment(occasionId)}/gifts/${_segment(giftId)}';

  /// Ids come from the location bar too: encoded, so one cannot add a path
  /// or a query to the call.
  static String _segment(String id) => Uri.encodeComponent(id);
}

List<String> _names(Object? names) =>
    [for (final name in names as List<dynamic>) name as String];
