#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# set-version.sh <version>
# Stamp <version> into every file that carries it. Run in CI right after
# checkout; the git tag is the single source of truth.
set -euo pipefail

V="${1:?usage: set-version.sh <version>}"

sed -i.bak -E "s#<version>[^<]*</version>#<version>${V}</version>#" \
    plugin/Plugins/AppleMusic/install.xml
sed -i.bak -E "s#^__version__ = .*#__version__ = \"${V}\"#" \
    helper/applemusic_helper/__init__.py
sed -i.bak -E "s#^version = \".*\"#version = \"${V}\"#" \
    helper/pyproject.toml

rm -f plugin/Plugins/AppleMusic/install.xml.bak \
      helper/applemusic_helper/__init__.py.bak \
      helper/pyproject.toml.bak

echo "stamped version ${V}"
grep -m1 '<version>' plugin/Plugins/AppleMusic/install.xml
