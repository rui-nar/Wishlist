/// Whether this device has shown the introduction (NEEDS, Constraints,
/// "Introduction"): once per device, after sign-in.
library;

import 'package:shared_preferences/shared_preferences.dart';

/// Where the flag is stored in shared preferences.
const kIntroSeenKey = 'shushgift.intro_seen';

/// The device's "introduction seen" flag, read once from shared preferences
/// and kept in memory afterwards.
///
/// A store that cannot be read counts as seen: the introduction is a nicety,
/// and a device whose storage refuses it must never be sent to it again and
/// again.
class IntroSeen {
  bool? _seen;
  Future<bool>? _loading;

  /// The flag, or null until [load] has finished.
  bool? get value => _seen;

  /// Reads the stored flag; later calls return the same answer.
  Future<bool> load() => _loading ??= _read();

  Future<bool> _read() async {
    bool seen;
    try {
      final prefs = await SharedPreferences.getInstance();
      seen = prefs.getBool(kIntroSeenKey) ?? false;
    } catch (_) {
      // Refused, or not a bool: the same as seen.
      seen = true;
    }
    // A mark made while reading wins.
    return _seen ??= seen;
  }

  /// Seen from now on: in memory at once, so the next redirect already
  /// knows, then stored. A refused write only means it shows again on the
  /// next start.
  Future<void> markSeen() async {
    _seen = true;
    _loading = Future.value(true);
    try {
      await (await SharedPreferences.getInstance()).setBool(
        kIntroSeenKey,
        true,
      );
    } catch (_) {
      // Kept in memory for this run.
    }
  }
}
