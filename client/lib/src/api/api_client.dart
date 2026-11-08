/// The HTTP layer every server call goes through (ACCOUNTS_PLAN D10).
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// The server refused the session: it is missing, expired or revoked (401).
class UnauthorizedException implements Exception {
  const UnauthorizedException();

  @override
  String toString() => 'UnauthorizedException';
}

/// The server answered with a status other than 2xx and 401.
class ApiException implements Exception {
  const ApiException(this.statusCode, [this.body]);

  final int statusCode;

  /// The answer's JSON object, when it is one, for the few errors whose body
  /// the API documents (a 409 on join names the list to open instead). Read
  /// for those fields only; never shown to the user.
  final Map<String, dynamic>? body;

  @override
  String toString() => 'ApiException: HTTP $statusCode';
}

/// The server could not be reached, did not answer in time, or answered
/// something that is not the expected JSON.
class ApiUnreachableException implements Exception {
  const ApiUnreachableException();

  @override
  String toString() => 'ApiUnreachableException';
}

const _kTimeout = Duration(seconds: 10);

/// Calls `<baseUrl>/api/...` with the session's bearer token, if any.
///
/// Errors are typed, never the server's text: [UnauthorizedException] on 401,
/// [ApiException] on any other error status, [ApiUnreachableException] when
/// there is no usable answer.
class ApiClient {
  ApiClient(this.httpClient, {required this.baseUrl});

  final http.Client httpClient;

  /// The server's origin; empty means the web client's own origin.
  final String baseUrl;

  /// The session token, sent as `Authorization: Bearer <token>` when set.
  String? token;

  /// Called with the token a request carried when it is answered 401: the
  /// session expired or was revoked, so the user is signed out (D10). Not
  /// called for requests made without a token, such as signing in.
  void Function(String token)? onUnauthorized;

  Future<Map<String, dynamic>> getJson(String path) async =>
      _decode<Map<String, dynamic>>(await _send('GET', path));

  /// A GET whose answer is a JSON array.
  Future<List<dynamic>> getJsonList(String path) async =>
      _decode<List<dynamic>>(await _send('GET', path));

  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body,
  ) async =>
      _decode<Map<String, dynamic>>(await _send('POST', path, body: body));

  Future<Map<String, dynamic>> patchJson(
    String path,
    Map<String, dynamic> body,
  ) async =>
      _decode<Map<String, dynamic>>(await _send('PATCH', path, body: body));

  /// A POST whose answer has no body (204).
  Future<void> post(String path) => _send('POST', path);

  /// A DELETE whose answer has no body (204).
  Future<void> delete(String path) => _send('DELETE', path);

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final sentToken = token;
    final request = http.Request(method, Uri.parse('$baseUrl$path'));
    if (sentToken != null) {
      request.headers['Authorization'] = 'Bearer $sentToken';
    }
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(
        await httpClient.send(request).timeout(_kTimeout),
      ).timeout(_kTimeout);
    } on http.ClientException {
      throw const ApiUnreachableException();
    } on TimeoutException {
      throw const ApiUnreachableException();
    }
    if (response.statusCode == 401) {
      if (sentToken != null) onUnauthorized?.call(sentToken);
      throw const UnauthorizedException();
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, _errorBody(response));
    }
    return response;
  }

  /// An error answer's JSON object, or null when it is not one.
  static Map<String, dynamic>? _errorBody(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      return body is Map<String, dynamic> ? body : null;
    } catch (_) {
      return null;
    }
  }

  /// The body as [T]: a JSON object or a JSON array.
  T _decode<T>(http.Response response) {
    try {
      return jsonDecode(response.body) as T;
    } catch (_) {
      throw const ApiUnreachableException();
    }
  }
}
