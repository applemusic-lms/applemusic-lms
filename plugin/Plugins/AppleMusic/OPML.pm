package Plugins::AppleMusic::OPML;

# SPDX-License-Identifier: GPL-2.0-or-later
# Browse menu (OPML) for the Apple Music plugin.

use strict;
use warnings;

use Slim::Utils::Log;
use Slim::Utils::Prefs;
use Slim::Utils::Strings qw(cstring);

use Plugins::AppleMusic::API;

my $log   = logger('plugin.applemusic');
my $prefs = preferences('plugin.applemusic');

use constant IMG => '/plugins/AppleMusic/html/images/icon.png';

sub handleFeed {
	my ($client, $cb, $args) = @_;

	Plugins::AppleMusic::API->health(sub {
		my $health = shift || {};

		if ( !$health->{user_token_ok} ) {
			return $cb->({ items => [{
				name => cstring($client, 'PLUGIN_APPLEMUSIC_NOT_SIGNED_IN'),
				type => 'text',
			}, _signInHint($client, $health) ] });
		}

		my @items = (
			{
				name => cstring($client, 'SEARCH'),
				type => 'search',
				image => IMG,
				url  => \&searchMenu,
			},
			{
				name => cstring($client, 'PLUGIN_APPLEMUSIC_MY_MUSIC'),
				type => 'opml',
				image => IMG,
				items => [
					_libNode($client, 'playlists', 'PLAYLISTS'),
					_libNode($client, 'albums',    'ALBUMS'),
					_libNode($client, 'artists',   'ARTISTS'),
					_libNode($client, 'songs',     'SONGS'),
				],
			},
			{
				name => cstring($client, 'PLUGIN_APPLEMUSIC_MADE_FOR_YOU'),
				type => 'opml',
				image => IMG,
				url  => \&recommendationsMenu,
			},
			{
				name => cstring($client, 'PLUGIN_APPLEMUSIC_RADIO'),
				type => 'opml',
				image => IMG,
				url  => \&stationsMenu,
			},
		);

		if ( !$health->{cdm_ok} ) {
			unshift @items, {
				name => cstring($client, 'PLUGIN_APPLEMUSIC_NO_CDM'),
				type => 'text',
			};
		}

		$cb->({ items => \@items });
	}, sub {
		my $err = shift;
		$cb->({ items => [{
			name => cstring($client, 'PLUGIN_APPLEMUSIC_HELPER_DOWN') . " ($err)",
			type => 'text',
		}] });
	});
}

sub _signInHint {
	my ($client, $health) = @_;
	my $url = $health->{auth_url} || ($prefs->get('helperUrl') . '/auth');
	return {
		name => cstring($client, 'PLUGIN_APPLEMUSIC_SIGN_IN_AT') . " $url",
		type => 'text',
	};
}

sub _libNode {
	my ($client, $kind, $string) = @_;
	return {
		name  => cstring($client, $string),
		type  => 'opml',
		url   => sub {
			my ($client, $cb) = @_;
			Plugins::AppleMusic::API->library($kind, sub {
				my $data = shift || {};
				$cb->({ items => [ map { _item($client, $_) } @{ $data->{items} || [] } ] });
			}, _errCb($client, $cb));
		},
	};
}

sub searchMenu {
	my ($client, $cb, $args) = @_;
	my $q = $args->{search} or return $cb->({ items => [] });

	Plugins::AppleMusic::API->search($q, 'artists,albums,songs,playlists', sub {
		my $r = shift || {};
		my @items;

		push @items, {
			name => cstring($client, 'SONGS'), type => 'opml',
			items => [ map { _item($client, $_) } @{ $r->{songs} || [] } ],
		} if $r->{songs} && @{$r->{songs}};

		push @items, {
			name => cstring($client, 'ALBUMS'), type => 'opml',
			items => [ map { _item($client, $_) } @{ $r->{albums} || [] } ],
		} if $r->{albums} && @{$r->{albums}};

		push @items, {
			name => cstring($client, 'ARTISTS'), type => 'opml',
			items => [ map { _item($client, $_) } @{ $r->{artists} || [] } ],
		} if $r->{artists} && @{$r->{artists}};

		push @items, {
			name => cstring($client, 'PLAYLISTS'), type => 'opml',
			items => [ map { _item($client, $_) } @{ $r->{playlists} || [] } ],
		} if $r->{playlists} && @{$r->{playlists}};

		push @items, { name => cstring($client, 'EMPTY'), type => 'text' } if !@items;
		$cb->({ items => \@items });
	}, _errCb($client, $cb));
}

