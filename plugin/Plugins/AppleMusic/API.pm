package Plugins::AppleMusic::API;

# SPDX-License-Identifier: GPL-2.0-or-later
# Async HTTP client for the local applemusic-helper sidecar.

use strict;
use warnings;

use JSON::XS::VersionOneAndTwo;
use URI::Escape qw(uri_escape_utf8);

use Slim::Networking::SimpleAsyncHTTP;
use Slim::Utils::Cache;
use Slim::Utils::Log;
use Slim::Utils::Prefs;

my $log   = logger('plugin.applemusic');
my $prefs = preferences('plugin.applemusic');
my $cache = Slim::Utils::Cache->new('applemusic');

use constant CACHE_TTL => 3600;

sub _base {
	my $url = $prefs->get('helperUrl') || 'http://127.0.0.1:9863';
	$url =~ s{/$}{};
	return $url;
}

# GET helper JSON. $args: { path, params, cb, ecb, ttl, nocache }
sub get {
	my ($class, $args) = @_;

	my $path   = $args->{path} or return $args->{ecb}->('missing path');
	my $params = $args->{params} || {};
	my $cb     = $args->{cb}  || sub {};
	my $ecb    = $args->{ecb} || sub { $log->warn("Apple Music helper error: @_") };
	my $ttl    = defined $args->{ttl} ? $args->{ttl} : CACHE_TTL;

	my $query = join('&', map {
		uri_escape_utf8($_) . '=' . uri_escape_utf8($params->{$_})
	} grep { defined $params->{$_} } sort keys %$params);

	my $url = _base() . $path . ($query ? "?$query" : '');
	my $ckey = "amget:$url";

	if ( !$args->{nocache} && (my $cached = $cache->get($ckey)) ) {
		main::DEBUGLOG && $log->is_debug && $log->debug("cache hit $url");
		return $cb->($cached);
	}

	main::INFOLOG && $log->is_info && $log->info("GET $url");

	Slim::Networking::SimpleAsyncHTTP->new(
		sub {
			my $http = shift;
			my $data = eval { from_json($http->content) };
			if ($@ || !defined $data) {
				return $ecb->("bad JSON from helper: $@");
			}
			$cache->set($ckey, $data, $ttl) if $ttl && !$args->{nocache};
			$cb->($data);
		},
		sub {
			my ($http, $error) = @_;
			$error ||= ($http && $http->error) || 'unknown error';
			my $code = $http && $http->code || 0;
			$log->warn("helper request failed ($code): $error -- $url");
			$ecb->($error, $code);
		},
		{
			timeout => 60,
			cache   => 0,
		},
	)->get($url);
}

# ---- typed helpers -------------------------------------------------------------

my $healthCache;
my $healthCacheTime = 0;

# last known /health result (hashref) or undef; second value = age in seconds
sub cachedHealth {
	return wantarray ? ($healthCache, time() - $healthCacheTime) : $healthCache;
}

sub health {
	my ($class, $cb, $ecb) = @_;
	$class->get({
		path => '/health', ttl => 0, nocache => 1,
		cb => sub {
			my $data = shift;
			$healthCache = $data;
			$healthCacheTime = time();
			$cb->($data) if $cb;
		},
		ecb => sub {
			$healthCache = undef;
			$healthCacheTime = time();
			$ecb->(@_) if $ecb;
		},
	});
}

sub reloadCdm {
	my ($class, $cb, $ecb) = @_;
	my $url = _base() . '/cdm/reload';
	Slim::Networking::SimpleAsyncHTTP->new(
		sub { $cb->(eval { from_json($_[0]->content) } || {}) if $cb },
		sub { $ecb->($_[1] || 'error') if $ecb },
		{ timeout => 15 },
	)->post($url);
}

sub search {
	my ($class, $term, $types, $cb, $ecb) = @_;
	$class->get({
		path => '/search',
		params => { q => $term, types => (ref $types ? join(',', @$types) : $types), limit => 25 },
		ttl => 300, cb => $cb, ecb => $ecb,
	});
}

sub trackMeta {
	my ($class, $id, $cb, $ecb) = @_;
	$class->get({ path => "/meta/track/$id", cb => $cb, ecb => $ecb });
}

sub tracksMeta {
	my ($class, $ids, $cb, $ecb) = @_;
	$class->get({
		path => '/meta/tracks',
		params => { ids => (ref $ids ? join(',', @$ids) : $ids) },
		cb => $cb, ecb => $ecb,
	});
}

sub itemMeta {
	my ($class, $kind, $id, $cb, $ecb) = @_;
	$class->get({ path => "/meta/$kind/$id", cb => $cb, ecb => $ecb });
}

sub albumTracks {
	my ($class, $id, $cb, $ecb) = @_;
	$class->get({ path => "/album/$id/tracks", cb => $cb, ecb => $ecb });
}

sub playlistTracks {
	my ($class, $id, $cb, $ecb) = @_;
	$class->get({ path => "/playlist/$id/tracks", ttl => 600, cb => $cb, ecb => $ecb });
}

sub artistTracks {
	my ($class, $id, $cb, $ecb) = @_;
	$class->get({ path => "/artist/$id/tracks", cb => $cb, ecb => $ecb });
}

sub artistAlbums {
	my ($class, $id, $cb, $ecb) = @_;
	$class->get({ path => "/artist/$id/albums", cb => $cb, ecb => $ecb });
}

sub library {
	my ($class, $kind, $cb, $ecb) = @_;
	$class->get({ path => "/library/$kind", ttl => 600, cb => $cb, ecb => $ecb });
}

sub recommendations {
	my ($class, $cb, $ecb) = @_;
	$class->get({ path => '/recommendations', ttl => 1800, cb => $cb, ecb => $ecb });
}

sub stations {
	my ($class, $cb, $ecb) = @_;
	$class->get({ path => '/stations', ttl => 1800, cb => $cb, ecb => $ecb });
}

# Base stream URL. custom-convert.conf appends "/<seconds>" as $START$ for seeks.
sub streamUrl {
	my ($class, $id) = @_;
	return _base() . "/stream/$id";
}

1;
