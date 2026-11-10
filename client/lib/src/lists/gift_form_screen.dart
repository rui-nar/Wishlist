import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../shared/gift_sheet.dart';
import '../shared/shared_repository.dart';
import 'common.dart';
import 'currencies.dart';
import 'gift_image_section.dart';
import 'gift_links.dart';
import 'lists_repository.dart';
import 'price.dart';

/// The server's limits on a gift (D3).
const kGiftTitleMaxLength = 200;
const kGiftDescriptionMaxLength = 2000;
const kMaxLinks = 10;
const kLinkMaxLength = 2048;

/// A gift being edited: what the form starts from.
typedef _Editing = ({GiftDraft fields, GiftImage? image});

/// Adds a gift to the list [listId], or edits its gift [giftId]: image,
/// title, description, shop links and an indicative price. Editing also
/// marks the gift received, or deletes it after confirmation. Goes back to
/// the list once saved, received or deleted.
///
/// [GiftFormScreen.hidden] does the same for a giver's hidden gift of an
/// occasion, through its routes, with nothing to mark received
/// (HIDDEN_GIFTS_PLAN D14).
class GiftFormScreen extends StatefulWidget {
  const GiftFormScreen({
    super.key,
    required String this.listId,
    this.giftId,
  })  : occasionId = null,
        occasionLocation = null;

  const GiftFormScreen.hidden({
    super.key,
    required String this.occasionId,
    required String this.occasionLocation,
    this.giftId,
  }) : listId = null;

  /// The list of a list gift; null for a hidden gift.
  final String? listId;

  /// The occasion of a hidden gift; null for a list gift.
  final String? occasionId;

  /// Where to go back to when a hidden gift is gone: the occasion's page.
  final String? occasionLocation;

  /// The gift to edit; null to add one.
  final String? giftId;

  @override
  State<GiftFormScreen> createState() => _GiftFormScreenState();
}

class _GiftFormScreenState extends State<GiftFormScreen> {
  late final _repository = ListsRepository.of(context);
  late final _shared = SharedRepository.of(context);
  final _form = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _amount = TextEditingController();
  final _currency = TextEditingController(text: kDefaultCurrency);
  final _links = <TextEditingController>[];

  /// Editing: the gift as it is, read first.
  Future<_Editing>? _gift;
  bool _busy = false;

  /// What saving does to the image, and whether one is being sent.
  ImageChange _imageChange = const KeepImage();
  bool _imageBusy = false;

  bool get _adding => widget.giftId == null;
  bool get _hidden => widget.occasionId != null;

  @override
  void initState() {
    super.initState();
    if (_adding) {
      _links.add(TextEditingController());
    } else {
      _load();
    }
  }

