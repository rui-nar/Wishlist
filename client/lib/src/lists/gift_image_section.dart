/// The gift form's image (GIFT_IMAGES D14): a preview, and the ways to add,
/// replace or remove it.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:pasteboard/pasteboard.dart';
import 'package:provider/provider.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../api/api_image.dart';
import '../design/tokens.dart';
import '../error_line.dart';
import 'common.dart';
import 'gift_links.dart';
import 'lists_repository.dart';
import 'paste_stub.dart' if (dart.library.js_interop) 'paste_web.dart';

/// The server's limit on an image's bytes (D4, D11): a larger file is
/// refused here, before it is sent.
const kImageMaxBytes = 10 * 1024 * 1024;

/// The server's limit on an image URL's length (D6).
const kImageUrlMaxLength = 2048;

/// What the picker re-encodes a photo to before it is sent (D5): HEIC
/// becomes JPEG, and a 12 MP photo a few hundred KB.
const kPickMaxSide = 2048.0;
const kPickQuality = 90;

/// Image bytes from the device; null when there are none (the user
/// cancelled the picker, the clipboard holds no image).
typedef ImageBytesSource = Future<Uint8List?> Function();

/// The photo the user picks from the device's gallery, with D5's options.
/// Without the full metadata, iOS needs no photo library permission; the
/// server drops it anyway (D4).
Future<Uint8List?> pickFromGallery() async {
  final file = await ImagePicker().pickImage(
    source: ImageSource.gallery,
    maxWidth: kPickMaxSide,
    maxHeight: kPickMaxSide,
    imageQuality: kPickQuality,
    requestFullMetadata: false,
  );
  return file?.readAsBytes();
}

/// The clipboard's image. In a browser, through the async clipboard API,
/// which may ask for permission and reads little in Firefox: the paste event
/// (Ctrl/Cmd+V) is the dependable way there.
Future<Uint8List?> readClipboardImage() => Pasteboard.image;

/// A file of a paste in the browser: its MIME type, and its bytes on demand.
class PastedFile {
  const PastedFile({required this.type, required this.read});

  final String type;
  final Future<Uint8List> Function() read;
}

/// The message for a refused image call, by its D11 code; null when [error]
/// is not one. A 413 without a code (a proxy's) is still a file too large.
String? imageRefusal(AppLocalizations l10n, Object? error) {
  if (error is! ApiException) return null;
  return switch (error.body?['detail']) {
    'image_too_large' => l10n.imageTooLarge,
    'image_too_many_pixels' => l10n.imageTooManyPixels,
    'image_unsupported' => l10n.imageUnsupported,
    'image_busy' => l10n.imageBusy,
    'url_not_allowed' => l10n.imageUrlNotAllowed,
    'url_fetch_failed' => l10n.imageUrlFetchFailed,
    'image_not_attachable' => l10n.imageNotAttachable,
    'image_expired' => l10n.imageExpired,
    _ => error.statusCode == 413 ? l10n.imageTooLarge : null,
  };
}

/// The image part of the gift form: the gift's image, or the one just added,
/// with Choose image, Image URL, Paste image and Remove image. Adding sends
/// the image at once and shows the server's version (D1); the form attaches
/// it when it saves, through [onChanged]. In a browser, pasting anywhere in
/// the page while the form is open adds the pasted image.
class GiftImageSection extends StatefulWidget {
  const GiftImageSection({
    super.key,
    this.initial,
    required this.onChanged,
    this.onBusyChanged,
    this.enabled = true,
    this.pickImage = pickFromGallery,
    this.readClipboard = readClipboardImage,
  });

  /// The gift's image as saved; null when adding, or when it has none.
  final GiftImage? initial;

  /// What saving the gift should do to its image, after each change.
  final ValueChanged<ImageChange> onChanged;

  /// True while an image is being sent: saving then would leave it out.
  final ValueChanged<bool>? onBusyChanged;

