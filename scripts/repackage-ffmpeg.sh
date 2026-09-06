#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Download known-good upstream *static* ffmpeg builds, keep only the `ffmpeg`
# binary, verify it runs and is >= 6.1, and re-archive as ffmpeg-<platform>.tar.gz.
# Run in GitHub Actions (ubuntu). Output dir is $1 (default: out).
set -euo pipefail

OUT="${1:-out}"
mkdir -p "$OUT" work
cd work

MIN="6.1"

# platform  ->  url  (each resolves to an archive containing a static `ffmpeg`)
# No macOS: there is no reliably-hosted static build. LMS-on-macOS users pick
# "System ffmpeg" or "Custom path" in the plugin settings (documented).
declare -A URLS=(
  [x86_64-linux]="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
  [aarch64-linux]="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
  [arm-linux]="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-armhf-static.tar.xz"
  [win-x64]="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
)

version_ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$2" ]; }

for plat in "${!URLS[@]}"; do
  url="${URLS[$plat]}"
  echo "== $plat  <-  $url"
  rm -rf x; mkdir x; cd x
  ok=1
  case "$url" in
    *.tar.xz) curl -fsSL "$url" | tar -xJ || ok=0 ;;
    *.zip)    curl -fsSL "$url" -o a.zip && unzip -q a.zip && rm a.zip || ok=0 ;;
  esac
  if [ "$ok" != 1 ]; then echo "  !! download failed for $plat, skipping"; cd ..; continue; fi

  bin=$(find . -type f \( -name ffmpeg -o -name ffmpeg.exe \) | head -1)
  if [ -z "$bin" ]; then echo "  !! no ffmpeg binary found for $plat, skipping"; cd ..; continue; fi
  chmod +x "$bin"

  # verify linux/native binaries; cross ones (arm on x86, win, mac) can't run here
  if [ "$plat" = x86_64-linux ]; then
    ver=$("$bin" -version | head -1 | grep -oP 'version \K[0-9]+\.[0-9]+')
    version_ge "$ver" "$MIN" || { echo "  !! $plat ffmpeg $ver < $MIN"; exit 1; }
    "$bin" -hide_banner -f lavfi -i anullsrc -t 0.1 -f null - </dev/null
    echo "  ok: ffmpeg $ver, decode smoke test passed"
  else
    echo "  (cross target - not executed here)"
  fi

  outname="ffmpeg"; [ "$plat" = win-x64 ] && outname="ffmpeg.exe"
  cp "$bin" "../$outname"
  cd ..
  tar -czf "../$OUT/ffmpeg-$plat.tar.gz" "$outname"
  rm -f "$outname"
done

cd ..
ls -la "$OUT"
