/// Where the session token is kept between runs (ACCOUNTS_PLAN D10).
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kTokenKey = 'wishlist.session_token';

/// Reads, writes and forgets the one session token of this device.
abstract class TokenStore {
  /// The platform's store: secure storage on Android and iOS, the browser's
  /// local storage on the web, where any script in the page could read it
  /// (the review envelope's "Web token storage").
  factory TokenStore.forPlatform() =>
      kIsWeb ? PreferencesTokenStore() : SecureTokenStore();

  Future<String?> read();
  Future<void> write(String token);
  Future<void> clear();
}

/// The Android Keystore or the iOS Keychain, through flutter_secure_storage.
class SecureTokenStore implements TokenStore {
  SecureTokenStore([this._storage = const FlutterSecureStorage()]);

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read() => _storage.read(key: _kTokenKey);

  @override
  Future<void> write(String token) =>
      _storage.write(key: _kTokenKey, value: token);

  @override
  Future<void> clear() => _storage.delete(key: _kTokenKey);
}

/// The browser's local storage, through shared_preferences.
class PreferencesTokenStore implements TokenStore {
  @override
  Future<String?> read() async =>
      (await SharedPreferences.getInstance()).getString(_kTokenKey);

  @override
  Future<void> write(String token) async =>
      (await SharedPreferences.getInstance()).setString(_kTokenKey, token);

  @override
  Future<void> clear() async =>
      (await SharedPreferences.getInstance()).remove(_kTokenKey);
}