  /// False while the form saves.
  final bool enabled;

  final ImageBytesSource pickImage;
  final ImageBytesSource readClipboard;

  @override
  State<GiftImageSection> createState() => GiftImageSectionState();
}

/// Public for [handlePaste], which tests call as the browser would.
class GiftImageSectionState extends State<GiftImageSection> {
  late final _repository = ListsRepository.of(context);
  late GiftImage? _image = widget.initial;
  bool _busy = false;
  String? _error;
  late final void Function() _stopListening;

  bool get _canAct => widget.enabled && !_busy;

  @override
  void initState() {
    super.initState();
    _stopListening = listenToPaste(handlePaste);
  }

  @override
  void dispose() {
    _stopListening();
    super.dispose();
  }

  /// A paste in the page: adds its first image, if any, and says whether it
  /// took one. Not while the section is busy or disabled, nor while a dialog
  /// covers the form.
  @visibleForTesting
  bool handlePaste(List<PastedFile> files) {
    if (!mounted || !_canAct) return false;
    if (!(ModalRoute.of(context)?.isCurrent ?? true)) return false;
    final image = files.where((file) => file.type.startsWith('image/'));
    if (image.isEmpty) return false;
    _addBytes(image.first.read);
    return true;
  }

  Future<void> _choose() => _addBytes(widget.pickImage);

  Future<void> _paste() {
    final l10n = AppLocalizations.of(context);
    return _addBytes(
      widget.readClipboard,
      whenNone: kIsWeb ? l10n.imageClipboardEmptyWeb : l10n.imageClipboardEmpty,
    );
  }

  /// Reads bytes from [source] and sends them. No bytes is a cancel, or
  /// [whenNone] when it says why; a source that fails says [whenNone] too.
  Future<void> _addBytes(ImageBytesSource source, {String? whenNone}) async {
    final l10n = AppLocalizations.of(context);
    setState(() => _error = null);
    Uint8List? bytes;
    try {
      bytes = await source();
    } catch (_) {
      if (mounted) setState(() => _error = whenNone ?? l10n.imageReadFailed);
      return;
    }
    if (!mounted) return;
    if (bytes == null || bytes.isEmpty) {
      if (whenNone != null) setState(() => _error = whenNone);
      return;
    }
    if (bytes.length > kImageMaxBytes) {
      setState(() => _error = l10n.imageTooLarge);
      return;
    }
    final upload = bytes;
    await _send(() => _repository.uploadImage(upload));
  }

  Future<void> _fromUrl() async {
    setState(() => _error = null);
    final url = await showDialog<String>(
      context: context,
      builder: (_) => const _ImageUrlDialog(),
    );
    if (url == null || !mounted) return;
    await _send(() => _repository.imageFromUrl(url));
  }

