/// The owner's lists and gifts, over the server's endpoints
/// (LISTS_GIFTS_SHARING_PLAN D8).
library;

import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';

/// Who a list is for, chosen at creation and never changed (D2).
enum RecipientKind {
  self('self'),
  other('other');

  const RecipientKind(this.json);

  final String json;

  static RecipientKind fromJson(String value) =>
      values.firstWhere((kind) => kind.json == value);
}

/// A list as `GET /api/lists` gives it.
class ListSummary {
  const ListSummary({
    required this.id,
    required this.title,
    required this.recipientKind,
    required this.recipientName,
    required this.giftCount,
  });

  factory ListSummary.fromJson(Map<String, dynamic> json) => ListSummary(
        id: json['id'] as String,
        title: json['title'] as String,
        recipientKind: RecipientKind.fromJson(json['recipient_kind'] as String),
        recipientName: json['recipient_name'] as String?,
        giftCount: json['gift_count'] as int,
      );

  final String id;
  final String title;
  final RecipientKind recipientKind;

  /// Set exactly when [recipientKind] is [RecipientKind.other].
  final String? recipientName;
  final int giftCount;
}

/// A list with its gifts, oldest first, its occasions, by date, and the
/// gifts off the list, received and revealed (HIDDEN_GIFTS_PLAN D5, D6), as
/// `GET /api/lists/{id}` gives it.
class ListDetail {
  const ListDetail({
    required this.id,
    required this.title,
    required this.recipientKind,
    required this.recipientName,
    required this.gifts,
    this.occasions = const [],
    this.received = const [],
    this.revealed = const [],
  });

  factory ListDetail.fromJson(Map<String, dynamic> json) => ListDetail(
        id: json['id'] as String,
        title: json['title'] as String,
        recipientKind: RecipientKind.fromJson(json['recipient_kind'] as String),
        recipientName: json['recipient_name'] as String?,
        gifts: [
          for (final gift in json['gifts'] as List<dynamic>)
            Gift.fromJson(gift as Map<String, dynamic>),
        ],
        occasions: [
          for (final occasion in json['occasions'] as List<dynamic>)
            Occasion.fromJson(occasion as Map<String, dynamic>),
        ],
        received: _gifts(json['received']),
        revealed: _gifts(json['revealed']),
      );

  /// Empty when absent: a server older than hidden gifts has neither key.
  static List<Gift> _gifts(Object? json) => [
        for (final gift in (json as List<dynamic>?) ?? const [])
          Gift.fromJson(gift as Map<String, dynamic>),
      ];

  final String id;
  final String title;
  final RecipientKind recipientKind;
  final String? recipientName;
  final List<Gift> gifts;
  final List<Occasion> occasions;

  /// Gifts its owners marked received, newest first (D5).
  final List<Gift> received;

  /// Gifts an occasion's givers added hidden and bought, once the occasion
  /// has passed: the gift alone, by title (D6).
  final List<Gift> revealed;
}

/// An occasion as its list's owners see it (D4, D8).
class Occasion {
  const Occasion({
    required this.id,
    required this.listId,
    required this.name,
    required this.date,
    required this.joinToken,
    required this.memberCount,
  });

  factory Occasion.fromJson(Map<String, dynamic> json) => Occasion(
        id: json['id'] as String,
        listId: json['list_id'] as String,
        name: json['name'] as String,
        date: parseDate(json['date'] as String),
        joinToken: json['join_token'] as String?,
        memberCount: json['member_count'] as int,
      );

  final String id;
  final String listId;
  final String name;

  /// A calendar day, at midnight; no time (D4).
  final DateTime date;

  /// What the occasion's link carries; null when it has no link.
  final String? joinToken;

  /// The invitees who joined, removed people not counted.
  final int memberCount;
}

/// Someone who joined an occasion, or whom an owner removed from it.
class Member {
  const Member({
    required this.userId,
    required this.displayName,
    required this.removed,
  });

  factory Member.fromJson(Map<String, dynamic> json) => Member(
        userId: json['user_id'] as String,
        displayName: json['display_name'] as String,
        removed: json['removed'] as bool,
      );

  final String userId;
  final String displayName;

  /// Removed by an owner: no link lets them back until they are allowed
  /// again.
  final bool removed;
}

/// A JSON calendar day (`2026-12-24`) as a [DateTime] at midnight.
DateTime parseDate(String value) {
  final date = DateTime.parse(value);
  return DateTime(date.year, date.month, date.day);
}

/// [date]'s calendar day as JSON (`2026-12-24`).
String formatJsonDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

/// A gift's picture as the server describes it (GIFT_IMAGES D11). The paths
/// are the server's to choose: the owner's are under `/api/images`, the
/// invitee's under the occasion. Used as they come.
class GiftImage {
  const GiftImage({
    required this.id,
    required this.width,
    required this.height,
    required this.url,
    required this.thumbUrl,
  });

  factory GiftImage.fromJson(Map<String, dynamic> json) => GiftImage(
        id: json['id'] as String,
        width: json['width'] as int,
        height: json['height'] as int,
        url: json['url'] as String,
        thumbUrl: json['thumb_url'] as String,
      );

