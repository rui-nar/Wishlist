/// Android and iOS: no address bar, and a link reaches the running app
/// (app_links.dart) instead of loading it again.
library;

import 'pending_join.dart';

JoinBrowser platformJoinBrowser() => MemoryJoinBrowser();
