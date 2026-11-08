import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:wishlist/src/auth/token_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final stores = {
    'local storage (web)': () {
      SharedPreferences.setMockInitialValues({});
      return PreferencesTokenStore();
    },
    'secure storage (Android, iOS)': () {
      FlutterSecureStorage.setMockInitialValues({});
      return SecureTokenStore();
    },
  };

  for (final MapEntry(key: name, value: create) in stores.entries) {
    test('$name keeps the token until cleared', () async {
      final store = create();
      expect(await store.read(), isNull);

      await store.write('session-token');
      expect(await store.read(), 'session-token');

      await store.clear();
      expect(await store.read(), isNull);
    });
  }
}
