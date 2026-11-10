/// What the billing tests share.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

/// url_launcher's platform side, recording every option: which tab a page
/// opens in is part of the checkout (PREMIUM_PLAN D18).
class RecordingUrlLauncher extends Fake
    with MockPlatformInterfaceMixin
    implements UrlLauncherPlatform {
  final launched = <({String url, LaunchOptions options})>[];

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    launched.add((url: url, options: options));
    return true;
  }
}

/// Installs a fresh [RecordingUrlLauncher] for the test.
RecordingUrlLauncher installRecordingUrlLauncher() {
  final previous = UrlLauncherPlatform.instance;
  final fake = RecordingUrlLauncher();
  UrlLauncherPlatform.instance = fake;
  addTearDown(() => UrlLauncherPlatform.instance = previous);
  return fake;
}
