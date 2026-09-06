package Plugins::AppleMusic::Settings;

# SPDX-License-Identifier: GPL-2.0-or-later

use strict;
use warnings;

use base qw(Slim::Web::Settings);

use Slim::Utils::Log;
use Slim::Utils::Prefs;

use Plugins::AppleMusic::API;
use Plugins::AppleMusic::Helper;

my $log   = logger('plugin.applemusic');
my $prefs = preferences('plugin.applemusic');

# prefs that require a helper restart / config rewrite when changed
my @HELPER_PREFS = qw(helperPort audioFormat ffmpegSource ffmpegPath
                      cdmClientId cdmPrivateKey cdmWvd helperBinary distRepo);

sub name { 'PLUGIN_APPLEMUSIC_NAME' }

sub page { 'plugins/AppleMusic/settings/basic.html' }

sub prefs {
	return ( $prefs, qw(helperUrl helperPort audioFormat cleanupTags
	                    ffmpegSource ffmpegPath cdmClientId cdmPrivateKey cdmWvd
	                    helperBinary distRepo) );
}

sub handler {
	my ( $class, $client, $params, $callback, @args ) = @_;

	# --- explicit actions -----------------------------------------------
	if ( $params->{helperAction} && $params->{helperAction} =~ /^(start|stop|restart)$/ ) {
		my $act = $1;
		Plugins::AppleMusic::Helper->$act;
		$params->{warning} .= "<strong>Helper: $act requested.</strong><br>";
	}
	elsif ( $params->{reloadCdm} ) {
		Plugins::AppleMusic::Helper->writeConfig;
		Plugins::AppleMusic::API->reloadCdm( sub {}, sub {} );
		$params->{warning} .= '<strong>Reloading helper config &amp; CDM&hellip;</strong><br>';
	}

	# --- will a save change something the helper cares about? ----------
	my $helperPrefsChanged = 0;
	if ( $params->{saveSettings} ) {
		for my $p (@HELPER_PREFS) {
			my $new = defined $params->{"pref_$p"} ? $params->{"pref_$p"} : '';
			$helperPrefsChanged++ if $new ne ($prefs->get($p) // '');
		}
		if ( $helperPrefsChanged && !$params->{helperAction} ) {
			$params->{warning} .= '<strong>Restarting helper with the new settings&hellip;</strong><br>';
		}
	}

	# populate the status panel from the live snapshot + local process state
	my ($health, $age) = Plugins::AppleMusic::API->cachedHealth;
	Plugins::AppleMusic::API->health( sub {}, sub {} );   # refresh for next view

	my $hstat = Plugins::AppleMusic::Helper->status;
	$params->{amProc}      = $hstat;
	$params->{amHelperUp}  = ($health && ref $health) ? 1 : 0;
	$params->{amHealth}    = $health if $health && ref $health;
	$params->{amHealthAge} = $age if defined $age;
	$params->{amAuthUrl}   = ($health && $health->{auth_url})
		|| ($prefs->get('helperUrl') . '/auth');
	$params->{amPlatform}  = Plugins::AppleMusic::Helper->platform;

	my $body = $class->SUPER::handler( $client, $params, $callback, @args );

	if ( $helperPrefsChanged && !$params->{helperAction} ) {
		Plugins::AppleMusic::Helper->writeConfig;
		Plugins::AppleMusic::Helper->restart;
	}

	return $body;
}

1;
