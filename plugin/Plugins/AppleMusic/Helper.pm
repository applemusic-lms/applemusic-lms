package Plugins::AppleMusic::Helper;

# SPDX-License-Identifier: GPL-2.0-or-later
#
# Owns the applemusic-helper process: locates/downloads the per-platform binary,
# writes its config.json from plugin prefs, starts it under Proc::Background,
# and keeps it alive. Model: Plugins::Spotty::Helper + RaopBridge::Squeeze2raop.

use strict;
use warnings;

use Digest::SHA qw(sha256_hex);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Spec::Functions qw(catdir catfile);
use JSON::XS;
use Proc::Background;

my $JSON = JSON::XS->new->utf8->canonical->pretty;

use Slim::Networking::SimpleAsyncHTTP;
use Slim::Utils::Log;
use Slim::Utils::OSDetect;
use Slim::Utils::Prefs;
use Slim::Utils::Timers;

my $log   = logger('plugin.applemusic');
my $prefs = preferences('plugin.applemusic');

# where releases live; override with the `distRepo` pref if you fork
use constant DEFAULT_REPO => 'applemusic-lms/applemusic-lms';
use constant BEAT_INTERVAL => 30;

my $proc;          # Proc::Background
my $port;
my $helperVersion;
my $wantRunning = 0;
my $downloading = 0;
my $lastError;

# ------------------------------------------------------------------ paths
sub dataDir {
	my $d = catdir(Slim::Utils::OSDetect::dirsFor('cache'), 'applemusic-helper');
	make_path($d) unless -d $d;
	return $d;
}

sub configFile { catfile(dataDir(), 'config.json') }
sub logFile    { catfile(dataDir(), 'helper.log') }
sub binDir     { catdir(dataDir(), 'bin') }

sub platform {
	return 'win-x64'        if main::ISWINDOWS;
	my $arch = Slim::Utils::OSDetect::details()->{osArch} || '';
	if (main::ISMAC) {
		return $arch =~ /arm|aarch64/i ? 'darwin-arm64' : 'darwin-x86_64';
	}
	return 'aarch64-linux' if $arch =~ /aarch64|arm64/i;
	return 'arm-linux'     if $arch =~ /arm/i;
	return 'x86_64-linux';                       # default / x86_64 / i686-with-32bit-python
}

sub _repo { $prefs->get('distRepo') || DEFAULT_REPO }
sub _version { Plugins::AppleMusic::Plugin->_pluginDataFor('version') || '0.0.0' }
sub distBaseUrl {
	sprintf('https://github.com/%s/releases/download/v%s', _repo(), _version());
}

# a custom command wins (dev: "python3 -m applemusic_helper")
sub _binArgv {
	if (my $custom = $prefs->get('helperBinary')) {
		return grep { length } split(/\s+/, $custom);
	}
	my $name = main::ISWINDOWS ? 'applemusic-helper.exe' : 'applemusic-helper';
	return (catfile(binDir(), $name));
}

# ------------------------------------------------------------------ status
sub status {
	return {
		running     => ($proc && $proc->alive) ? 1 : 0,
		downloading => $downloading,
		version     => $helperVersion,
		port        => $port,
		error       => $lastError,
		binary      => (_binArgv())[-1],
	};
}

# ------------------------------------------------------------------ lifecycle
sub init {
	my $class = shift;
	$wantRunning = 1;
	$class->writeConfig;
	$class->ensureBinary(sub {
		$class->start;
	});
	Slim::Utils::Timers::setTimer($class, time() + BEAT_INTERVAL, \&_beat);
}

sub shutdown {
	my $class = shift;
	$wantRunning = 0;
	Slim::Utils::Timers::killTimers($class, \&_beat);
	$class->stop;
}

sub _beat {
	my $class = shift;
	Slim::Utils::Timers::killTimers($class, \&_beat);

	if ($wantRunning && !$downloading && !($proc && $proc->alive)) {
		$log->warn('helper not running - (re)starting');
		$class->ensureBinary(sub { $class->start });
	}

	# keep the settings page /health snapshot warm
	eval { Plugins::AppleMusic::API->health(sub {}, sub {}) };

	Slim::Utils::Timers::setTimer($class, time() + BEAT_INTERVAL, \&_beat);
}

sub start {
	my $class = shift;
	return if $proc && $proc->alive;

	my @argv = _binArgv();
	if (!$prefs->get('helperBinary') && !-x $argv[0]) {
		$lastError = "helper binary missing: $argv[0]";
		$log->error($lastError);
		return;
	}

	$class->writeConfig;
	$port = $prefs->get('helperPort') || 9863;

	my @cmd = (@argv,
		'--config',   configFile(),
		'--host',     '127.0.0.1',
		'--port',     $port,
		'--dist-url', distBaseUrl(),
	);

	main::INFOLOG && $log->is_info && $log->info('starting helper: ' . join(' ', @cmd));
	eval { $proc = Proc::Background->new({ die_upon_destroy => 1 }, @cmd) };
	if ($@ || !$proc) {
		$lastError = "could not start helper: $@";
		$log->error($lastError);
		return;
	}
	$lastError = undef;

	# the API client talks to whatever helperUrl points at
	$prefs->set('helperUrl', "http://127.0.0.1:$port");

	Slim::Utils::Timers::setTimer($class, time() + 2, sub {
		$class->_probeVersion;
	});
}

sub stop {
	my $class = shift;
	if ($proc && $proc->alive) {
		main::INFOLOG && $log->is_info && $log->info('stopping helper');
		$proc->die;
	}
	$proc = undef;
}

