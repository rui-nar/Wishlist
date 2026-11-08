import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import 'common.dart';
import 'lists_repository.dart';

/// The server's limit on an occasion's name (D4).
const kOccasionNameMaxLength = 100;

/// Creates an occasion of the list [listId], or renames the occasion
/// [occasionId] and changes its date. Either goes back to the list.
class OccasionFormScreen extends StatefulWidget {
  const OccasionFormScreen({super.key, required this.listId, this.occasionId});

  final String listId;

  /// The occasion to edit; null to create one.
  final String? occasionId;

  @override
  State<OccasionFormScreen> createState() => _OccasionFormScreenState();
}

class _OccasionFormScreenState extends State<OccasionFormScreen> {
  late final _repository = ListsRepository.of(context);
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  DateTime? _date;

  /// Editing: the occasion as it is, read from its list (owners only).
  Future<Occasion>? _occasion;
  bool _saving = false;

  bool get _creating => widget.occasionId == null;

  @override
  void initState() {
    super.initState();
    if (!_creating) _load();
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _load() {
    final occasion = _repository.list(widget.listId).then((list) {
      final found = list.occasions
          .where((occasion) => occasion.id == widget.occasionId)
          .firstOrNull;
      // Deleted meanwhile: the same as any occasion that is not there.
      if (found == null) throw const ApiException(404);
      return found;
    });
    setState(() {
      _occasion = occasion;
    });
    occasion.then((occasion) {
      _name.text = occasion.name;
      _date = occasion.date;
    }, onError: (_) {});
  }

  Future<void> _pickDate(FormFieldState<DateTime> field) async {
    final now = DateTime.now();
    final initial = _date ?? DateTime(now.year, now.month, now.day);
    // Wide enough for any occasion, and always around the current date.
    final first = DateTime(now.year - 5);
    final last = DateTime(now.year + 10, 12, 31);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: initial.isBefore(first) ? initial : first,
      lastDate: initial.isAfter(last) ? initial : last,
    );
    if (picked == null || !mounted) return;
    setState(() => _date = picked);
    field.didChange(picked);
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final name = _name.text.trim();
    setState(() => _saving = true);
    try {
      if (_creating) {
        await _repository.createOccasion(
          widget.listId,
          name: name,
          date: _date!,
        );
      } else {
        await _repository.updateOccasion(
          widget.occasionId!,
          name: name,
          date: _date!,
        );
      }
      if (mounted) context.pop();
    } catch (error) {
      messenger.showSnackBar(SnackBar(
        content: Text(
          isNotFound(error)
              ? (_creating ? l10n.listNotFound : l10n.occasionNotFound)
              : l10n.saveFailed,
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
        title: Text(_creating ? l10n.newOccasion : l10n.editOccasionTitle),
      ),
      body: PageFrame(
        child: SafeArea(
          child: _creating
              ? _buildForm(context)
              : FutureBuilder<Occasion>(
                  future: _occasion,
                  builder: (context, snapshot) {
                    if (snapshot.hasError) {
                      return LoadFailure(
                        error: snapshot.error,
                        onRetry: _load,
                        maxWidth: ContentWidths.form,
                        notFound: l10n.occasionNotFound,
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
                    controller: _name,
                    autofocus: _creating,
                    decoration: InputDecoration(
                      labelText: l10n.occasionNameLabel,
                      hintText: l10n.occasionNameHint,
                    ),
                    inputFormatters: [
                      LengthLimitingTextInputFormatter(kOccasionNameMaxLength),
                    ],
                    validator: (value) => (value ?? '').trim().isEmpty
                        ? l10n.occasionNameRequired
                        : null,
                  ),
                  const SizedBox(height: Spacing.s16),
                  FormField<DateTime>(
                    initialValue: _date,
                    validator: (_) =>
                        _date == null ? l10n.occasionDateRequired : null,
                    builder: (field) => InkWell(
                      onTap: () => _pickDate(field),
                      borderRadius:
                          const BorderRadius.all(Radius.circular(Radii.md)),
                      child: InputDecorator(
                        decoration: InputDecoration(
                          labelText: l10n.occasionDateLabel,
                          errorText: field.errorText,
                          suffixIcon: const Icon(Icons.calendar_today_outlined),
                        ),
                        isEmpty: _date == null,
                        child: Text(
                          _date == null
                              ? ''
                              : formatOccasionDate(context, _date!),
                          style: theme.textTheme.bodyLarge,
                        ),
                      ),
                    ),
                  ),
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
