plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// PROD's application id (ANDROID_RELEASE_PLAN D1), from the Gradle property
// shushgiftAppId (`-P shushgiftAppId=…` on flutter build, or the environment
// variable ORG_GRADLE_PROJECT_shushgiftAppId). The committed default is the
// placeholder, which the release workflow refuses to upload.
val shushgiftAppId: String =
    providers.gradleProperty("shushgiftAppId").orNull?.takeIf { it.isNotBlank() }
        ?: "com.example.shushgift"

// The upload key (D3), from the environment only: no key or password is ever
// in a file of the repository. CI decodes ANDROID_UPLOAD_KEYSTORE_B64 into the
// file ANDROID_UPLOAD_KEYSTORE_PATH names.
val uploadKeyVariables =
    listOf(
        "ANDROID_UPLOAD_KEYSTORE_PATH",
        "ANDROID_UPLOAD_KEYSTORE_PASSWORD",
        "ANDROID_UPLOAD_KEY_ALIAS",
        "ANDROID_UPLOAD_KEY_PASSWORD",
    ).associateWith { providers.environmentVariable(it).orNull?.takeIf { value -> value.isNotEmpty() } }
val missingUploadKeyVariables = uploadKeyVariables.filterValues { it == null }.keys
val hasUploadKey = missingUploadKeyVariables.isEmpty()

// Set by the release workflow: a release build signed with the debug key is
// refused instead of uploaded.
val requireUploadKey = providers.gradleProperty("shushgiftRequireUploadKey").orNull == "true"

// The host whose links open the app (Shush Gift plan D7), from the Gradle
// property shushgiftAppLinkHost, which the release workflow sets to the host
// of the build's API_BASE_URL_* secret. Without it, the app claims no link.
val appLinkHost: String? =
    providers.gradleProperty("shushgiftAppLinkHost").orNull?.takeIf { it.isNotBlank() }
if (appLinkHost != null && !Regex("^[A-Za-z0-9.-]+$").matches(appLinkHost)) {
    throw GradleException("shushgiftAppLinkHost must be a bare host name, got: $appLinkHost")
}

if (!hasUploadKey && missingUploadKeyVariables.size < uploadKeyVariables.size) {
    // Some are set and some are not: a mistake, not a dev machine.
    throw GradleException("Upload key incomplete, missing: ${missingUploadKeyVariables.joinToString()}")
}
if (!hasUploadKey && requireUploadKey) {
    throw GradleException(
        "shushgiftRequireUploadKey is set but the upload key is not: ${missingUploadKeyVariables.joinToString()}",
    )
}

android {
    // The code's namespace, never the store id (D1). Both flavours share it.
    namespace = "app.shushgift"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = shushgiftAppId
        // Flutter's defaults (D5): its targetSdk is the level Play requires,
        // and a Flutter upgrade moves it.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // Two apps (D1): testers install VAL beside PROD, and a VAL build never
    // replaces a PROD install. Flutter builds need --flavor val or prod.
    flavorDimensions += "environment"
    productFlavors {
        create("val") {
            dimension = "environment"
            applicationIdSuffix = ".val"
            manifestPlaceholders["appLabel"] = "Shush Gift VAL"
        }
        create("prod") {
            dimension = "environment"
            manifestPlaceholders["appLabel"] = "Shush Gift"
        }
    }

    signingConfigs {
        if (hasUploadKey) {
            create("upload") {
                storeFile = file(uploadKeyVariables.getValue("ANDROID_UPLOAD_KEYSTORE_PATH")!!)
                storePassword = uploadKeyVariables.getValue("ANDROID_UPLOAD_KEYSTORE_PASSWORD")
                keyAlias = uploadKeyVariables.getValue("ANDROID_UPLOAD_KEY_ALIAS")
                keyPassword = uploadKeyVariables.getValue("ANDROID_UPLOAD_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // Without the upload key, the debug key, so `flutter run --release`
            // works on a dev machine. Play refuses a debug-signed bundle, and
            // the release workflow refuses to build one (shushgiftRequireUploadKey).
            signingConfig = signingConfigs.getByName(if (hasUploadKey) "upload" else "debug")
        }
    }
}

// The app-link intent filter, in a manifest generated only when
// shushgiftAppLinkHost is set and merged into the main one: without the
// property, the filter is left out (D7). autoVerify has Android check the
// host's /.well-known/assetlinks.json (server/app/app_links.py), so these are
// the paths that file's host lets the app open: /join, /shared/*,
// /create-account, /reset-password and exactly /account. `android:path` is
// exact, so /account/plan (Stripe's return, sold on the web only),
// /unsubscribe, /legal/*, /api/* and /welcome stay in the browser.
abstract class AppLinkManifestTask : DefaultTask() {
    @get:Input
    abstract val host: Property<String>

    @get:OutputFile
    abstract val manifest: RegularFileProperty

    @TaskAction
    fun write() {
        manifest.get().asFile.writeText(
            """
            |<manifest xmlns:android="http://schemas.android.com/apk/res/android">
            |    <application>
            |        <activity android:name="app.shushgift.MainActivity">
            |            <intent-filter android:autoVerify="true">
            |                <action android:name="android.intent.action.VIEW" />
            |                <category android:name="android.intent.category.DEFAULT" />
            |                <category android:name="android.intent.category.BROWSABLE" />
            |                <data android:scheme="https" />
            |                <data android:host="${host.get()}" />
            |                <data android:path="/join" />
            |                <data android:pathPrefix="/shared/" />
            |                <data android:path="/create-account" />
            |                <data android:path="/reset-password" />
            |                <data android:path="/account" />
            |            </intent-filter>
            |        </activity>
            |    </application>
            |</manifest>
            |
            """.trimMargin(),
        )
    }
}

if (appLinkHost != null) {
    val appLinkManifest =
        tasks.register<AppLinkManifestTask>("appLinkManifest") {
            host.set(appLinkHost)
            manifest.set(layout.buildDirectory.file("generated/appLinks/AndroidManifest.xml"))
        }
    androidComponents {
        onVariants { variant ->
            variant.sources.manifests.addGeneratedManifestFile(appLinkManifest, AppLinkManifestTask::manifest)
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
