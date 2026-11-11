/// The operating system the app runs on, not the platform a test or a
/// widget pretends to be: only on a real Android is Play's billing there.
library;

import 'dart:io' show Platform;

bool get runsOnAndroid => Platform.isAndroid;
