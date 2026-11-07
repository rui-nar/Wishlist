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

## Placeholder application id

The project was created with the placeholder org `com.example`, so the Android
application id and the iOS bundle id are currently `com.example.wishlist`.
**This is not the real id.** The real one is an open decision in
`docs/plans/DEVOPS_FOUNDATION_PLAN.md`, and it cannot change after the first
store upload: set it before any build is published to Google Play or the App
Store.
