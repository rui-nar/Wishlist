/// Gift links open outside the app (LISTS_GIFTS_SHARING_PLAN D12).
library;

import 'package:url_launcher/url_launcher.dart';

final _space = RegExp(r'\s');

/// [link] when it is an absolute `http` or `https` URL with a host, as the
/// server requires; null otherwise.
Uri? webLink(String link) {
  if (link.isEmpty || link.contains(_space)) return null;
  final uri = Uri.tryParse(link);
  if (uri == null || !(uri.isScheme('http') || uri.isScheme('https'))) {
    return null;
  }
  return uri.host.isEmpty ? null : uri;
}

/// Opens [link] in the external browser, checking it again first rather than
/// relying on the server's check. False when it is not such a link or could
/// not be opened.
Future<bool> openGiftLink(String link) async {
  final uri = webLink(link);
  if (uri == null) return false;
  try {
    return await launchUrl(uri, mode: LaunchMode.externalApplication);
  } catch (_) {
    return false;
  }
}
