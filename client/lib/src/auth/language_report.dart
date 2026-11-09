import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'auth_controller.dart';
import 'preferences_repository.dart';

/// Tells the server the language the app displays, so that emails are written
/// in it (COMMENTS_NOTIFICATIONS_PLAN D17, D20).
///
/// Under `MaterialApp`, where the displayed locale is known. Sent when someone
/// is signed in and the language differs from the last one reported for them
/// in this run; nothing is sent signed out. A failure is ignored, and the next
/// start reports again.
class LanguageReport extends StatefulWidget {
  const LanguageReport({super.key, required this.child});

  final Widget child;

  @override
  State<LanguageReport> createState() => _LanguageReportState();
}

class _LanguageReportState extends State<LanguageReport> {
  /// User id → the language last sent for them.
  final _reported = <String, String>{};

  @override
  Widget build(BuildContext context) {
    final userId = context.select((AuthController auth) => auth.user?.id);
    final language = Localizations.localeOf(context).languageCode;
    if (userId != null && _reported[userId] != language) {
      _reported[userId] = language;
      // After the frame: the repository reads a provider, not to be done
      // while building.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_report(language));
      });
    }
    return widget.child;
  }

  Future<void> _report(String language) async {
    try {
      await PreferencesRepository.of(context).setLanguage(language);
    } catch (_) {
      // Emails stay in the last language the server knows.
    }
  }
}
