package Plugins::AppleMusic::Auth;

# SPDX-License-Identifier: GPL-2.0-or-later
#
# Sign-in / sign-out for Apple Music, served through the LMS web server so a
# headless box never has to reach the helper's own :9863/auth page. The helper
# still owns the token - these endpoints just relay to it.

use strict;
use warnings;

use JSON::XS::VersionOneAndTwo;

use Slim::Utils::Log;
use Slim::Web::HTTP;
use Slim::Web::Pages;

use Plugins::AppleMusic::API;

my $log = logger('plugin.applemusic');

sub init {
	Slim::Web::Pages->addRawFunction('plugins/AppleMusic/auth/token',  \&_setToken);
	Slim::Web::Pages->addRawFunction('plugins/AppleMusic/auth/signout', \&_signOut);
}

# same-origin guard: these mutate state and aren't CSRF-token protected, so
# reject cross-site callers. A missing Origin/Referer (curl, some proxies) is
# allowed through - LMS's own web password still applies if the user set one.
sub _sameOrigin {
	my $request = shift;
	my $host = $request->header('Host') or return 1;
	for my $h (qw(Origin Referer)) {
		my $v = $request->header($h) or next;
		return 0 unless $v =~ m{^https?://\Q$host\E(?:[/:]|$)};
	}
	return 1;
}

sub _reply {
	my ($httpClient, $response, $code, $data) = @_;
	my $body = to_json($data);
	$response->code($code);
	$response->content_type('application/json');
	$response->header('Content-Length' => length $body);
	$response->header('Connection' => 'close');
	Slim::Web::HTTP::addHTTPResponse($httpClient, $response, \$body);
}

sub _setToken {
	my ($httpClient, $response) = @_;
	my $request = $response->request;

	return _reply($httpClient, $response, 403, { error => 'cross-site request refused' })
		unless _sameOrigin($request);

	my $in = eval { from_json($request->content) } || {};
	my $token = $in->{media_user_token} || '';
	$token =~ s/^\s+|\s+$//g;

	if ( length($token) < 20 ) {
		return _reply($httpClient, $response, 400, { error => 'missing / implausible media-user-token' });
	}

	Plugins::AppleMusic::API->setUserToken($token, $in->{storefront}, sub {
		my $r = shift || {};
		if ( $r->{error} || (($r->{status} || '') eq 'error') ) {
			return _reply($httpClient, $response, 502, { error => $r->{error} || 'sign-in failed' });
		}
		Plugins::AppleMusic::API->health( sub {}, sub {} );   # refresh status panel
		_reply($httpClient, $response, 200, { status => 'ok', %$r });
	}, sub {
		my $err = shift || 'sign-in failed';
		_reply($httpClient, $response, 502, { error => $err });
	});
}

sub _signOut {
	my ($httpClient, $response) = @_;
	my $request = $response->request;

	return _reply($httpClient, $response, 403, { error => 'cross-site request refused' })
		unless _sameOrigin($request);

	Plugins::AppleMusic::API->signOut( sub {
		Plugins::AppleMusic::API->health( sub {}, sub {} );
		_reply($httpClient, $response, 200, { status => 'ok' });
	}, sub {
		_reply($httpClient, $response, 502, { error => (shift || 'sign-out failed') });
	});
}

1;
