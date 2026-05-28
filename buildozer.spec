[app]
title = NetSocket Utility
package.name = netsocketutility
package.domain = com.netsocket.utility

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests, bin, .buildozer, .github, __pycache__, .git

version = 1.0.0
requirements = python3,kivy==2.3.0,pyjnius,android

# الخدمة الخلفية المستقلة للتطبيق
android.services = NetSocketService:service.py

orientation = portrait
fullscreen = 0

# الصلاحيات الحيوية للشبكات
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,WAKE_LOCK,FOREGROUND_SERVICE,RECEIVE_BOOT_COMPLETED

android.api = 34
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.accept_sdk_license = True

# معمارية متوافقة ومستقرة جداً للهواتف والـ Colab
android.archs = armeabi-v7a

android.allow_backup = False
android.release_artifact = apk
android.gradle_dependencies = androidx.core:core:1.12.0
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1