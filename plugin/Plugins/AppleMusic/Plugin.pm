package Plugins::AppleMusic::Plugin;

# Apple Music for Lyrion Music Server (unofficial)
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Thin OPML/protocol-handler front end. All Apple Music work (API, MusicKit
# sign-in, Widevine, ffmpeg decrypt) happens in the local "applemusic-helper"
# Python sidecar; this plugin only talks to it over HTTP.

use strict;
use warnings;

use base qw(Slim::Plugin::OPMLBased);

use Slim::Utils::Log;
use Slim::Utils::Prefs;
use Slim::Utils::Strings qw(cstring);

use Plugins::AppleMusic::API;
use Plugins::AppleMusic::Helper;
use Plugins::AppleMusic::ProtocolHandler;

use vars qw($VERSION);

my $log = Slim::Utils::Log->addLogCategory({
	category     => 'plugin.applemusic',
	defaultLevel => 'WARN',
	description   => 'PLUGIN_APPLEMUSIC_NAME',
});

my $prefs = preferences('plugin.applemusic');

$prefs->init({
	helperUrl    => 'http://127.0.0.1:9863',
	helperPort   => 9863,
	audioFormat  => 'flac',
	cleanupTags  => 1,
	ffmpegSource => 'auto',      # auto | system | custom
	ffmpegPath   => '',
	cdmClientId    => '',
	cdmPrivateKey  => '',
	cdmWvd         => '',
	helperBinary => '',          # advanced: e.g. "python3 -m applemusic_helper"
	distRepo     => '',          # advanced: owner/repo override for downloads
});

$prefs->setValidate({
	validator => sub { $_[1] =~ m{^https?://[^/\s]+/?$} },
}, 'helperUrl');

$prefs->setValidate({ 'int' => 1, low => 1024, high => 65535 }, 'helperPort');

sub initPlugin {
	my $class = shift;

	if ( !main::TRANSCODING ) {
		$log->error('Apple Music needs transcoding enabled in LMS to work');
	}

	$VERSION = $class->_pluginDataFor('version');

	Slim::Player::ProtocolHandlers->registerHandler('applemusic', 'Plugins::AppleMusic::ProtocolHandler');

	if ( main::WEBUI ) {
		require Plugins::AppleMusic::Settings;
		Plugins::AppleMusic::Settings->new();
	}

	require Plugins::AppleMusic::OPML;

	$class->SUPER::initPlugin(
		feed   => \&Plugins::AppleMusic::OPML::handleFeed,
		tag    => 'applemusic',
		menu   => 'apps',
		is_app => 1,
		weight => 1,
	);

	# download (if needed), configure and start the helper; keeps itself alive
	Plugins::AppleMusic::Helper->init;
}

sub shutdownPlugin {
	Plugins::AppleMusic::Helper->shutdown;
}

sub postinitPlugin {
	my $class = shift;

	# hijack music.apple.com share URLs so they can be pasted into the search bar
	Slim::Player::ProtocolHandlers->registerURLHandler(
		qr{^https?://music\.apple\.com/}, 'Plugins::AppleMusic::ProtocolHandler'
	) if Slim::Player::ProtocolHandlers->can('registerURLHandler');
}

sub getDisplayName { 'PLUGIN_APPLEMUSIC_NAME' }

sub playerMenu {}

sub _pluginDataFor {
	my ($class, $key) = @_;
	my $data = Slim::Utils::PluginManager->dataForPlugin($class);
	return $data->{$key} if $data && ref $data && $data->{$key};
	return undef;
}

1;
