import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../auth/preferences_repository.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../error_line.dart';
import '../lists/common.dart';

/// The path of an email's unsubscribe link: `<origin>/unsubscribe#<token>`.
const kUnsubscribePath = '/unsubscribe';

/// The token an unsubscribe link carries in [url]: the fragment of
/// `/unsubscribe#<token>`, or null for any other address.
String? unsubscribeTokenFrom(Uri url) {
  if (url.path != kUnsubscribePath || url.fragment.isEmpty) return null;
  return url.fragment;
}

enum _Stage { confirm, sending, done, invalid, failed }

/// `/unsubscribe`: one button that stops email notifications for the account
/// the link was made for (COMMENTS_NOTIFICATIONS_PLAN D18, D20).
///
/// Public: an email's link works signed out. Nothing is sent until the button
/// is pressed, since mail security scanners open links. A token the server
/// refuses, or none at all, says the link is not valid.
class UnsubscribeScreen extends StatefulWidget {
  const UnsubscribeScreen({super.key, required this.token});

  /// From the link's fragment; null when the address has none, as after a
  /// reload (the router rewrites the address without it).
  final String? token;

  @override
  State<UnsubscribeScreen> createState() => _UnsubscribeScreenState();
}

class _UnsubscribeScreenState extends State<UnsubscribeScreen> {
  late final _repository = PreferencesRepository.of(context);
  late _Stage _stage =
      widget.token == null ? _Stage.invalid : _Stage.confirm;
  Object? _error;

  Future<void> _unsubscribe() async {
    setState(() => _stage = _Stage.sending);
    try {
      await _repository.unsubscribe(widget.token!);
      if (mounted) setState(() => _stage = _Stage.done);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        if (error is ApiException &&
            (error.statusCode == 404 || error.statusCode == 422)) {
          _stage = _Stage.invalid;
        } else {
          _error = error;
          _stage = _Stage.failed;
        }
      });
    }
  }

  /// In this page's place, so going back does not come to a page that has
  /// lost its token. Signed out, the guard asks to sign in first.
  void _openAccount() =>
      Router.neglect(context, () => context.go('/account'));

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final toAccount = OutlinedButton(
      onPressed: _openAccount,
      child: Text(l10n.unsubscribeOpenAccount),
    );
    return Scaffold(
      appBar: AppBar(title: Text(l10n.unsubscribeTitle)),
      body: PageFrame(
        child: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: SingleChildScrollView(
              padding: PageFrame.paddingOf(context, ContentWidths.reading),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: switch (_stage) {
                      _Stage.confirm || _Stage.sending => [
                          Text(
                            l10n.unsubscribeBody,
                            style: theme.textTheme.bodyLarge,
                          ),
                          const SizedBox(height: Spacing.s24),
                          FilledButton(
                            onPressed:
                                _stage == _Stage.sending ? null : _unsubscribe,
                            child: Text(l10n.unsubscribeAction),
                          ),
                        ],
                      _Stage.done => [
                          Text(
                            l10n.unsubscribeDone,
                            style: theme.textTheme.bodyLarge,
                          ),
                          const SizedBox(height: Spacing.s24),
                          toAccount,
                        ],
                      _Stage.invalid => [
                          ErrorLine(l10n.unsubscribeInvalid),
                          const SizedBox(height: Spacing.s16),
                          toAccount,
                        ],
                      _Stage.failed => [
                          ErrorLine(failureMessage(l10n, _error)),
                          const SizedBox(height: Spacing.s16),
                          OutlinedButton(
                            onPressed: _unsubscribe,
                            child: Text(l10n.retry),
                          ),
                        ],
                    },
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