  @override
  void dispose() {
    for (final controller in [
      _title,
      _description,
      _amount,
      _currency,
      ..._links,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  /// There is no endpoint for one gift: it is read with its list, and a gift
  /// missing from it is gone (404).
  Future<_Editing> _readListGift() async {
    final list = await _repository.list(widget.listId!);
    for (final gift in list.gifts) {
      if (gift.id == widget.giftId) return (fields: gift, image: gift.image);
    }
    throw const ApiException(404);
  }

  /// A hidden gift is read with its occasion's. The occasion is asked first:
  /// a recipient, on a location they typed, never reaches the hidden gifts
  /// (HIDDEN_GIFTS_PLAN D14). A gift that is not the user's is theirs to
  /// edit no more than a missing one (D8).
  Future<_Editing> _readHiddenGift() async {
    final occasionId = widget.occasionId!;
    final view = await _shared.occasion(occasionId);
    if (view is OwnedOccasion && !view.givesHere) {
      throw const ApiException(404);
    }
    for (final gift in await _shared.hiddenGifts(occasionId)) {
      if (gift.id == widget.giftId && gift.mine) {
        return (fields: gift, image: gift.image);
      }
    }
    throw const ApiException(404);
  }

  void _load() {
    final gift = _hidden ? _readHiddenGift() : _readListGift();
    setState(() {
      _gift = gift;
    });
    gift.then((gift) {
      final fields = gift.fields;
      _title.text = fields.title;
      _description.text = fields.description;
      for (final controller in _links) {
        controller.dispose();
      }
      _links
        ..clear()
        ..addAll([
          for (final link in fields.links) TextEditingController(text: link),
        ]);
      if (_links.isEmpty) _links.add(TextEditingController());
      _amount.text = fields.priceAmount ?? '';
      _currency.text = fields.priceCurrency ?? kDefaultCurrency;
    }, onError: (_) {});
  }

  void _addLink() => setState(() => _links.add(TextEditingController()));

  void _removeLink(int index) {
    final removed = _links.removeAt(index);
    setState(() {});
    WidgetsBinding.instance.addPostFrameCallback((_) => removed.dispose());
  }

  /// What the form says. A price is sent only with an amount: a currency
  /// alone is not a price, so an emptied amount removes the price.
  GiftDraft _draft() {
    final amount = parseAmount(_amount.text);
    return GiftDraft(
      title: _title.text.trim(),
      description: _description.text.trim(),
      links: [
        for (final link in _links)
          if (link.text.trim().isNotEmpty) link.text.trim(),
      ],
      priceAmount: amount,
      priceCurrency: amount == null ? null : _currency.text,
      imageChange: _imageChange,
    );
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      final occasionId = widget.occasionId;
      final giftId = widget.giftId;
      if (occasionId != null) {
        if (giftId == null) {
          await _shared.addHiddenGift(occasionId, _draft());
        } else {
          await _shared.updateHiddenGift(occasionId, giftId, _draft());
        }
      } else if (giftId == null) {
        await _repository.addGift(widget.listId!, _draft());
      } else {
        await _repository.updateGift(giftId, _draft());
      }
      if (mounted) context.pop();
    } on HiddenGiftRefused catch (refused) {
      _sayRefusedAndLeave(messenger, l10n, refused);
    } catch (error) {
      messenger.showSnackBar(SnackBar(
        content: Text(
          isNotFound(error)
              ? _goneMessage(l10n)
              : imageRefusal(l10n, error) ?? l10n.saveFailed,
        ),
      ));
      if (mounted) setState(() => _busy = false);
    }
  }

  String _goneMessage(AppLocalizations l10n) => !_adding
      ? l10n.giftNotFound
      : _hidden
          ? l10n.occasionNoLongerShared
          : l10n.listNotFound;

  /// The hidden gift can no longer be changed (bought, the occasion passed,
  /// HIDDEN_GIFTS_PLAN D8): says so and goes back to the occasion, which
  /// shows it as it now is. Staying would only be refused again.
  void _sayRefusedAndLeave(
    ScaffoldMessengerState messenger,
    AppLocalizations l10n,
    HiddenGiftRefused refused,
  ) {
    messenger.showSnackBar(SnackBar(
      content: Text(hiddenGiftRefusalMessage(l10n, refused.refusal)),
    ));
    if (mounted) context.pop();
  }

  /// Offered on every gift alike, so it says nothing about which ones were
  /// bought (HIDDEN_GIFTS_PLAN D5). Reversible from the list: no
  /// confirmation.
  Future<void> _markReceived() async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      await _repository.markReceived(widget.giftId!);
      if (mounted) context.pop();
    } catch (error) {
      messenger.showSnackBar(SnackBar(
        content: Text(isNotFound(error) ? l10n.giftNotFound : l10n.saveFailed),
      ));
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await confirmDelete(
      context,
      title: l10n.deleteGiftTitle,
      body: _hidden ? l10n.hiddenGiftDeleteBody : l10n.deleteGiftBody,
    );
    if (!confirmed || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      final occasionId = widget.occasionId;
      if (occasionId != null) {
        await _shared.deleteHiddenGift(occasionId, widget.giftId!);
      } else {
        await _repository.deleteGift(widget.giftId!);
      }
    } on HiddenGiftRefused catch (refused) {
      _sayRefusedAndLeave(messenger, l10n, refused);
      return;
    } catch (error) {
      // Already gone is what the user asked for.
      if (!isNotFound(error)) {
        messenger.showSnackBar(SnackBar(content: Text(l10n.deleteFailed)));
        if (mounted) setState(() => _busy = false);
        return;
      }
    }
    if (mounted) context.pop();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final addLabel = _hidden ? l10n.addHiddenGift : l10n.addGift;
    return Scaffold(
      appBar: AppBar(title: Text(_adding ? addLabel : l10n.editGift)),
      body: PageFrame(
        child: SafeArea(
          child: _adding
              ? _buildForm(context, null, addLabel)
              : FutureBuilder<_Editing>(
                  future: _gift,
                  builder: (context, snapshot) {
                    if (snapshot.hasError) {
                      return LoadFailure(
                        error: snapshot.error,
                        onRetry: _load,
                        maxWidth: ContentWidths.form,
                        notFound: l10n.giftNotFound,
                        backLocation: widget.occasionLocation ?? '/',
                        backLabel: _hidden ? l10n.backToOccasion : null,
                      );
                    }
                    if (!snapshot.hasData) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    return _buildForm(
                      context,
                      snapshot.data!.image,
                      addLabel,
                    );
                  },
                ),
        ),
      ),
    );
  }

  /// [image] is the gift's as it is, when editing; [addLabel] what adding is
  /// called.
  Widget _buildForm(
    BuildContext context,
    GiftImage? image,
    String addLabel,
  ) {
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
                  GiftImageSection(
                    initial: image,
                    enabled: !_busy,
                    onChanged: (change) => _imageChange = change,
                    onBusyChanged: (busy) => setState(() => _imageBusy = busy),
                  ),
                  const SizedBox(height: Spacing.s24),
                  TextFormField(
                    controller: _title,
                    autofocus: _adding,
                    decoration: InputDecoration(labelText: l10n.giftTitleLabel),
                    inputFormatters: [
                      LengthLimitingTextInputFormatter(kGiftTitleMaxLength),
                    ],
                    textInputAction: TextInputAction.next,
                    validator: (value) => (value ?? '').trim().isEmpty
                        ? l10n.giftTitleRequired
                        : null,
                  ),
                  const SizedBox(height: Spacing.s16),
                  TextFormField(
                    controller: _description,
                    decoration: InputDecoration(
                      labelText: l10n.giftDescriptionLabel,
                    ),
                    inputFormatters: [
                      LengthLimitingTextInputFormatter(
                        kGiftDescriptionMaxLength,
                      ),
                    ],
                    minLines: 2,
                    maxLines: 6,
                  ),
                  const SizedBox(height: Spacing.s16),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: TextFormField(
                          controller: _amount,
                          decoration: InputDecoration(
                            labelText: l10n.priceLabel,
                          ),
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          validator: (value) {
                            final text = (value ?? '').trim();
                            return text.isEmpty || parseAmount(text) != null
                                ? null
                                : l10n.priceInvalid;
                          },
                        ),
                      ),
                      const SizedBox(width: Spacing.s12),
                      SizedBox(
                        width: _currencyWidth,
                        child: TextFormField(
                          controller: _currency,
                          decoration: InputDecoration(
                            labelText: l10n.currencyLabel,
                            errorMaxLines: 3,
                          ),
                          textCapitalization: TextCapitalization.characters,
                          inputFormatters: [
                            FilteringTextInputFormatter.allow(
                              RegExp('[A-Za-z]'),
                            ),
                            LengthLimitingTextInputFormatter(3),
                            _upperCase,
                          ],
                          validator: (value) {
                            // Without an amount there is no price to check.
                            if (_amount.text.trim().isEmpty) return null;
                            final code = value ?? '';
                            if (code.isEmpty) return l10n.currencyRequired;
                            return kCurrencies.contains(code)
                                ? null
                                : l10n.currencyUnknown;
                          },
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: Spacing.s24),
                  Text(l10n.giftLinksLabel, style: theme.textTheme.titleMedium),
                  for (final (index, link) in _links.indexed) ...[
                    const SizedBox(height: Spacing.s12),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: TextFormField(
                            key: ObjectKey(link),
                            controller: link,
                            decoration: InputDecoration(
                              labelText: l10n.giftLinkLabel(index + 1),
                              errorMaxLines: 2,
                            ),
                            keyboardType: TextInputType.url,
                            inputFormatters: [
                              LengthLimitingTextInputFormatter(kLinkMaxLength),
                            ],
                            validator: (value) {
                              final text = (value ?? '').trim();
                              return text.isEmpty || webLink(text) != null
                                  ? null
                                  : l10n.linkInvalid;
                            },
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.close),
                          tooltip: l10n.removeLink,
                          onPressed: () => _removeLink(index),
                        ),
                      ],
                    ),
                  ],
                  if (_links.length < kMaxLinks) ...[
                    const SizedBox(height: Spacing.s8),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: _addLink,
                        icon: const Icon(Icons.add_link),
                        label: Text(l10n.addLink),
                      ),
                    ),
                  ],
                  const SizedBox(height: Spacing.s24),
                  FilledButton(
                    onPressed: _busy || _imageBusy ? null : _save,
                    child: Text(_adding ? addLabel : l10n.save),
                  ),
                  if (!_adding && !_hidden) ...[
                    const SizedBox(height: Spacing.s12),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _markReceived,
                      icon: const Icon(Icons.inventory_2_outlined),
                      label: Text(l10n.markReceived),
                    ),
                  ],
                  if (!_adding) ...[
                    const SizedBox(height: Spacing.s12),
                    TextButton.icon(
                      onPressed: _busy ? null : _delete,
                      style: TextButton.styleFrom(
                        foregroundColor: theme.colorScheme.error,
                      ),
                      icon: const Icon(Icons.delete_outline),
                      label: Text(l10n.deleteGift),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Wide enough for a three-letter code and the field's label.
const double _currencyWidth = 112;

final _upperCase = TextInputFormatter.withFunction(
  (oldValue, newValue) => newValue.copyWith(text: newValue.text.toUpperCase()),
);
