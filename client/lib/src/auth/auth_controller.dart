/// Who is signed in, and the calls that change it (ACCOUNTS_PLAN D10).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import 'token_store.dart';

/// The signed-in user, as `/api/me` and sign-in report them (D7).
class AccountUser {
  const AccountUser({
    required this.id,
    required this.email,
    required this.displayName,
  });

  factory AccountUser.fromJson(Map<String, dynamic> json) => AccountUser(
        id: json['id'] as String,
        email: json['email'] as String,
        displayName: json['display_name'] as String,
      );

  final String id;
  final String email;

  /// Google's name for the account; can be empty.
  final String displayName;

  /// The display name, or the email when there is none.
  String get name => displayName.isEmpty ? email : displayName;
}

enum AuthStatus {
  /// Reading the stored token and checking it with `/api/me`, at start.
  restoring,

  /// A token is stored but the server could not confirm it (unreachable, or
  /// an error other than 401). The token is kept; [AuthController.restore]
  /// tries again.
  unavailable,

  /// No session.
  signedOut,

  /// The server is checking a Google ID token.
  signingIn,

  /// Signed in as [AuthController.user].
  signedIn,

  /// The last sign-in failed, for [AuthController.failure]. No session.
  failed,
}

/// Why a sign-in failed.
enum SignInFailure {
  /// The server refused the Google ID token (401).
  rejected,

  /// Google sign-in is not configured on the server (503).
  notConfigured,

  /// The server could not be reached.
  unreachable,

  /// The server answered another error, or something unexpected.
  serverError,
}

/// The session: restores it at start, signs in with a Google ID token, signs
/// out and deletes the account. Any 401 on a call made with the session ends
/// it (D10), whatever screen made the call.
class AuthController extends ChangeNotifier {
  AuthController({required this._api, required this._store}) {
    _api.onUnauthorized = _onUnauthorized;
  }

  final ApiClient _api;
  final TokenStore _store;

  AuthStatus _status = AuthStatus.restoring;
  AccountUser? _user;
  SignInFailure? _failure;

  AuthStatus get status => _status;

  /// Set exactly when [status] is [AuthStatus.signedIn].
  AccountUser? get user => _user;

  /// Set exactly when [status] is [AuthStatus.failed].
  SignInFailure? get failure => _failure;

  bool get isSignedIn => _status == AuthStatus.signedIn;

  /// Restores the stored session, at start or to retry after
  /// [AuthStatus.unavailable]. A 401 forgets the token; any other failure
  /// keeps it, so an outage does not sign anyone out.
  Future<void> restore() async {
    _set(AuthStatus.restoring);
    String? token;
    try {
      token = await _store.read();
    } catch (_) {
      // An unreadable store holds no usable session.
      token = null;
    }
    if (token == null) {
      _set(AuthStatus.signedOut);
      return;
    }
    _api.token = token;
    try {
      _user = AccountUser.fromJson(await _api.getJson('/api/me'));
      _set(AuthStatus.signedIn);
    } on UnauthorizedException {
      await _endSession();
    } catch (_) {
      _set(AuthStatus.unavailable);
    }
  }

  /// Exchanges a Google ID token for a session (`POST /api/auth/google`).
  Future<void> signInWithGoogle(String idToken) async {
    _set(AuthStatus.signingIn);
    try {
      final body =
          await _api.postJson('/api/auth/google', {'id_token': idToken});
      final token = body['token'] as String;
      final user = AccountUser.fromJson(body['user'] as Map<String, dynamic>);
      try {
        await _store.write(token);
      } catch (_) {
        // Signed in for this run only: the next start asks again.
      }
      _api.token = token;
      _user = user;
      _set(AuthStatus.signedIn);
    } on UnauthorizedException {
      _fail(SignInFailure.rejected);
    } on ApiException catch (e) {
      _fail(e.statusCode == 503
          ? SignInFailure.notConfigured
          : SignInFailure.serverError);
    } on ApiUnreachableException {
      _fail(SignInFailure.unreachable);
    } catch (_) {
      // An answer without the expected token or user.
      _fail(SignInFailure.serverError);
    }
  }

  /// Ends the session on the server (`POST /api/auth/sign-out`) and here.
  /// Signed out here whatever the server answers: if it cannot be reached,
  /// its session row expires on its own (D4).
  Future<void> signOut() async {
    if (_api.token != null) {
      try {
        await _api.post('/api/auth/sign-out');
      } catch (_) {}
    }
    await _endSession();
  }

  /// Deletes the account (`DELETE /api/me`), then ends the session. Throws
  /// [ApiException] or [ApiUnreachableException] when the server did not
  /// delete it, and the user stays signed in. A 401 means the session was
  /// already gone: the user is signed out.
  Future<void> deleteAccount() async {
    try {
      await _api.delete('/api/me');
    } on UnauthorizedException {
      return;
    }
    await _endSession();
  }

  /// A 401 to a call made with [token]. A late answer to a call made with an
  /// older session must not end the current one.
  void _onUnauthorized(String token) {
    if (_api.token == token) unawaited(_endSession());
  }

  Future<void> _endSession() async {
    _api.token = null;
    if (_status != AuthStatus.signedOut) _set(AuthStatus.signedOut);
    try {
      await _store.clear();
    } catch (_) {
      // The next start finds the token refused (401) and clears it then.
    }
  }

  void _fail(SignInFailure failure) {
    _failure = failure;
    _set(AuthStatus.failed);
  }

  void _set(AuthStatus status) {
    _status = status;
    if (status != AuthStatus.signedIn) _user = null;
    if (status != AuthStatus.failed) _failure = null;
    notifyListeners();
  }
}
