[app]
title = ImageQuality
package.name = imagequality
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy==2.2.1
orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.3.0
fullscreen = 0
android.permissions = INTERNET, CAMERA, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE
android.api = 35
android.ndk = 28c
# android.sdk = 33
android.archs = arm64-v8a
android.minapi = 24
android.accept_sdk_license = True
[buildozer]
log_level = 2
warn_on_root = 1
