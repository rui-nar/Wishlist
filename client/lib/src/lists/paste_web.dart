/// Web: the browser's paste event (GIFT_IMAGES D14). Ctrl/Cmd+V hands the
/// page the clipboard's files without the permission prompt the async
/// clipboard API may show, in every browser.
library;

import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'gift_image_section.dart';

/// Calls [onPaste] with the files of each paste in the page until the
/// returned function is called. A paste [onPaste] takes (it returns true)
/// goes no further, so no text field also receives it.
void Function() listenToPaste(bool Function(List<PastedFile> files) onPaste) {
  final listener = ((web.ClipboardEvent event) {
    final files = event.clipboardData?.files;
    if (files == null || files.length == 0) return;
    final pasted = [
      for (var i = 0; i < files.length; i++)
        if (files.item(i) case final file?)
          PastedFile(
            type: file.type,
            read: () async => (await file.arrayBuffer().toDart).toDart
                .asUint8List(),
          ),
    ];
    if (onPaste(pasted)) event.preventDefault();
  }).toJS;
  web.document.addEventListener('paste', listener);
  return () => web.document.removeEventListener('paste', listener);
}
