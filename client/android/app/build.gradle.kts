plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// PROD's application id (ANDROID_RELEASE_PLAN D1), from the Gradle property
// wishlistAppId (`-P wishlistAppId=…` on flutter build, or the environment
// variable ORG_GRADLE_PROJECT_wishlistAppId). The committed default is the
// placeholder, which the release workflow refuses to upload.
val wishlistAppId: String =
    providers.gradleProperty("wishlistAppId").orNull?.takeIf { it.isNotBlank() }
        ?: "com.example.wishlist"

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
val requireUploadKey = providers.gradleProperty("wishlistRequireUploadKey").orNull == "true"

if (!hasUploadKey && missingUploadKeyVariables.size < uploadKeyVariables.size) {
    // Some are set and some are not: a mistake, not a dev machine.
    throw GradleException("Upload key incomplete, missing: ${missingUploadKeyVariables.joinToString()}")
}
if (!hasUploadKey && requireUploadKey) {
    throw GradleException(
        "wishlistRequireUploadKey is set but the upload key is not: ${missingUploadKeyVariables.joinToString()}",
    )
}

android {
    // The code's namespace, never the store id (D1). Both flavours share it.
    namespace = "app.wishlist"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = wishlistAppId
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
            manifestPlaceholders["appLabel"] = "Wishlist VAL"
        }
        create("prod") {
            dimension = "environment"
            manifestPlaceholders["appLabel"] = "Wishlist"
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
            // the release workflow refuses to build one (wishlistRequireUploadKey).
            signingConfig = signingConfigs.getByName(if (hasUploadKey) "upload" else "debug")
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
