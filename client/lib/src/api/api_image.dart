/// An image the API serves behind the session (GIFT_IMAGES D13).
library;

import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import 'api_client.dart';

/// Loads `<baseUrl><path>` through [ApiClient.getBytes], so the bearer token
/// is sent on every platform. Two providers with the same [path] are the same
/// image, which is what Flutter's image cache keys on. A failed load is an
/// error the widget showing it turns into its placeholder.
@immutable
class ApiImage extends ImageProvider<ApiImage> {
  const ApiImage(this.api, this.path);

  final ApiClient api;
  final String path;

  @override
  Future<ApiImage> obtainKey(ImageConfiguration configuration) =>
      SynchronousFuture<ApiImage>(this);

  @override
  ImageStreamCompleter loadImage(
    ApiImage key,
    ImageDecoderCallback decode,
  ) =>
      OneFrameImageStreamCompleter(_load(decode));

  Future<ImageInfo> _load(ImageDecoderCallback decode) async {
    final bytes = await api.getBytes(path);
    final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
    final codec = await decode(buffer);
    final frame = await codec.getNextFrame();
    return ImageInfo(image: frame.image);
  }

  @override
  bool operator ==(Object other) =>
      other is ApiImage && other.path == path;

  @override
  int get hashCode => path.hashCode;

  @override
  String toString() => 'ApiImage($path)';
}
