package Plugins::AppleMusic::ProtocolHandler;

# SPDX-License-Identifier: GPL-2.0-or-later
#
# applemusic://track/<catalogId>
#   -> transcoding rule "apm" (custom-convert.conf) runs curl against the local
#      helper's /stream endpoint, which returns decrypted FLAC. Seeking is
#      server-side: LMS re-runs the command with $START$ = /<seconds>.
# music.apple.com/... share URLs -> exploded into applemusic:// track uris.

use strict;
use warnings;

use base qw(Slim::Formats::RemoteStream);

use Scalar::Util qw(blessed);

use Slim::Control::Request;
use Slim::Player::Playlist;
use Slim::Utils::Cache;
use Slim::Utils::Log;
use Slim::Utils::Prefs;
use Slim::Utils::Strings qw(cstring);

use Plugins::AppleMusic::API;

my $log   = logger('plugin.applemusic');
my $prefs = preferences('plugin.applemusic');
my $cache = Slim::Utils::Cache->new();

use constant IMG_TRACK => '/plugins/AppleMusic/html/images/cover.png';

sub isRemote { 1 }
sub isAudio  { 1 }
sub canDirectStream { 0 }

# "apm" is our pseudo-format; custom-convert.conf turns it into flc
sub getFormatForURL { 'apm' }
sub contentType     { 'apm' }
sub formatOverride  { 'apm' }

sub audioScrobblerSource { 'P' }        # chosen by the user

# server-side (transcoder) seek, like Spotty
sub canSeek          { 1 }
sub canTranscodeSeek { 1 }

sub getSeekData {
	my ($class, $client, $song, $newtime) = @_;
	return { timeOffset => $newtime };
}