  /// Null when the JSON has no image or a null one.
  static GiftImage? fromJsonOrNull(Object? json) =>
      json == null ? null : GiftImage.fromJson(json as Map<String, dynamic>);

  final String id;
  final int width;
  final int height;

  /// The full version (at most 1600 px on its longest side).
  final String url;

  /// The 256 px square.
  final String thumbUrl;
}

/// An uploaded image waiting to be attached by saving a gift: the same
/// object as a gift's image (D11).
typedef PendingImage = GiftImage;

/// What saving a gift does to its image (D11): `image_id` absent, an id, or
/// `null`.
sealed class ImageChange {
  const ImageChange();
}

/// Leaves the image as it is; sends no `image_id`.
class KeepImage extends ImageChange {
  const KeepImage();
}

/// Attaches the pending image [id].
class AttachImage extends ImageChange {
  const AttachImage(this.id);

  final String id;
}

/// Removes the image; sends `image_id: null`.
class RemoveImage extends ImageChange {
  const RemoveImage();
}

/// What a gift says (D3). Also the body of an add or an edit.
class GiftDraft {
  const GiftDraft({
    required this.title,
    this.description = '',
    this.links = const [],
    this.priceAmount,
    this.priceCurrency,
    this.imageChange = const KeepImage(),
  });

  final String title;
  final String description;

  /// Absolute `http` or `https` URLs, at most 10.
  final List<String> links;

  /// A decimal string such as `"149.00"`, never a binary float; null with
  /// [priceCurrency] when the gift has no price.
  final String? priceAmount;

  /// An ISO 4217 code in capitals; set exactly when [priceAmount] is.
  final String? priceCurrency;

  /// What the save does to the gift's image; unchanged unless the owner
  /// chose otherwise.
  final ImageChange imageChange;

  /// Every field, so an edit also clears a description, the links or the
  /// price the owner removed; `image_id` only when the image changes.
  Map<String, dynamic> toJson() => {
        'title': title,
        'description': description,
        'links': links,
        'price_amount': priceAmount,
        'price_currency': priceCurrency,
        ...switch (imageChange) {
          KeepImage() => <String, dynamic>{},
          AttachImage(:final id) => {'image_id': id},
          RemoveImage() => {'image_id': null},
        },
      };
}

/// A gift as the server stores it.
class Gift extends GiftDraft {
  const Gift({
    required this.id,
    required this.listId,
    required super.title,
    super.description,
    super.links,
    super.priceAmount,
    super.priceCurrency,
    this.image,
  });

  factory Gift.fromJson(Map<String, dynamic> json) => Gift(
        id: json['id'] as String,
        listId: json['list_id'] as String,
        title: json['title'] as String,
        description: json['description'] as String,
        links: [for (final link in json['links'] as List<dynamic>) link as String],
        priceAmount: json['price_amount'] as String?,
        priceCurrency: json['price_currency'] as String?,
        image: GiftImage.fromJsonOrNull(json['image']),
      );

  final String id;
  final String listId;

  /// Null when the gift has no picture.
  final GiftImage? image;
}

/// Putting back or keeping a gift the server answered 409 `not_revealed`
/// (HIDDEN_GIFTS_PLAN D5, D6): its occasion's date was moved later since it
/// was revealed, so it can be put back once that date has passed. Nothing
/// changed.
class NotRevealed implements Exception {
  const NotRevealed();

  @override
  String toString() => 'NotRevealed';
}

/// The list, gift and occasion calls of a list's owner. Errors are
/// [ApiClient]'s: a list, gift or occasion that is gone, or not the user's,
/// is an [ApiException] with status 404 (D7).
class ListsRepository {
  ListsRepository(this._api);

  /// Over the app's [ApiClient], from the providers.
  factory ListsRepository.of(BuildContext context) =>
      ListsRepository(context.read<ApiClient>());

  final ApiClient _api;

  /// The lists I own, oldest first.
  Future<List<ListSummary>> myLists() async => [
        for (final list in await _api.getJsonList('/api/lists'))
          ListSummary.fromJson(list as Map<String, dynamic>),
      ];

  /// Creates a list I own; returns its id. [recipientName] only for
  /// [RecipientKind.other].
  Future<String> createList({
    required String title,
    required RecipientKind recipientKind,
    String? recipientName,
  }) async {
    final created = await _api.postJson('/api/lists', {
      'title': title,
      'recipient_kind': recipientKind.json,
      if (recipientKind == RecipientKind.other) 'recipient_name': recipientName,
    });
    return created['id'] as String;
  }

  Future<ListDetail> list(String id) async =>
      ListDetail.fromJson(await _api.getJson('/api/lists/${_segment(id)}'));

  /// Renames the list and, for a list for someone else, its recipient.
  Future<void> updateList(
    String id, {
    required String title,
    String? recipientName,
  }) =>
      _api.patchJson('/api/lists/${_segment(id)}', {
        'title': title,
        'recipient_name': ?recipientName,
      });

