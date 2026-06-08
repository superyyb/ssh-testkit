#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP;

# parse_log.pl
# Parses device and application log files.
# Auto-detects log type. Supports human-readable and JSON output.
#
# Usage:
#   perl parse_log.pl <log_file>           # human-readable output
#   perl parse_log.pl <log_file> --json    # JSON output for Python pipeline
#
# Exit code: 0 = PASS, 1 = FAIL

my $log_file  = $ARGV[0] or die "Usage: perl parse_log.pl <log_file> [--json]\n";
my $json_mode = grep { $_ eq '--json' } @ARGV;

open(my $fh, '<', $log_file) or die "Cannot open $log_file: $!\n";

# ── Counters and collectors ────────────────────────────────────────────────
my $pass_count      = 0;
my $fail_count      = 0;
my $total_lines     = 0;
my %level_counts    = (INFO => 0, WARN => 0, ERROR => 0, FATAL => 0, DEBUG => 0);
my @errors;
my @failures;
my %error_frequency;
my $log_type        = "unknown";
my $first_timestamp = "";
my $last_timestamp  = "";

# ── Parse log line by line ─────────────────────────────────────────────────
while (my $line = <$fh>) {
    chomp $line;
    $total_lines++;
    next if $line =~ /^\s*$/;

    # Extract timestamp
    if ($line =~ /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/) {
        $first_timestamp = $1 unless $first_timestamp;
        $last_timestamp  = $1;
    }

    # Count log levels
    if ($line =~ /\[(INFO|WARN(?:ING)?|ERROR|FATAL|DEBUG)\]/i) {
        my $level = uc($1);
        $level = "WARN" if $level eq "WARNING";
        $level_counts{$level}++ if exists $level_counts{$level};
    }

    # Device log markers
    if ($line =~ /TEST_PASS/i) { $pass_count++; $log_type = "device"; }
    if ($line =~ /TEST_FAIL/i) {
        $fail_count++;
        push @failures, $line;
        $log_type = "device";
    }

    # App log markers
    if ($line =~ /startup complete|application starting|uvicorn running/i) {
        $log_type = "app";
    }

    # Collect ERROR / FATAL lines
    if ($line =~ /\b(ERROR|FATAL)\b/i) {
        push @errors, $line;
        if ($line =~ /\b(?:ERROR|FATAL)\b[:\s]+(.+)$/i) {
            my $msg = $1;
            $msg =~ s/\s+$//;
            $error_frequency{$msg}++;
        }
    }
}

close($fh);

# ── Determine result ───────────────────────────────────────────────────────
my $result = ($fail_count == 0 && scalar(@errors) == 0) ? "PASS" : "FAIL";

# ── Repeated errors ────────────────────────────────────────────────────────
my @repeated = map  { { message => $_, count => $error_frequency{$_} } }
               grep { $error_frequency{$_} > 1 }
               keys %error_frequency;

# ── JSON output (for Python pipeline) ─────────────────────────────────────
if ($json_mode) {
    my %data = (
        file            => $log_file,
        type            => $log_type,
        total_lines     => $total_lines,
        time_range      => { start => $first_timestamp, end => $last_timestamp },
        levels          => \%level_counts,
        pass_count      => $pass_count,
        fail_count      => $fail_count,
        errors          => \@errors,
        failures        => \@failures,
        repeated_errors => \@repeated,
        result          => $result,
    );
    print JSON::PP->new->pretty->canonical->encode(\%data);
    exit ($result eq "PASS" ? 0 : 1);
}

# ── Human-readable output ──────────────────────────────────────────────────
print "=" x 50 . "\n";
print "Log Analysis Summary\n";
print "=" x 50 . "\n";
printf "File:        %s\n", $log_file;
printf "Type:        %s\n", $log_type;
printf "Total lines: %d\n", $total_lines;
printf "Time range:  %s  ->  %s\n", $first_timestamp, $last_timestamp
    if $first_timestamp;
print "-" x 50 . "\n";

print "Log levels:\n";
for my $level (qw(INFO WARN ERROR FATAL DEBUG)) {
    printf "  %-8s %d\n", "${level}:", $level_counts{$level}
        if $level_counts{$level} > 0;
}

if ($log_type eq "device") {
    print "-" x 50 . "\n";
    printf "TEST_PASS:   %d\n", $pass_count;
    printf "TEST_FAIL:   %d\n", $fail_count;
}

if (@failures) { print "\nFAILURES:\n"; print "  $_\n" for @failures; }
if (@errors)   { print "\nERRORS:\n";   print "  $_\n" for @errors;   }

if (@repeated) {
    print "\nREPEATED ERRORS:\n";
    printf "  (%dx) %s\n", $_->{count}, $_->{message} for @repeated;
}

print "=" x 50 . "\n";
print "Result: $result\n";
exit ($result eq "PASS" ? 0 : 1);
