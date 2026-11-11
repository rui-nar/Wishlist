/// Who is signed in, and the calls that change it (ACCOUNTS_PLAN D10).
library;

import 'dart:async';
import 'dart:developer';

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

  /// The account's name, from Google or typed at sign-up; can be empty.
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

  /// The server is checking a Google or Apple ID token, or an email and
  /// password.
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

  /// The server refused the Apple ID token (401).
  appleRejected,

  /// Apple's own flow failed before reaching the server. Cancelling is not
  /// a failure.
  appleFailed,

  /// The email address and password do not match an account (401). One
  /// answer for every cause, so nothing is learnt about the address (D10).
  wrongCredentials,

  /// Too many attempts for now (429).
  tooManyAttempts,

  /// Google sign-in is not configured on the server (503).
  notConfigured,

  /// The server could not be reached.
  unreachable,

  /// The server answered another error, or something unexpected.
  serverError,
}

/// Why a mailed link could not be used to choose a password (D9).
enum EmailLinkFailure {
  /// Forged, used or past its hour (410): only a new link helps.
  expired,

  /// Too many attempts for now (429).
  tooManyAttempts,

  /// The server refused the name or the password (422).
  notAccepted,

  /// The server could not be reached.
  unreachable,

  /// The server answered another error, or something unexpected.
  serverError,
}

/// The session: restores it at start, signs in with a Google ID token or an
/// email and password, completes a mailed link, signs out and deletes the
/// account. Any 401 on a call made with the session ends
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

  bool _isAdmin = false;

  /// `is_admin` from `/api/me` (admin panel plan D2): shows the admin panel's
  /// entry and lets its routes open. Only `/api/me` says it, so a sign-in
  /// reads it there before the user is signed in. False whenever [status] is
  /// not [AuthStatus.signedIn]. The server decides; this only shows.
  bool get isAdmin => _isAdmin;

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
      final me = await _api.getJson('/api/me');
      _user = AccountUser.fromJson(me);
      _isAdmin = me['is_admin'] == true;
      _set(AuthStatus.signedIn);
    } on UnauthorizedException {
      await _endSession();
    } catch (_) {
      _set(AuthStatus.unavailable);
    }
  }

  /// Exchanges a Google ID token for a session (`POST /api/auth/google`).
  Future<void> signInWithGoogle(String idToken) => _signIn(
        '/api/auth/google',
        {'id_token': idToken},
        refused: SignInFailure.rejected,
      );

  /// Exchanges an Apple ID token for a session (`POST /api/auth/apple`).
  /// [nonce] is the raw one whose hash Apple signed; [name] comes from the
  /// first authorisation only (sign-in plan D15); the server exchanges
  /// [authorizationCode] for the token it revokes at the account's deletion
  /// (IOS_APP_PLAN D5).
  Future<void> signInWithApple({
    required String idToken,
    required String nonce,
    String? name,
    String? authorizationCode,
  }) =>
      _signIn(
        '/api/auth/apple',
        {
          'id_token': idToken,
          'nonce': nonce,
          'name': ?name,
          'authorization_code': ?authorizationCode,
        },
        refused: SignInFailure.appleRejected,
        invalidIsRefused: true,
      );

  /// Apple's own flow failed: no token reached the server.
  void appleFlowFailed() => _fail(SignInFailure.appleFailed);

  /// Exchanges an email address and password for a session
  /// (`POST /api/auth/email/sign-in`). An address or password the server
  /// cannot even read (422) is refused like any other wrong pair.
  Future<void> signInWithEmail(String email, String password) => _signIn(
        '/api/auth/email/sign-in',
        {'email': email, 'password': password},
        refused: SignInFailure.wrongCredentials,
        invalidIsRefused: true,
      );

  /// Chooses a password with a mailed link (`POST /api/auth/email/complete`),
  /// creating the account or replacing its password.
  ///
  /// Returns why it failed, or null once this account's session is in place.
  /// A failure changes nothing, unlike a sign-in: the page opens signed in as
  /// well as signed out, and a used link must not end the session it finds.
  Future<EmailLinkFailure?> completeEmailLink({
    required String token,
    required String password,
    String? displayName,
  }) async {
    try {
      await _adopt(await _api.postJson('/api/auth/email/complete', {
        'token': token,
        'password': password,
        'display_name': ?displayName,
      }));
      return null;
    } on ApiException catch (e) {
      return switch (e.statusCode) {
        410 => EmailLinkFailure.expired,
        429 => EmailLinkFailure.tooManyAttempts,
        422 => EmailLinkFailure.notAccepted,
        _ => EmailLinkFailure.serverError,
      };
    } on ApiUnreachableException {
      return EmailLinkFailure.unreachable;
    } catch (_) {
      // An answer without the expected token or user.
      return EmailLinkFailure.serverError;
    }
  }

  Future<void> _signIn(
    String path,
    Map<String, dynamic> body, {
    required SignInFailure refused,
    bool invalidIsRefused = false,
  }) async {
    _set(AuthStatus.signingIn);
    try {
      await _adopt(await _api.postJson(path, body));
    } on UnauthorizedException {
      _fail(refused);
    } on ApiException catch (e) {
      _fail(switch (e.statusCode) {
        429 => SignInFailure.tooManyAttempts,
        422 when invalidIsRefused => refused,
        503 => SignInFailure.notConfigured,
        _ => SignInFailure.serverError,
      });
    } on ApiUnreachableException {
      _fail(SignInFailure.unreachable);
    } catch (_) {
      // An answer without the expected token or user.
      _fail(SignInFailure.serverError);
    }
  }

  /// Makes a sign-in's answer the current session.
  Future<void> _adopt(Map<String, dynamic> body) async {
    final token = body['token'] as String;
    final user = AccountUser.fromJson(body['user'] as Map<String, dynamic>);
    try {
      await _store.write(token);
    } catch (_) {
      // Signed in for this run only: the next start asks again.
    }
    _api.token = token;
    final isAdmin = await _readIsAdmin();
    // A 401 to that read ended this new session already.
    if (_api.token != token) return;
    _user = user;
    _isAdmin = isAdmin;
    _set(AuthStatus.signedIn);
  }

  /// `is_admin` from `/api/me`, which the sign-in answers do not carry. A
  /// failed read signs in all the same, as a user who is not the admin.
  Future<bool> _readIsAdmin() async {
    try {
      return (await _api.getJson('/api/me'))['is_admin'] == true;
    } catch (error) {
      // Logged so a missing admin entry is not read as a configuration error
      // (review R4-3). The typed errors' text is their type only.
      log('is_admin read failed after sign-in', name: 'auth', error: error);
      return false;
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
    if (status != AuthStatus.signedIn) {
      _user = null;
      _isAdmin = false;
    }
    if (status != AuthStatus.failed) _failure = null;
    notifyListeners();
  }
}
