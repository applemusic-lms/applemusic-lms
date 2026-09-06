#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Runs INSIDE a manylinux2014 container (CentOS 7, glibc 2.17) via `docker run`
# to build a portable PyInstaller binary of the helper. PyInstaller can't use
# manylinux's static python, so we fetch a shared-libpython build from
# python-build-standalone (also glibc 2.17).
#   $1  = arch key (x86_64 | aarch64)
#   env = PBS_TAG, PBS_VER
set -euxo pipefail

ARCH="${1:?arch}"
: "${PBS_TAG:?PBS_TAG not set}"
: "${PBS_VER:?PBS_VER not set}"

PBS="cpython-${PBS_VER}+${PBS_TAG}-${ARCH}-unknown-linux-gnu-install_only.tar.gz"
curl -sSfL "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS}" \
  | tar xz -C /opt
PY=/opt/python/bin/python3

"$PY" -m pip install -q -U pip pyinstaller
"$PY" -m pip install -q -r helper/requirements.txt ./helper
"$PY" -m PyInstaller --onefile --name applemusic-helper \
  --collect-all pywidevine --collect-submodules aiohttp \
  --collect-data applemusic_helper helper/pyinstaller_entry.py

# proof of portability: this container IS glibc 2.17, so if it runs here it
# runs on any Linux from the last decade.
./dist/applemusic-helper --selftest
./dist/applemusic-helper --version
