import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shushgift/src/billing/google_store.dart';
import 'package:shushgift/src/billing/store.dart';

import 'support.dart';

// What the Android app keeps of purchases the server has dealt with, which
// Play goes on listing as unacknowledged until Google refunds the refused
// ones (Android release plan D6): they are not posted again at each start.

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  List<String?> tokens(List<StorePurchase> purchases) =>
      [for (final purchase in purchases) purchase.verificationData];

  test('nothing set aside: every unacknowledged purchase is posted', () async {
    final waiting = [googlePurchase(id: 'GPA.1'), googlePurchase(id: 'GPA.2')];

    expect(
      tokens(await DealtWithPurchases().leaveOut(waiting)),
      ['token-GPA.1', 'token-GPA.2'],
    );
  });

  test('a refused purchase is left out, even after a restart', () async {
    await DealtWithPurchases().add('token-GPA.1');
    final waiting = [googlePurchase(id: 'GPA.1'), googlePurchase(id: 'GPA.2')];

    expect(
      tokens(await DealtWithPurchases().leaveOut(waiting)),
      ['token-GPA.2'],
    );
  });

  test('forgotten once Play no longer lists it', () async {
    final dealtWith = DealtWithPurchases();
    await dealtWith.add('token-GPA.1');
    await dealtWith.add('token-GPA.2');

    await dealtWith.leaveOut([googlePurchase(id: 'GPA.2')]);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getStringList(DealtWithPurchases.key), ['token-GPA.2']);
  });

  test('added once', () async {
    final dealtWith = DealtWithPurchases();
    await dealtWith.add('token-GPA.1');
    await dealtWith.add('token-GPA.1');

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getStringList(DealtWithPurchases.key), ['token-GPA.1']);
  });
}