sub recommendationsMenu {
	my ($client, $cb) = @_;
	Plugins::AppleMusic::API->recommendations(sub {
		my $data = shift || {};
		my @items = map {
			{
				name  => $_->{title},
				type  => 'opml',
				items => [ map { _item($client, $_) } @{ $_->{items} || [] } ],
			}
		} @{ $data->{rows} || [] };
		$cb->({ items => \@items });
	}, _errCb($client, $cb));
}

sub stationsMenu {
	my ($client, $cb) = @_;
	Plugins::AppleMusic::API->stations(sub {
		my $data = shift || {};
		$cb->({ items => [ map { _item($client, $_) } @{ $data->{items} || [] } ] });
	}, _errCb($client, $cb));
}

# ---- item rendering ----------------------------------------------------------

sub _item {
	my ($client, $obj) = @_;
	my $type = $obj->{type} || '';

	if ( $type eq 'track' ) {
		return {
			name        => $obj->{title},
			line1       => $obj->{title},
			line2       => join(' - ', grep { $_ } $obj->{artist}, $obj->{album}),
			type        => 'audio',
			play        => $obj->{uri},
			url         => $obj->{uri},
			image       => $obj->{cover},
			duration    => $obj->{duration},
			playall     => 1,
			on_select   => 'play',
		};
	}
	elsif ( $type eq 'album' ) {
		return {
			name  => $obj->{title} . ($obj->{year} ? " ($obj->{year})" : ''),
			line1 => $obj->{title},
			line2 => $obj->{artist},
			type  => 'playlist',
			image => $obj->{cover},
			url   => sub {
				my ($client, $cb) = @_;
				Plugins::AppleMusic::API->albumTracks($obj->{id}, sub {
					my $d = shift || {};
					$cb->({ items => [ map { _item($client, $_) } @{ $d->{tracks} || [] } ] });
				}, _errCb($client, $cb));
			},
		};
	}
	elsif ( $type eq 'artist' ) {
		return {
			name  => $obj->{name},
			type  => 'opml',
			image => $obj->{cover},
			url   => sub {
				my ($client, $cb) = @_;
				my $out = { items => [] };
				Plugins::AppleMusic::API->artistAlbums($obj->{id}, sub {
					my $d = shift || {};
					push @{$out->{items}}, {
						name => cstring($client, 'PLUGIN_APPLEMUSIC_TOP_SONGS'),
						type => 'opml',
						url  => sub {
							my ($client, $cb2) = @_;
							Plugins::AppleMusic::API->artistTracks($obj->{id}, sub {
								my $t = shift || {};
								$cb2->({ items => [ map { _item($client, $_) } @{ $t->{tracks} || [] } ] });
							}, _errCb($client, $cb2));
						},
					};
					push @{$out->{items}}, map { _item($client, $_) } @{ $d->{albums} || [] };
					$cb->($out);
				}, _errCb($client, $cb));
			},
		};
	}
	elsif ( $type eq 'playlist' ) {
		return {
			name  => $obj->{name},
			line2 => $obj->{curator},
			type  => 'playlist',
			image => $obj->{cover},
			url   => sub {
				my ($client, $cb) = @_;
				Plugins::AppleMusic::API->playlistTracks($obj->{id}, sub {
					my $d = shift || {};
					$cb->({ items => [ map { _item($client, $_) } @{ $d->{tracks} || [] } ] });
				}, _errCb($client, $cb));
			},
		};
	}
	elsif ( $type eq 'station' ) {
		return {
			name  => $obj->{name},
			type  => 'audio',
			play  => $obj->{uri},
			url   => $obj->{uri},
			image => $obj->{cover},
		};
	}

	return { name => $obj->{name} || $obj->{title} || '?', type => 'text' };
}

sub _errCb {
	my ($client, $cb) = @_;
	return sub {
		my $err = shift || 'error';
		$cb->({ items => [{
			name => cstring($client, 'PLUGIN_APPLEMUSIC_ERROR') . ": $err",
			type => 'text',
		}] });
	};
}

1;
