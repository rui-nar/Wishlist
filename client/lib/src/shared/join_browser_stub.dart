/// Android and iOS: no address bar, and no link opens the app yet.
library;

import 'pending_join.dart';

JoinBrowser platformJoinBrowser() => MemoryJoinBrowser();
