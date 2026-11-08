import 'package:flutter/material.dart';

import 'tokens.dart';

/// Colours [ColorScheme] has no slot for (DESIGN_SYSTEM_PLAN D3).
///
/// Invitee activity is a theme extension rather than a Material role because
/// Material widgets paint `secondary` and `tertiary` on their own: rose must
/// only appear where invitee activity is shown, so that a rose element on a
/// recipient's screen is a visible bug.
@immutable
class WishlistColors extends ThemeExtension<WishlistColors> {
  const WishlistColors({
    required this.inviteeActivity,
    required this.inviteeActivityContainer,
    required this.onInviteeActivityContainer,
    required this.pageBackground,
    required this.bodyText,
  });

  /// Rose accent for invitee activity: reservations, purchases, pledges,
  /// comments and their counts. Nothing else uses it.
  final Color inviteeActivity;

  /// Background of invitee-activity chips and badges.
  final Color inviteeActivityContainer;

  /// Text and icons on [inviteeActivityContainer].
  final Color onInviteeActivityContainer;

  /// Behind the surfaces; also the theme's `scaffoldBackgroundColor`.
  final Color pageBackground;

  /// Running text, softer than the `onSurface` of headings.
  final Color bodyText;

  static const light = WishlistColors(
    inviteeActivity: LightColors.inviteeActivity,
    inviteeActivityContainer: LightColors.inviteeActivityContainer,
    onInviteeActivityContainer: LightColors.onInviteeActivityContainer,
    pageBackground: LightColors.pageBackground,
    bodyText: LightColors.bodyText,
  );

  static const dark = WishlistColors(
    inviteeActivity: DarkColors.inviteeActivity,
    inviteeActivityContainer: DarkColors.inviteeActivityContainer,
    onInviteeActivityContainer: DarkColors.onInviteeActivityContainer,
    pageBackground: DarkColors.pageBackground,
    bodyText: DarkColors.bodyText,
  );

  @override
  WishlistColors copyWith({
    Color? inviteeActivity,
    Color? inviteeActivityContainer,
    Color? onInviteeActivityContainer,
    Color? pageBackground,
    Color? bodyText,
  }) {
    return WishlistColors(
      inviteeActivity: inviteeActivity ?? this.inviteeActivity,
      inviteeActivityContainer:
          inviteeActivityContainer ?? this.inviteeActivityContainer,
      onInviteeActivityContainer:
          onInviteeActivityContainer ?? this.onInviteeActivityContainer,
      pageBackground: pageBackground ?? this.pageBackground,
      bodyText: bodyText ?? this.bodyText,
    );
  }

  @override
  WishlistColors lerp(WishlistColors? other, double t) {
    if (other == null) return this;
    return WishlistColors(
      inviteeActivity: Color.lerp(inviteeActivity, other.inviteeActivity, t)!,
      inviteeActivityContainer: Color.lerp(
          inviteeActivityContainer, other.inviteeActivityContainer, t)!,
      onInviteeActivityContainer: Color.lerp(
          onInviteeActivityContainer, other.onInviteeActivityContainer, t)!,
      pageBackground: Color.lerp(pageBackground, other.pageBackground, t)!,
      bodyText: Color.lerp(bodyText, other.bodyText, t)!,
    );
  }
}

/// `context.wishlistColors`: the [WishlistColors] of the current theme.
extension WishlistColorsContext on BuildContext {
  WishlistColors get wishlistColors =>
      Theme.of(this).extension<WishlistColors>()!;
}
