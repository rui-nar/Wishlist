import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Loads the bundled fonts and the Material icon font before any test runs, so
/// goldens show real text and real icons, not the test font's boxes
/// (DESIGN_SYSTEM_PLAN D10).
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  TestWidgetsFlutterBinding.ensureInitialized();

  await _load('Inter', [
    'assets/fonts/inter/Inter-Regular.ttf',
    'assets/fonts/inter/Inter-Medium.ttf',
    'assets/fonts/inter/Inter-SemiBold.ttf',
    'assets/fonts/inter/Inter-Bold.ttf',
  ]);
  await _load('Space Grotesk', [
    'assets/fonts/space_grotesk/SpaceGrotesk-Medium.ttf',
    'assets/fonts/space_grotesk/SpaceGrotesk-Bold.ttf',
  ]);

  // Named by sign_in_with_apple's button. Absent outside Apple's platforms,
  // where the platform's default font is used; Inter stands in for it here.
  await _load('.SF Pro Text', ['assets/fonts/inter/Inter-Regular.ttf']);

  // The SDK's icon font; `flutter test` sets FLUTTER_ROOT.
  final sdk = Platform.environment['FLUTTER_ROOT'];
  if (sdk == null) {
    throw StateError('FLUTTER_ROOT is not set: cannot find the icon font.');
  }
  final icons = File(
    '$sdk/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
  ).readAsBytesSync();
  await (FontLoader(
    'MaterialIcons',
  )..addFont(Future.value(ByteData.sublistView(icons)))).load();

  await testMain();
}

Future<void> _load(String family, List<String> assets) {
  final loader = FontLoader(family);
  for (final asset in assets) {
    loader.addFont(rootBundle.load(asset));
  }
  return loader.load();
}
