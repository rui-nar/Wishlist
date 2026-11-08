# Bundled fonts

The app bundles its fonts instead of fetching them at runtime
(DESIGN_SYSTEM_PLAN D4): owners edit offline, a download would send the
user's IP address to Google, and goldens must not depend on the network.
`pubspec.yaml` declares them, and `lib/main.dart` registers each family's
`OFL.txt` with `LicenseRegistry`.

Both families are licensed under the SIL Open Font License 1.1.

The sha256 values are of the files as downloaded. The TTFs are binary and
match in any checkout; the `OFL.txt` files are text, so git's line-ending
normalisation (`* text=auto`) can change their bytes in a working copy.

## Inter 4.1 (font version 4.001)

Static TTFs from the `extras/ttf` folder of the release archive
https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
(archive sha256
`9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`).
`OFL.txt` is the archive's `LICENSE.txt`.

| File | Weight | sha256 |
|---|---|---|
| `inter/Inter-Regular.ttf` | 400 | `40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82` |
| `inter/Inter-Medium.ttf` | 500 | `97ad806f526e41546d46365bb3a393145f75b7b1568913db74549ad8b8dba872` |
| `inter/Inter-SemiBold.ttf` | 600 | `78a843fade9d4612a5567302fb595b56976eb5fcebf4fea5a5912d638bafcde3` |
| `inter/Inter-Bold.ttf` | 700 | `288316099b1e0a47a4716d159098005eef7c0066921f34e3200393dbdb01947f` |
| `inter/OFL.txt` | — | `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |

## Space Grotesk 2.0.0 (font version 2.000)

Static TTFs from tag `2.0.0` of https://github.com/floriankarsten/space-grotesk
(`fonts/ttf/static`). Upstream publishes no static SemiBold, so card titles
use Medium (D4).

| File | Weight | Source | sha256 |
|---|---|---|---|
| `space_grotesk/SpaceGrotesk-Medium.ttf` | 500 | https://raw.githubusercontent.com/floriankarsten/space-grotesk/2.0.0/fonts/ttf/static/SpaceGrotesk-Medium.ttf | `3183b7eb0b4241476360e2cd8e527868616cc16d3ce332c4376505989b772b44` |
| `space_grotesk/SpaceGrotesk-Bold.ttf` | 700 | https://raw.githubusercontent.com/floriankarsten/space-grotesk/2.0.0/fonts/ttf/static/SpaceGrotesk-Bold.ttf | `7209bbb75fc0f5c546a5f5773b0db74ffc6abf04c2148c1105cace5765a96bdb` |
| `space_grotesk/OFL.txt` | — | https://raw.githubusercontent.com/floriankarsten/space-grotesk/2.0.0/OFL.txt | `564ce565c371c5e5bbf286006565a7c9aa55a9f56e7ca58d56e05d649dd61a72` |

## The `Roboto` alias

`pubspec.yaml` also declares a family named `Roboto` pointing at the Inter
files. Flutter's web engine downloads Roboto from `fonts.gstatic.com` at start
unless a family of that name is in the font manifest; the alias stops that
request.
