/// Android and iOS: no paste event to listen to; the Paste image button reads
/// the clipboard (GIFT_IMAGES D14).
library;

import 'gift_image_section.dart';

/// Calls [onPaste] with the files of each paste in the page until the
/// returned function is called; here, never.
void Function() listenToPaste(bool Function(List<PastedFile> files) onPaste) =>
    () {};