# ------------------------------------------------------------------ track id
sub _idFromUrl {
	my $url = shift || '';
	return $1 if $url =~ m{^applemusic://track/([^/?]+)};
	return undef;
}

# ------------------------------------------------------------------ streaming
sub getNextTrack {
	my ($class, $song, $successCb, $errorCb) = @_;

	my $url = $song->track->url;
	my $id  = _idFromUrl($url);
	return $errorCb->("Not an Apple Music track URL: $url") unless $id;

	my $streamUrl = Plugins::AppleMusic::API->streamUrl($id);   # no seek: $START$ adds it

	# metadata is usually already cached from the browse list that queued this
	# track - use it and don't stall the stream on a lookup
	if ( my $meta = $cache->get("ameta:$url") ) {
		$song->duration($meta->{duration}) if $meta->{duration};
		$song->pluginData(meta => $meta);
		main::INFOLOG && $log->is_info && $log->info("stream $url -> $streamUrl (cached meta)");
		$song->streamUrl($streamUrl);
		return $successCb->();
	}

	Plugins::AppleMusic::API->trackMeta($id, sub {
		my $meta = shift;
		if ( $meta && ref $meta && $meta->{duration} ) {
			$song->duration($meta->{duration});
			$song->pluginData(meta => $meta);
			_cacheMeta($url, $meta);
		}
		main::INFOLOG && $log->is_info && $log->info("stream $url -> $streamUrl");
		$song->streamUrl($streamUrl);
		$successCb->();
	}, sub {
		my $error = shift;
		$log->warn("metadata lookup failed for $id: $error");
		$song->streamUrl($streamUrl);
		$successCb->();
	});
}

# ------------------------------------------------------------------ scanning
sub scanUrl {
	my ($class, $url, $args) = @_;
	$args->{cb}->( $args->{song}->currentTrack() );
}

sub explodePlaylist {
	my ($class, $client, $uri, $cb) = @_;

	my ($kind, $id);
	if ( $uri =~ m{^applemusic://(album|playlist|artist|station|track)/([^/?]+)} ) {
		($kind, $id) = ($1, $2);
	}
	elsif ( $uri =~ m{music\.apple\.com/[^/]+/(album|playlist|artist|song)/[^/]+/([a-zA-Z0-9.\-]+)} ) {
		($kind, $id) = ($1, $2);
		if ( $kind eq 'album' && $uri =~ m{[?&]i=(\d+)} ) {
			($kind, $id) = ('track', $1);
		}
		$kind = 'track' if $kind eq 'song';
	}

	return $cb->([]) unless $kind;
	return $cb->([ "applemusic://track/$id" ]) if $kind eq 'track' || $kind eq 'station';

	my $api  = 'Plugins::AppleMusic::API';
	my $done = sub {
		my $data = shift || {};
		my @tracks = grep { $_->{available} } @{ $data->{tracks} || [] };
		# stash metadata now so the playlist view has titles/art immediately
		_cacheMeta($_->{uri}, $_) for grep { $_->{uri} } @tracks;
		$cb->([ map { $_->{uri} } @tracks ]);
	};
	my $fail = sub { $cb->([]) };

	if    ( $kind eq 'album' )    { $api->albumTracks($id, $done, $fail) }
	elsif ( $kind eq 'playlist' ) { $api->playlistTracks($id, $done, $fail) }
	elsif ( $kind eq 'artist' )   { $api->artistTracks($id, $done, $fail) }
	else                          { $cb->([]) }
}

# ------------------------------------------------------------------ metadata
sub _cacheMeta {
	my ($url, $meta) = @_;
	return unless $url && $meta && ref $meta;
	$cache->set("ameta:$url", $meta, 86400);
}

# public: stash one track obj (or a list) from a browse menu so the playlist
# view and getNextTrack find it without a round-trip
sub cacheMeta {
	my ($class, @objs) = @_;
	for my $obj ( map { ref $_ eq 'ARRAY' ? @$_ : $_ } @objs ) {
		next unless ref $obj eq 'HASH';
		my $url = $obj->{uri} || ($obj->{id} && "applemusic://track/$obj->{id}");
		_cacheMeta($url, $obj);
	}
}

sub _renderMeta {
	my $meta = shift;
	return {
		title    => $meta->{title},
		artist   => $meta->{artist},
		album    => $meta->{album},
		duration => $meta->{duration},
		secs     => $meta->{duration},
		cover    => $meta->{cover} || IMG_TRACK,
		icon     => $meta->{cover} || IMG_TRACK,
		tracknum => $meta->{track_number},
		disc     => $meta->{disc_number},
		genre    => (ref $meta->{genres} ? $meta->{genres}[0] : undef),
		bitrate  => '256k',
		type     => 'Apple Music (AAC)',
	};
}

sub getMetadataFor {
	my ($class, $client, $url, undef, $song) = @_;

	my $id = _idFromUrl($url) or return {};

	my $meta;
	$meta = $song->pluginData('meta') if blessed($song) && $song->can('pluginData');
	$meta ||= $cache->get("ameta:$url");

	return _renderMeta($meta) if $meta;

	# miss - pull every still-unknown Apple Music track in this playlist in one
	# request, then nudge the UI to redraw
	_prefetchPlaylist($client) if $client;

	return {
		title   => cstring($client, 'PLUGIN_APPLEMUSIC_LOADING'),
		cover   => IMG_TRACK,
		icon    => IMG_TRACK,
		bitrate => '256k',
		type    => 'Apple Music (AAC)',
	};
}

sub _prefetchPlaylist {
	my $client = shift or return;
	$client = $client->master;

	return if $client->pluginData('fetchingMeta');

	# ids we've already asked about this session - Apple won't return every id
	# (region-locked etc.), so remember and don't refetch them on every redraw
	my $tried = $client->pluginData('metaTried') || {};

	my (@ids, %seen);
	for my $track ( @{ Slim::Player::Playlist::playList($client) || [] } ) {
		my $turl = blessed($track) ? $track->url : $track;
		my $tid  = _idFromUrl($turl) or next;
		next if $seen{$tid}++ || $tried->{$tid} || $cache->get("ameta:$turl");
		push @ids, $tid;
		last if @ids >= 50;
	}
	return unless @ids;

	$tried->{$_} = 1 for @ids;
	$client->pluginData(metaTried => $tried);
	$client->pluginData(fetchingMeta => 1);

	Plugins::AppleMusic::API->tracksMeta(\@ids, sub {
		my $data = shift || {};
		_cacheMeta($_->{uri} || "applemusic://track/$_->{id}", $_)
			for @{ $data->{tracks} || [] };
		$client->pluginData(fetchingMeta => 0);
		Slim::Control::Request::notifyFromArray($client, ['newmetadata']);
	}, sub {
		$client->pluginData(fetchingMeta => 0);
	});
}

sub getIcon {
	return Plugins::AppleMusic::Plugin->_pluginDataFor('icon') || IMG_TRACK;
}

1;
