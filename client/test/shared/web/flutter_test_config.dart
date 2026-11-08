import 'dart:async';

/// The browser tests here draw nothing, so they skip the fonts that
/// test/flutter_test_config.dart loads from the disk, which a browser cannot
/// read; and they start no binding, so the test can set the page's URL
/// strategy the way main() does.
Future<void> testExecutable(FutureOr<void> Function() testMain) async =>
    testMain();
