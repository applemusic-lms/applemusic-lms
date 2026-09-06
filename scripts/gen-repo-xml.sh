#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# gen-repo-xml.sh <version> <owner/repo>
# Emits repo.xml pointing at the GitHub release assets. Run from repo root after
# dist/AppleMusic-<version>.zip exists.
set -euo pipefail

VERSION="${1:?version}"
REPO="${2:?owner/repo}"
ZIP="dist/AppleMusic-${VERSION}.zip"
SHA=$(sha1sum "$ZIP" | cut -d' ' -f1)
BASE="https://github.com/${REPO}/releases/download/v${VERSION}"

cat <<XML
<?xml version="1.0" encoding="utf-8"?>
<extensions>
	<details>
		<title lang="EN">Apple Music for LMS (unofficial)</title>
	</details>
	<plugins>
		<plugin name="AppleMusic" version="${VERSION}" minTarget="8.0" maxTarget="*">
			<title lang="EN">Apple Music</title>
			<desc lang="EN">Stream your Apple Music subscription (unofficial). Supply a Widevine CDM; the helper and ffmpeg download automatically.</desc>
			<url>${BASE}/AppleMusic-${VERSION}.zip</url>
			<sha>${SHA}</sha>
			<link>https://github.com/${REPO}</link>
			<creator>applemusic-lms contributors</creator>
		</plugin>
	</plugins>
</extensions>
XML
