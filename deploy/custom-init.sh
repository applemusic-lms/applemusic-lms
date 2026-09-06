#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
# ---------------------------------------------------------------------------
# OPTIONAL. You do NOT need this for a normal install — the plugin downloads
# and runs the helper (and ffmpeg) itself.
#
# It is only useful for the *development* path, where you want the plugin to
# run the helper from a Python source checkout instead of the prebuilt binary
# (set the "Helper binary override" pref to
#   /config/cache/applemusic-helper/venv/bin/python -m applemusic_helper
# and keep this file to build that venv on container start).
# ---------------------------------------------------------------------------
set -eu

apt-get update -qq
apt-get install --no-install-recommends -qy python3 python3-venv python3-pip ca-certificates

SRC=/config/applemusic-helper/src        # a checkout of this repo's helper/ dir
VENV=/config/cache/applemusic-helper/venv

if [ -f "$SRC/pyproject.toml" ]; then
    HASH_FILE="$VENV/.req.sha"
    NEW="$(sha1sum "$SRC/requirements.txt" | cut -d' ' -f1)"
    if [ ! -x "$VENV/bin/python" ] || [ "$(cat "$HASH_FILE" 2>/dev/null)" != "$NEW" ]; then
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install -q -U pip
        "$VENV/bin/pip" install -q -r "$SRC/requirements.txt" -e "$SRC"
        echo "$NEW" > "$HASH_FILE"
    fi
fi