  /// Sends an image, then shows the server's version, or why it was refused.
  Future<void> _send(Future<PendingImage> Function() send) async {
    final l10n = AppLocalizations.of(context);
    _setBusy(true);
    try {
      final image = await send();
      if (!mounted) return;
      setState(() => _image = image);
      widget.onChanged(AttachImage(image.id));
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = imageRefusal(l10n, error) ?? failureMessage(l10n, error);
      });
    } finally {
      if (mounted) _setBusy(false);
    }
  }

  void _setBusy(bool busy) {
    setState(() => _busy = busy);
    widget.onBusyChanged?.call(busy);
  }

  /// Removing an image the gift never had (added then removed) changes
  /// nothing.
  void _remove() {
    setState(() {
      _image = null;
      _error = null;
    });
    widget.onChanged(
      widget.initial == null ? const KeepImage() : const RemoveImage(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final image = _image;
    final placeholder = _Placeholder(size: image == null ? _placeholderSize : null);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(l10n.giftImageLabel, style: theme.textTheme.titleMedium),
        const SizedBox(height: Spacing.s12),
        Align(
          alignment: Alignment.centerLeft,
          child: Stack(
            alignment: Alignment.center,
            children: [
              if (image == null)
                placeholder
              else
                ConstrainedBox(
                  constraints: const BoxConstraints(
                    maxHeight: _previewMaxHeight,
                  ),
                  child: AspectRatio(
                    aspectRatio: image.width / image.height,
                    child: ClipRRect(
                      borderRadius: const BorderRadius.all(
                        Radius.circular(Radii.md),
                      ),
                      child: Image(
                        key: const ValueKey('gift-image-preview'),
                        image: ApiImage(context.read<ApiClient>(), image.url),
                        semanticLabel: l10n.giftImagePreview,
                        fit: BoxFit.contain,
                        errorBuilder: (_, _, _) => placeholder,
                      ),
                    ),
                  ),
                ),
              if (_busy)
                CircularProgressIndicator(semanticsLabel: l10n.imageUploading),
            ],
          ),
        ),
        const SizedBox(height: Spacing.s8),
        Wrap(
          spacing: Spacing.s8,
          children: [
            TextButton.icon(
              onPressed: _canAct ? _choose : null,
              icon: const Icon(Icons.photo_library_outlined),
              label: Text(l10n.imageChoose),
            ),
            TextButton.icon(
              onPressed: _canAct ? _fromUrl : null,
              icon: const Icon(Icons.link),
              label: Text(l10n.imageFromUrl),
            ),
            TextButton.icon(
              onPressed: _canAct ? _paste : null,
              icon: const Icon(Icons.content_paste),
              label: Text(l10n.imagePaste),
            ),
            if (image != null)
              TextButton.icon(
                onPressed: _canAct ? _remove : null,
                icon: const Icon(Icons.hide_image_outlined),
                label: Text(l10n.imageRemove),
              ),
          ],
        ),
        if (_error != null) ...[
          const SizedBox(height: Spacing.s8),
          ErrorLine(_error!),
        ],
      ],
    );
  }
}

const double _previewMaxHeight = 200;
const double _placeholderSize = 96;

/// No image: the gift card's placeholder, at [size], or filling the preview
/// when the image fails to load.
class _Placeholder extends StatelessWidget {
  const _Placeholder({this.size});

  final double? size;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ClipRRect(
      borderRadius: const BorderRadius.all(Radius.circular(Radii.md)),
      child: SizedBox(
        width: size,
        height: size,
        child: ColoredBox(
          color: scheme.primaryContainer,
          child: ExcludeSemantics(
            child: Icon(
              Icons.card_giftcard_outlined,
              color: scheme.onPrimaryContainer,
            ),
          ),
        ),
      ),
    );
  }
}

/// Asks for an image's web address; pops it, trimmed, or null.
class _ImageUrlDialog extends StatefulWidget {
  const _ImageUrlDialog();

  @override
  State<_ImageUrlDialog> createState() => _ImageUrlDialogState();
}

class _ImageUrlDialogState extends State<_ImageUrlDialog> {
  final _form = GlobalKey<FormState>();
  final _url = TextEditingController();

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  void _submit() {
    if (_form.currentState!.validate()) {
      Navigator.of(context).pop(_url.text.trim());
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.imageUrlTitle),
      content: Form(
        key: _form,
        child: TextFormField(
          controller: _url,
          autofocus: true,
          decoration: InputDecoration(
            labelText: l10n.imageUrlLabel,
            errorMaxLines: 2,
          ),
          keyboardType: TextInputType.url,
          inputFormatters: [
            LengthLimitingTextInputFormatter(kImageUrlMaxLength),
          ],
          validator: (value) =>
              webLink((value ?? '').trim()) == null ? l10n.linkInvalid : null,
          onFieldSubmitted: (_) => _submit(),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.cancel),
        ),
        TextButton(onPressed: _submit, child: Text(l10n.imageUrlConfirm)),
      ],
    );
  }
}
