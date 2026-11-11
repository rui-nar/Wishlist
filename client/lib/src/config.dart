/// Build-time settings, passed with `--dart-define`.
library;

/// The server's origin, e.g. `http://localhost:8000`.
///
/// Empty means same origin: the web build is served by the FastAPI app next to
/// `/api/*` (one image, D5). Android and iOS builds must set it.
const kApiBaseUrl = String.fromEnvironment('API_BASE_URL');

/// The client's own version (D11): `v1.2.3`, `validation-<short sha>`, or
/// `dev` for a local build. Shown verbatim.
const kAppVersion = String.fromEnvironment('APP_VERSION', defaultValue: 'dev');

/// Google's iOS OAuth client ID (IOS_APP_PLAN D3), e.g.
/// `123-abc.apps.googleusercontent.com`. Empty means the iOS app offers no
/// Google sign-in. A build that sets it also sets its reversed form in
/// `ios/Flutter/Identity.xcconfig`; other platforms ignore it.
const kGoogleIosClientId = String.fromEnvironment('GOOGLE_IOS_CLIENT_ID');
