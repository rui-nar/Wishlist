# Wishlist client

The Flutter client for web, Android and iOS. For now it is a single screen that
shows its own version and the server's `GET /api/version` (version and env).

## Build settings

Both come from `--dart-define`:

| Name | Default | Meaning |
|---|---|---|
| `API_BASE_URL` | empty | Server origin, e.g. `http://localhost:8000`. Empty means same origin, which is how the web build is served in the Docker image. Android and iOS builds must set it. |
| `APP_VERSION` | `dev` | The client's version, shown as is (`v1.2.3`, `validation-<short sha>`). |

```
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
flutter build web --release --dart-define=APP_VERSION=v1.2.3
```

## Checks

```
flutter analyze
flutter test
```

## Android

Two flavours, two apps (`docs/plans/ANDROID_RELEASE_PLAN.md` D1), so a VAL
build never replaces a PROD install:

| Flavour | Application id | Name |
|---|---|---|
| `prod` | the Gradle property `wishlistAppId` | Wishlist |
| `val` | `wishlistAppId` + `.val` | Wishlist VAL |

Every Android command needs `--flavor`. Without one, Gradle builds both and
Flutter stops with "Gradle build failed to produce an .apk file". There is no
default flavour: `default-flavor` in `pubspec.yaml` would apply to iOS too,
which has no flavours. Use `val` on a device:

```
flutter run -d <device> --flavor val --dart-define=API_BASE_URL=http://<host>:8000
flutter build appbundle --flavor prod -P wishlistAppId=<application id>
```

`-P wishlistAppId=…` can also be given as the environment variable
`ORG_GRADLE_PROJECT_wishlistAppId`. The code's namespace is `app.wishlist` for
both, and is not the store id.

**Signing (D3).** A release build is signed with the upload key when these
environment variables are all set, and with the debug key when none is (so
`flutter run --release` works on a dev machine). Setting only some of them
fails the build.

| Variable | Meaning |
|---|---|
| `ANDROID_UPLOAD_KEYSTORE_PATH` | the keystore file (CI decodes the secret `ANDROID_UPLOAD_KEYSTORE_B64` into it) |
| `ANDROID_UPLOAD_KEYSTORE_PASSWORD` | the keystore's password |
| `ANDROID_UPLOAD_KEY_ALIAS` | the key's alias |
| `ANDROID_UPLOAD_KEY_PASSWORD` | the key's password |

`-P wishlistRequireUploadKey=true` (set by the release workflow) makes a build
without the upload key fail instead of signing with the debug key. No key or
password goes in a file of the repository; `*.jks` and `*.keystore` are
ignored.

**Icon (D5).** The launcher icons, legacy and adaptive, are generated from the
iOS icon's source image, `ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png`
(still Flutter's logo):

- `mipmap-*/ic_launcher.png`: the whole image at 48dp, for API 24 and 25;
- `mipmap-*/ic_launcher_foreground.png`: the image filling the inner 72dp of
  a transparent 108dp layer, over `@color/ic_launcher_background` (the image's
  white), through `mipmap-anydpi-v26/ic_launcher.xml`.

When the artwork changes, regenerate both sets at each density (mdpi 1x, hdpi
1.5x, xhdpi 2x, xxhdpi 3x, xxxhdpi 4x) and keep the background colour the
image's.

**SDK levels (D5).** `minSdk` and `targetSdk` are Flutter's defaults
(`flutter.minSdkVersion`, `flutter.targetSdkVersion`); Flutter's `targetSdk`
is the level Google Play requires.

## Placeholder application id

The project was created with the placeholder org `com.example`, so the Android
application id (`wishlistAppId`'s default, `com.example.wishlist`, and
`com.example.wishlist.val` for VAL) and the iOS bundle id
(`ios/Flutter/Identity.xcconfig`) are currently `com.example.wishlist`.
**This is not the real id.** The real one is an open decision in
`docs/plans/DEVOPS_FOUNDATION_PLAN.md` and `docs/plans/ANDROID_RELEASE_PLAN.md`,
and it cannot change after the first store upload: a build published to
Google Play or the App Store must be given it (`-P wishlistAppId=…` on
Android), and the release workflows refuse the placeholder.
