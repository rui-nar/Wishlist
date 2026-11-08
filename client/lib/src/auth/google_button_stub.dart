/// Stub for Android and iOS, where the sign-in screen shows its own button
/// calling `authenticate()` instead of Google's web button.
library;

import 'package:flutter/material.dart';

Widget buildGoogleSignInButton(BuildContext context) => const SizedBox.shrink();
