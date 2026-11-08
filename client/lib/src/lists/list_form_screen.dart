import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import 'common.dart';
import 'lists_repository.dart';

/// The server's limits on a list's title and recipient name (D1).
const kListTitleMaxLength = 100;
const kRecipientNameMaxLength = 100;

/// Creates a list, or renames the list [listId]. Creating asks who the list
/// is for, once (D2); renaming changes the title and, for a list for someone
/// else, their name. Creating opens the new list, in place of the form;
/// renaming goes back.
class ListFormScreen extends StatefulWidget {
  const ListFormScreen({super.key, this.listId});

  /// The list to rename; null to create one.
  final String? listId;

  @override
  State<ListFormScreen> createState() => _ListFormScreenState();
}

class _ListFormScreenState extends State<ListFormScreen> {
  late final _repository = ListsRepository.of(context);
  final _form = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _recipientName = TextEditingController();
  RecipientKind _kind = RecipientKind.self;

  /// Renaming: the list as it is, read first.
  Future<ListDetail>? _list;
  bool _saving = false;

  bool get _creating => widget.listId == null;

  @override
  void initState() {
    super.initState();
    if (!_creating) _load();
  }

  @override
  void dispose() {
    _title.dispose();
    _recipientName.dispose();
    super.dispose();
  }

  void _load() {
    final list = _repository.list(widget.listId!);
    setState(() {
      _list = list;
    });
    list.then((list) {
      _title.text = list.title;
      _kind = list.recipientKind;
      _recipientName.text = list.recipientName ?? '';
    }, onError: (_) {});
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final title = _title.text.trim();
    final name =
        _kind == RecipientKind.other ? _recipientName.text.trim() : null;
    setState(() => _saving = true);
    try {
      if (_creating) {
        final id = await _repository.createList(
          title: title,
          recipientKind: _kind,
          recipientName: name,
        );
        if (mounted) context.go('/lists/$id');
      } else {
        await _repository.updateList(
          widget.listId!,
          title: title,
          recipientName: name,
        );
        if (mounted) context.pop();
      }
    } catch (error) {
      messenger.showSnackBar(SnackBar(
        content: Text(
          isNotFound(error) ? l10n.listNotFound : l10n.saveFailed,
        ),
      ));
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(_creating ? l10n.newList : l10n.renameListTitle),
      ),
      body: PageFrame(
        child: SafeArea(
          child: _creating
              ? _buildForm(context)
              : FutureBuilder<ListDetail>(
                  future: _list,
                  builder: (context, snapshot) {
                    if (snapshot.hasError) {
                      return LoadFailure(
                        error: snapshot.error,
                        onRetry: _load,
                        maxWidth: ContentWidths.form,
                        notFound: l10n.listNotFound,
                      );
                    }
                    if (!snapshot.hasData) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    return _buildForm(context);
                  },
                ),
        ),
      ),
    );
  }

  Widget _buildForm(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Form(
      key: _form,
      child: ListView(
        padding: PageFrame.paddingOf(context, ContentWidths.form),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextFormField(
                    controller: _title,
                    autofocus: _creating,
                    decoration: InputDecoration(labelText: l10n.listTitleLabel),
                    inputFormatters: [
                      LengthLimitingTextInputFormatter(kListTitleMaxLength),
                    ],
                    textInputAction: TextInputAction.next,
                    validator: (value) => (value ?? '').trim().isEmpty
                        ? l10n.listTitleRequired
                        : null,
                  ),
                  if (_creating) ...[
                    const SizedBox(height: Spacing.s24),
                    Text(
                      l10n.listRecipientChoice,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: Spacing.s12),
                    SegmentedButton<RecipientKind>(
                      segments: [
                        ButtonSegment(
                          value: RecipientKind.self,
                          label: Text(l10n.listForMe),
                        ),
                        ButtonSegment(
                          value: RecipientKind.other,
                          label: Text(l10n.listForSomeoneElse),
                        ),
                      ],
                      selected: {_kind},
                      onSelectionChanged: (selected) =>
                          setState(() => _kind = selected.single),
                    ),
                    const SizedBox(height: Spacing.s8),
                    Text(
                      l10n.listRecipientKindFixed,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                  if (_kind == RecipientKind.other) ...[
                    const SizedBox(height: Spacing.s16),
                    TextFormField(
                      controller: _recipientName,
                      decoration: InputDecoration(
                        labelText: l10n.recipientNameLabel,
                      ),
                      inputFormatters: [
                        LengthLimitingTextInputFormatter(
                          kRecipientNameMaxLength,
                        ),
                      ],
                      validator: (value) => (value ?? '').trim().isEmpty
                          ? l10n.recipientNameRequired
                          : null,
                    ),
                  ],
                  const SizedBox(height: Spacing.s24),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(_creating ? l10n.create : l10n.save),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
