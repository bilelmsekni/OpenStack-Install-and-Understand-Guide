===============
glance-scrubber
===============

--------------------
Glance scrub service
--------------------

:Author: glance@lists.launchpad.net
:Date:   2012-01-03
:Copyright: OpenStack LLC
:Version: 2012.1-dev
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  glance-scrubber [options]

DESCRIPTION
===========

glance-scrubber is an utility that cleans up images that have been deleted. The
mechanics of this differ depending on the backend store and pending_deletion
options chosen.

Multiple glance-scrubbers can be run in a single deployment, but only one of
them may be designated as the 'cleanup_scrubber' in the glance-scrubber.conf
file. The 'cleanup_scrubber' coordinates other glance-scrubbers by maintaining
the master queue of images that need to be removed.

The glance-scubber.conf file also specifies important configuration items such
as the time between runs ('wakeup_time' in seconds), length of time images
can be pending before their deletion ('cleanup_scrubber_time' in seconds) as
well as registry connectivity options.

glance-scrubber can run as a periodic job or long-running daemon.

OPTIONS
=======

  **--version**
        show program's version number and exit

  **-h, --help**
        show this help message and exit

  **--config-file=PATH**
        Path to a config file to use. Multiple config files can be specified,
        with values in later files taking precedence.
        The default files used are: []

  **-d, --debug**
        Print debugging output

  **--nodebug**
        Do not print debugging output

  **-v, --verbose**
        Print more verbose output

  **--noverbose**
        Do not print verbose output

  **--log-config=PATH**
        If this option is specified, the logging configuration
        file specified is used and overrides any other logging
        options specified. Please see the Python logging
        module documentation for details on logging
        configuration files.

  **--log-format=FORMAT**
        A logging.Formatter log message format string which
        may use any of the available logging.LogRecord
        attributes.
        Default: none

  **--log-date-format=DATE_FORMAT**
        Format string for %(asctime)s in log records. Default: none

  **--log-file=PATH**
        (Optional) Name of log file to output to. If not set,
        logging will go to stdout.

  **--log-dir=LOG_DIR**
        (Optional) The directory to keep log files in (will be
        prepended to --logfile)

  **--use-syslog**
        Use syslog for logging.

  **--nouse-syslog**
        Do not use syslog for logging.

  **--syslog-log-facility=SYSLOG_LOG_FACILITY**
        syslog facility to receive log lines

  **-D, --daemon**
        Run as a long-running process. When not specified (the
        default) run the scrub operation once and then exits.
        When specified do not exit and run scrub on
        wakeup_time interval as specified in the config.

  **--nodaemon**
        The inverse of --daemon. Runs the scrub operation once and then exits.

SEE ALSO
========

* `OpenStack Glance <http://glance.openstack.org>`__

BUGS
====

* Glance is sourced in Launchpad so you can view current bugs at `OpenStack Glance <http://glance.openstack.org>`__
