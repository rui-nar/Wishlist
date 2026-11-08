/// Indicative prices: stored as given, shown in the viewer's locale
/// (LISTS_GIFTS_SHARING_PLAN D13).
library;

import 'package:intl/intl.dart';

/// [amount] (the server's decimal string) in [currency], formatted for
/// [locale]: `€149.00` in English, `149,00 €` in French. No conversion.
String formatPrice(String amount, String currency, String locale) =>
    NumberFormat.simpleCurrency(locale: locale, name: currency)
        .format(num.parse(amount));

final _amount = RegExp(r'^\d{1,10}([.,]\d{1,2})?$');

/// The amount typed in the gift form as the decimal string the server takes
/// (`149,90` → `149.90`), or null when it is not one: at most 10 integer
/// digits and 2 decimals, not negative (D3). Either decimal separator is
/// accepted, whatever the locale.
String? parseAmount(String text) {
  final trimmed = text.trim();
  if (!_amount.hasMatch(trimmed)) return null;
  return trimmed.replaceAll(',', '.');
}