  /// Deletes the list with its gifts.
  Future<void> deleteList(String id) =>
      _api.delete('/api/lists/${_segment(id)}');

  Future<Gift> addGift(String listId, GiftDraft gift) async => Gift.fromJson(
        await _api.postJson(
          '/api/lists/${_segment(listId)}/gifts',
          gift.toJson(),
        ),
      );

  Future<Gift> updateGift(String giftId, GiftDraft gift) async =>
      Gift.fromJson(
        await _api.patchJson('/api/gifts/${_segment(giftId)}', gift.toJson()),
      );

  /// Deletes the gift; also how a revealed gift is dismissed (D6).
  Future<void> deleteGift(String giftId) =>
      _api.delete('/api/gifts/${_segment(giftId)}');

  /// Takes the gift off the list and out of every occasion, under
  /// "Received" (D5). Marking it twice is fine.
  Future<void> markReceived(String giftId) =>
      _api.post('/api/gifts/${_segment(giftId)}/received');

  /// Puts a received gift back where it was, with its reservations (D5). A
  /// gift that is not received is fine; [NotRevealed] when it cannot be put
  /// back yet.
  Future<void> putBack(String giftId) => _revealedOnly(
        () => _api.delete('/api/gifts/${_segment(giftId)}/received'),
      );

  /// Keeps a revealed gift on the list; the answer is the gift now on it,
  /// under a new id (D6). [NotRevealed] for a gift that is not revealed.
  Future<Gift> keep(String giftId) async => Gift.fromJson(
        await _revealedOnly(
          () => _api.postJson('/api/gifts/${_segment(giftId)}/keep', {}),
        ),
      );

  /// A 409 `not_revealed` becomes [NotRevealed]; anything else stays
  /// [ApiClient]'s.
  static Future<T> _revealedOnly<T>(Future<T> Function() call) async {
    try {
      return await call();
    } on ApiException catch (error) {
      if (error.statusCode == 409 && error.body?['code'] == 'not_revealed') {
        throw const NotRevealed();
      }
      rethrow;
    }
  }

  /// Sends the image's bytes; the answer is a pending image that saving a
  /// gift attaches (GIFT_IMAGES D1). A refusal is an [ApiException] whose
  /// body carries a stable `detail` code (D11).
  Future<PendingImage> uploadImage(Uint8List bytes) async =>
      GiftImage.fromJson(await _api.postBytes('/api/images', bytes));

  /// Has the server download the image at [url] (D6). It may take the
  /// fetch's 20 s plus the processing lock's 30 s wait, so the call waits
  /// 60 s instead of 10 (review R1-5).
  Future<PendingImage> imageFromUrl(String url) async => GiftImage.fromJson(
        await _api.postJson(
          '/api/images/from-url',
          {'url': url},
          timeout: const Duration(seconds: 60),
        ),
      );

  /// Creates an occasion of the list, without a link yet (D5).
  Future<Occasion> createOccasion(
    String listId, {
    required String name,
    required DateTime date,
  }) async =>
      Occasion.fromJson(
        await _api.postJson('/api/lists/${_segment(listId)}/occasions', {
          'name': name,
          'date': formatJsonDate(date),
        }),
      );

  Future<Occasion> updateOccasion(
    String occasionId, {
    required String name,
    required DateTime date,
  }) async =>
      Occasion.fromJson(
        await _api.patchJson('/api/occasions/${_segment(occasionId)}', {
          'name': name,
          'date': formatJsonDate(date),
        }),
      );

  /// Deletes the occasion with its memberships.
  Future<void> deleteOccasion(String occasionId) =>
      _api.delete('/api/occasions/${_segment(occasionId)}');

  /// Creates the occasion's link, or replaces it: the previous link stops
  /// working, invitees who joined keep their access (D5).
  Future<Occasion> createLink(String occasionId) async => Occasion.fromJson(
        await _api.postJson('/api/occasions/${_segment(occasionId)}/link', {}),
      );

  /// Revokes the occasion's link: nobody new can join with it.
  Future<void> revokeLink(String occasionId) =>
      _api.delete('/api/occasions/${_segment(occasionId)}/link');

  /// Who joined, in the order they joined, then the people removed.
  Future<List<Member>> members(String occasionId) async => [
        for (final member in await _api.getJsonList(
          '/api/occasions/${_segment(occasionId)}/members',
        ))
          Member.fromJson(member as Map<String, dynamic>),
      ];

  /// Removes an invitee: they lose access at once and no link lets them back
  /// until they are allowed again (D4).
  Future<void> removeMember(String occasionId, String userId) => _api.delete(
        '/api/occasions/${_segment(occasionId)}/members/${_segment(userId)}',
      );

  /// Allows a removed person again; they still need a link to rejoin.
  Future<void> allowAgain(String occasionId, String userId) => _api.delete(
        '/api/occasions/${_segment(occasionId)}/removals/${_segment(userId)}',
      );

  /// Ids come from the location bar too: encoded, so one cannot add a path
  /// or a query to the call.
  static String _segment(String id) => Uri.encodeComponent(id);
}
