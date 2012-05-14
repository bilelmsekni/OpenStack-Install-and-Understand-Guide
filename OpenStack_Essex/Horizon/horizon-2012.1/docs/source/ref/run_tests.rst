===========================
The ``run_tests.sh`` Script
===========================

.. contents:: Contents:
   :local:

Horizon ships with a script called ``run_tests.sh`` at the root of the
repository. This script provides many crucial functions for the project,
and also makes several otherwise complex tasks trivial for you as a
developer.

First Run
=========

If you start with a clean copy of the Horizon repository, the first thing
you should do is to run ``./run_tests.sh`` from the root of the repository.
This will do two things for you:

    #. Set up a virtual environment for both the ``horizon`` module and
       the ``openstack-dashboard`` project using
       ``openstack-dashboard/tools/install_venv.py``.
    #. Run the tests for both ``horizon`` and ``openstack-dashboard`` using
       their respective environments and verify that evreything is working.

Setting up the environment the first time can take several minutes, but only
needs to be done once. If dependencies are added in the future, updating the
environments will be necessary but not as time consuming.

I just want to run the tests!
=============================

Running the full set of unit tests quickly and easily is the main goal of this
script. All you need to do is::

    ./run_tests.sh

Yep, that's it. However, for a quicker test run you can skip the Selenium
tests by using the ``--skip-selenium`` flag::

    ./run_tests.sh --skip-selenium

This isn't recommended, but can be a timesaver when you only need to run
the code tests and not the frontend tests during development.

Give me metrics!
================

You can generate various reports and metrics using command line arguments
to ``run_tests.sh``.

Coverage
--------

To run coverage reports::

    ./run_tests.sh --coverage

The reports are saved to ``./reports/`` and ``./coverage.xml``.

PEP8
----

You can check for PEP8 violations as well::

    ./run_tests.sh --pep8

The results are saved to ``./pep8.txt``.

PyLint
------

For more detailed code analysis you can run::

    ./run_tests.sh --pylint

The output will be saved in ``./pylint.txt``.

Tab Characters
--------------

For those who dislike having a mix of tab characters and spaces for indentation
there's a command to check for that in Python, CSS, JavaScript and HTML files::

    ./run_tests.sh --tabs

This will output a total "tab count" and a list of the offending files.

Running the development server
==============================

As an added bonus, you can run Django's development server directly from
the root of the repository with ``run_tests.sh`` like so::

    ./run_tests.sh --runserver

This is effectively just an alias for::

    ./openstack-dashboard/tools/with_venv.sh ./openstack-dashboard/dashboard/manage.py runserver

Generating the documentation
============================

You can build Horizon's documentation automatically by running::

    ./run_tests.sh --docs

The output is stored in ``./docs/build/html/``.

Updating the translation files
==============================

You can update all of the translation files for both the ``horizon`` app and
``openstack_dashboard`` project with a single command:

    ./run_tests.sh --makemessages

or, more compactly:

    ./run_tests.sh --m

Starting clean
==============

If you ever want to start clean with a new environment for Horizon, you can
run::

    ./run_tests.sh --force

That will blow away the existing environments and create new ones for you.

Non-interactive Mode
====================

There is an optional flag which will run the script in a non-interactive
(and eventually less verbose) mode::

    ./run_tests.sh --quiet

This will automatically take the default action for actions which would
normally prompt for user input such as installing/updating the environment.

Environment Backups
===================

To speed up the process of doing clean checkouts, running continuous
integration tests, etc. there are options for backing up the current
environment and restoring from a backup.

    ./run_tests.sh --restore-environment
    ./run_tests.sh --backup-environment

The environment backup is stored in ``/tmp/.horizon_environment/``.

Environment Versioning
======================

Horizon keeps track of changes to the environment by incrementing an
``environment_version`` integer at the top of ``run_tests.sh``.

If you do anything which changes the environment (adding new dependencies
or renaming directories are both great examples) be sure to increment the
``environment_version`` counter as well.
