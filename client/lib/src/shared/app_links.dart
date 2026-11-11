/// Links that open the app on Android and iOS (Shush Gift plan D7).
///
/// The platform hands the app the whole link, `https://<host>/join#<token>`:
/// at start as the initial route on Android, and as pushed route information
/// while the app runs, and at start on iOS. Each goes through
/// [AppLinkReceiver], which does what the web does with its address: the
/// tokens in the fragment are kept out of the router (PendingJoin, the mailed
/// link's token), and the router gets the location a browser would show.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

/// The location inside the app of [link]: its path and query, without the
/// scheme, the host or the fragment, as the web's router sees an address.
String appLocationOf(Uri link) => Uri(
      path: link.path.isEmpty ? '/' : link.path,
      query: link.hasQuery ? link.query : null,
    ).toString();

/// Takes every link the platform pushes while the app runs, before the
/// router's own listener: [onLink] keeps its tokens and opens its location.
///
/// Registered ahead of the router, it answers the push as handled, so the
/// router never sees a link whole, and iOS does not give a handled link back
/// to Safari.
class AppLinkReceiver with WidgetsBindingObserver {
  AppLinkReceiver(this.onLink);

  final void Function(Uri link) onLink;

  @override
  Future<bool> didPushRouteInformation(RouteInformation routeInformation) {
    onLink(routeInformation.uri);
    return SynchronousFuture<bool>(true);
  }
}
