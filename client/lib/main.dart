import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'src/config.dart';
import 'src/version_screen.dart';

void main() {
  runApp(WishlistApp(httpClient: http.Client()));
}

class WishlistApp extends StatelessWidget {
  const WishlistApp({
    super.key,
    required this.httpClient,
    this.apiBaseUrl = kApiBaseUrl,
    this.appVersion = kAppVersion,
  });

  // Injectable so tests can supply a MockClient (package:http/testing.dart).
  final http.Client httpClient;
  final String apiBaseUrl;
  final String appVersion;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Wishlist',
      home: VersionScreen(
        httpClient: httpClient,
        apiBaseUrl: apiBaseUrl,
        appVersion: appVersion,
      ),
    );
  }
}
