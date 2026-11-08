import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'src/config.dart';
import 'src/design/theme.dart';
import 'src/version_screen.dart';

void main() {
  LicenseRegistry.addLicense(_fontLicenses);
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
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: ThemeMode.system,
      home: VersionScreen(
        httpClient: httpClient,
        apiBaseUrl: apiBaseUrl,
        appVersion: appVersion,
      ),
    );
  }
}

/// The SIL Open Font License texts of the bundled fonts, shown on the
/// licences page.
Stream<LicenseEntry> _fontLicenses() async* {
  for (final (family, path) in [
    ('Inter', 'assets/fonts/inter/OFL.txt'),
    ('Space Grotesk', 'assets/fonts/space_grotesk/OFL.txt'),
  ]) {
    yield LicenseEntryWithLineBreaks(
      [family],
      await rootBundle.loadString(path),
    );
  }
}
