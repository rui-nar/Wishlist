/// The account's email switch and language, and unsubscribing from an email
/// link (COMMENTS_NOTIFICATIONS_PLAN D17, D18).
library;

import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';

const _kPath = '/api/me/preferences';

/// `GET /api/me/preferences`.
class Preferences {
  const Preferences({required this.emailNotifications, required this.language});

  factory Preferences.fromJson(Map<String, dynamic> json) => Preferences(
        emailNotifications: json['email_notifications'] as bool,
        language: json['language'] as String,
      );

  final bool emailNotifications;

  /// `en` or `fr`: what emails are written in.
  final String language;
}

class PreferencesRepository {
  PreferencesRepository(this._api);

  factory PreferencesRepository.of(BuildContext context) =>
      PreferencesRepository(context.read<ApiClient>());

  final ApiClient _api;

  Future<Preferences> preferences() async =>
      Preferences.fromJson(await _api.getJson(_kPath));

  Future<Preferences> setEmailNotifications(bool on) async =>
      Preferences.fromJson(
        await _api.patchJson(_kPath, {'email_notifications': on}),
      );

  Future<Preferences> setLanguage(String language) async =>
      Preferences.fromJson(await _api.patchJson(_kPath, {'language': language}));

  /// Turns email notifications off for the account [token] was made for.
  ///
  /// Without a session, whoever is signed in here: the link speaks for its
  /// own account, and it must not sign anyone out.
  Future<void> unsubscribe(String token) =>
      ApiClient(_api.httpClient, baseUrl: _api.baseUrl)
          .post('/api/unsubscribe/${Uri.encodeComponent(token)}');
}