sub restart {
	my $class = shift;
	$wantRunning = 1;
	$class->stop;
	$class->ensureBinary(sub { $class->start });
}

sub _probeVersion {
	my $class = shift;
	my @argv  = _binArgv();
	my $out   = `"$argv[0]" @argv[1..$#argv] --selftest 2>&1`;
	if ($out =~ /^ok applemusic-helper v(\S+)/m) {
		$helperVersion = $1;
		main::INFOLOG && $log->is_info && $log->info("helper selftest ok: v$helperVersion");
	}
	else {
		$log->warn("helper selftest: $out");
	}
}

# ------------------------------------------------------------------ config.json
sub writeConfig {
	my $class = shift;

	my $file = configFile();
	my $cfg  = {};
	if (-r $file && open(my $rfh, '<:raw', $file)) {
		local $/;
		my $raw = <$rfh>;
		close $rfh;
		$cfg = eval { $JSON->decode($raw) } || {};
		$cfg = {} unless ref $cfg eq 'HASH';
	}

	# plugin owns these; helper owns media_user_token / developer_token* / storefront
	$cfg->{bind_host}     = '127.0.0.1';
	$cfg->{bind_port}     = $prefs->get('helperPort') || 9863;
	$cfg->{audio_format}  = ($prefs->get('audioFormat') || 'flac') eq 'aac' ? 'aac' : 'flac';
	$cfg->{ffmpeg_source} = $prefs->get('ffmpegSource') || 'auto';
	$cfg->{ffmpeg_path}   = $prefs->get('ffmpegSource') eq 'custom' ? ($prefs->get('ffmpegPath') || '') : '';
	$cfg->{log_file}      = logFile();
	$cfg->{cdm_client_id_path}   = $prefs->get('cdmClientId')   || '';
	$cfg->{cdm_private_key_path} = $prefs->get('cdmPrivateKey') || '';
	$cfg->{cdm_wvd_path}         = $prefs->get('cdmWvd')        || '';

	make_path(dataDir()) unless -d dataDir();
	my $tmp = "$file.tmp$$";
	open(my $fh, '>:raw', $tmp) or do { $log->error("write $tmp: $!"); return; };
	print $fh $JSON->encode($cfg);
	close $fh;
	rename($tmp, $file) or $log->error("rename $tmp -> $file: $!");
}

# ------------------------------------------------------------------ binary download
sub _stampFile { catfile(binDir(), '.version') }

sub _stampMatches {
	my $want = _version();
	open(my $fh, '<', _stampFile()) or return 0;
	local $/; my $have = <$fh>; close $fh;
	$have =~ s/\s+//g;
	return $have eq $want;
}

sub ensureBinary {
	my ($class, $cb) = @_;
	$cb ||= sub {};

	# dev override: caller manages the binary
	if ($prefs->get('helperBinary')) {
		return $cb->(1);
	}
	my $bin = (_binArgv())[0];

	# present AND downloaded for this plugin version -> nothing to do
	if (-x $bin && _stampMatches()) {
		return $cb->(1);
	}
	if ($downloading) {
		return $cb->(0);
	}
	$log->info('helper binary missing or from a previous version - fetching v' . _version());

	my $plat = platform();
	my $name = main::ISWINDOWS ? "applemusic-helper-$plat.exe" : "applemusic-helper-$plat";
	my $url  = distBaseUrl() . "/$name";

	$downloading = 1;
	$lastError = undef;
	$log->warn("downloading helper for $plat from $url");

	# fetch the checksum manifest first (best-effort), then the binary
	Slim::Networking::SimpleAsyncHTTP->new(
		sub {
			my $sums = $_[0]->content || '';
			my $want;
			for my $line (split /\n/, $sums) {
				my ($h, $n) = $line =~ /^(\S+)\s+\*?(\S+)$/ or next;
				$want = $h if $n eq $name;
			}
			_downloadBinary($class, $url, $bin, $want, $cb);
		},
		sub { _downloadBinary($class, $url, $bin, undef, $cb) },
		{ timeout => 30 },
	)->get(distBaseUrl() . '/sha256sums.txt');
}

sub _downloadBinary {
	my ($class, $url, $bin, $wantSha, $cb) = @_;

	Slim::Networking::SimpleAsyncHTTP->new(
		sub {
			my $http = shift;
			$downloading = 0;
			my $body = $http->content;

			if ($wantSha && sha256_hex($body) ne $wantSha) {
				$lastError = "helper download checksum mismatch";
				$log->error($lastError);
				return $cb->(0);
			}

			make_path(binDir()) unless -d binDir();
			my $tmp = "$bin.tmp$$";
			if (open(my $fh, '>', $tmp)) {
				binmode $fh;
				print $fh $body;
				close $fh;
				chmod(0755, $tmp);
				rename($tmp, $bin);
				if (open(my $vfh, '>', _stampFile())) { print $vfh _version(); close $vfh; }
				$log->info("helper downloaded: $bin (" . length($body) . " bytes"
					. ($wantSha ? ", sha256 ok" : ", unverified") . ")");
				_dequarantine($bin);
				$cb->(1);
			}
			else {
				$lastError = "cannot write $tmp: $!";
				$log->error($lastError);
				$cb->(0);
			}
		},
		sub {
			my ($http, $error) = @_;
			$downloading = 0;
			$lastError = "helper download failed: " . ($error || 'unknown');
			$log->error("$lastError ($url)");
			$cb->(0);
		},
		{ timeout => 180 },
	)->get($url);
}

sub _dequarantine {
	my $path = shift;
	return unless main::ISMAC;
	system('xattr', '-dr', 'com.apple.quarantine', $path);
}

1;
