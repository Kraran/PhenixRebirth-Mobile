[app]
title = Phenix Rebirth
package.name = phenixrebirth
package.domain = org.kraran
source.dir = .
source.include_exts = py,png,jpg,jpeg,ogg,json,txt,md
source.exclude_dirs = build,docs,.git,__pycache__,archives,.buildozer,p4a-recipes
source.exclude_patterns = *.mp3,*.wav,*.apk
version = 1.1.1
requirements = python3==3.11.10,hostpython3==3.11.10,sdl2,pygame
orientation = landscape
fullscreen = 1
icon.filename = %(source.dir)s/assets/logo/frame_001.png
android.permissions = VIBRATE
android.archs = arm64-v8a
android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
p4a.branch = master
p4a.bootstrap = sdl2
p4a.local_recipes = /home/ffc59/phenix/PhenixRebirth-Mobile/p4a-recipes

[buildozer]
log_level = 2
warn_on_root = 0
android.numeric_version = 11011
