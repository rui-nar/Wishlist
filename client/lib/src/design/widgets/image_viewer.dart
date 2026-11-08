import 'package:flutter/material.dart';

import '../../../l10n/app_localizations.dart';

/// Opens [image] full screen, zoomable, with a close button (GIFT_IMAGES D15).
///
/// [semanticLabel] describes the picture to screen readers (the gift's title).
Future<void> showImageViewer(
  BuildContext context,
  ImageProvider image, {
  String? semanticLabel,
}) =>
    showDialog<void>(
      context: context,
      builder: (_) => ImageViewer(image: image, semanticLabel: semanticLabel),
    );

/// The content of [showImageViewer]; public so tests and goldens can pump it.
class ImageViewer extends StatelessWidget {
  const ImageViewer({super.key, required this.image, this.semanticLabel});

  final ImageProvider image;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Dialog.fullscreen(
      backgroundColor: scheme.scrim,
      child: Stack(
        children: [
          Positioned.fill(
            child: InteractiveViewer(
              maxScale: 5,
              child: Center(
                child: Image(
                  image: image,
                  semanticLabel: semanticLabel,
                  fit: BoxFit.contain,
                  errorBuilder: (_, _, _) => Icon(
                    Icons.broken_image_outlined,
                    size: 64,
                    color: scheme.onInverseSurface,
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            top: 0,
            right: 0,
            child: SafeArea(
              child: IconButton(
                tooltip: AppLocalizations.of(context).imageViewerClose,
                color: scheme.onInverseSurface,
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
