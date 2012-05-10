# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack, LLC
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Base test class for running non-stubbed tests (functional tests)

The FunctionalTest class contains helper methods for starting the API
and Registry server, grabbing the logs of each, cleaning up pidfiles,
and spinning down the servers.
"""

import datetime
import functools
import json
import os
import re
import shutil
import signal
import socket
import time
import unittest
import urlparse

from sqlalchemy import create_engine

from glance.common import utils
from glance.tests import utils as test_utils

execute, get_unused_port = test_utils.execute, test_utils.get_unused_port


def runs_sql(func):
    """
    Decorator for a test case method that ensures that the
    sql_connection setting is overridden to ensure a disk-based
    SQLite database so that arbitrary SQL statements can be
    executed out-of-process against the datastore...
    """
    @functools.wraps(func)
    def wrapped(*a, **kwargs):
        test_obj = a[0]
        orig_sql_connection = test_obj.registry_server.sql_connection
        try:
            if orig_sql_connection.startswith('sqlite'):
                test_obj.registry_server.sql_connection =\
                        "sqlite:///tests.sqlite"
            func(*a, **kwargs)
        finally:
            test_obj.registry_server.sql_connection = orig_sql_connection
    return wrapped


class Server(object):
    """
    Class used to easily manage starting and stopping
    a server during functional test runs.
    """
    def __init__(self, test_dir, port):
        """
        Creates a new Server object.

        :param test_dir: The directory where all test stuff is kept. This is
                         passed from the FunctionalTestCase.
        :param port: The port to start a server up on.
        """
        self.verbose = True
        self.debug = True
        self.no_venv = False
        self.test_dir = test_dir
        self.bind_port = port
        self.conf_file_name = None
        self.conf_base = None
        self.paste_conf_base = None
        self.server_control = './bin/glance-control'
        self.exec_env = None
        self.deployment_flavor = ''
        self.server_control_options = ''

    def write_conf(self, **kwargs):
        """
        Writes the configuration file for the server to its intended
        destination.  Returns the name of the configuration file and
        the over-ridden config content (may be useful for populating
        error messages).
        """

        if self.conf_file_name:
            return self.conf_file_name
        if not self.conf_base:
            raise RuntimeError("Subclass did not populate config_base!")

        conf_override = self.__dict__.copy()
        if kwargs:
            conf_override.update(**kwargs)

        # A config file and paste.ini to use just for this test...we don't want
        # to trample on currently-running Glance servers, now do we?

        conf_dir = os.path.join(self.test_dir, 'etc')
        conf_filepath = os.path.join(conf_dir, "%s.conf" % self.server_name)
        paste_conf_filepath = conf_filepath.replace(".conf", "-paste.ini")
        utils.safe_mkdirs(conf_dir)

        def override_conf(filepath, overridden):
            with open(filepath, 'wb') as conf_file:
                conf_file.write(overridden)
                conf_file.flush()
                return conf_file.name

        overridden_core = self.conf_base % conf_override
        self.conf_file_name = override_conf(conf_filepath, overridden_core)

        overridden_paste = ''
        if self.paste_conf_base:
            overridden_paste = self.paste_conf_base % conf_override
            override_conf(paste_conf_filepath, overridden_paste)

        overridden = ('==Core config==\n%s\n==Paste config==\n%s' %
                      (overridden_core, overridden_paste))

        return self.conf_file_name, overridden

    def start(self, expect_exit=True, expected_exitcode=0, **kwargs):
        """
        Starts the server.

        Any kwargs passed to this method will override the configuration
        value in the conf file used in starting the servers.
        """

        # Ensure the configuration file is written
        overridden = self.write_conf(**kwargs)[1]

        cmd = ("%(server_control)s %(server_name)s start "
               "%(conf_file_name)s --pid-file=%(pid_file)s "
               "%(server_control_options)s"
               % self.__dict__)
        return execute(cmd,
                       no_venv=self.no_venv,
                       exec_env=self.exec_env,
                       expect_exit=expect_exit,
                       expected_exitcode=expected_exitcode,
                       context=overridden)

    def stop(self):
        """
        Spin down the server.
        """
        cmd = ("%(server_control)s %(server_name)s stop "
               "%(conf_file_name)s --pid-file=%(pid_file)s"
               % self.__dict__)
        return execute(cmd, no_venv=self.no_venv, exec_env=self.exec_env,
                       expect_exit=True)


class ApiServer(Server):

    """
    Server object that starts/stops/manages the API server
    """

    def __init__(self, test_dir, port, registry_port, policy_file,
            delayed_delete=False):
        super(ApiServer, self).__init__(test_dir, port)
        self.server_name = 'api'
        self.default_store = 'file'
        self.key_file = ""
        self.cert_file = ""
        self.metadata_encryption_key = "012345678901234567890123456789ab"
        self.image_dir = os.path.join(self.test_dir,
                                         "images")
        self.pid_file = os.path.join(self.test_dir,
                                         "api.pid")
        self.scrubber_datadir = os.path.join(self.test_dir,
                                             "scrubber")
        self.log_file = os.path.join(self.test_dir, "api.log")
        self.registry_port = registry_port
        self.s3_store_host = "s3.amazonaws.com"
        self.s3_store_access_key = ""
        self.s3_store_secret_key = ""
        self.s3_store_bucket = ""
        self.swift_store_auth_address = ""
        self.swift_store_user = ""
        self.swift_store_key = ""
        self.swift_store_container = ""
        self.swift_store_large_object_size = 5 * 1024
        self.swift_store_large_object_chunk_size = 200
        self.rbd_store_ceph_conf = ""
        self.rbd_store_pool = ""
        self.rbd_store_user = ""
        self.rbd_store_chunk_size = 4
        self.delayed_delete = delayed_delete
        self.owner_is_tenant = True
        self.workers = 0
        self.image_cache_dir = os.path.join(self.test_dir,
                                            'cache')
        self.image_cache_driver = 'sqlite'
        self.policy_file = policy_file
        self.policy_default_rule = 'default'
        self.server_control_options = '--capture-output'
        self.conf_base = """[DEFAULT]
verbose = %(verbose)s
debug = %(debug)s
filesystem_store_datadir=%(image_dir)s
default_store = %(default_store)s
bind_host = 0.0.0.0
bind_port = %(bind_port)s
key_file = %(key_file)s
cert_file = %(cert_file)s
metadata_encryption_key = %(metadata_encryption_key)s
registry_host = 0.0.0.0
registry_port = %(registry_port)s
log_file = %(log_file)s
s3_store_host = %(s3_store_host)s
s3_store_access_key = %(s3_store_access_key)s
s3_store_secret_key = %(s3_store_secret_key)s
s3_store_bucket = %(s3_store_bucket)s
swift_store_auth_address = %(swift_store_auth_address)s
swift_store_user = %(swift_store_user)s
swift_store_key = %(swift_store_key)s
swift_store_container = %(swift_store_container)s
swift_store_large_object_size = %(swift_store_large_object_size)s
swift_store_large_object_chunk_size = %(swift_store_large_object_chunk_size)s
rbd_store_chunk_size = %(rbd_store_chunk_size)s
rbd_store_user = %(rbd_store_user)s
rbd_store_pool = %(rbd_store_pool)s
rbd_store_ceph_conf = %(rbd_store_ceph_conf)s
delayed_delete = %(delayed_delete)s
owner_is_tenant = %(owner_is_tenant)s
workers = %(workers)s
scrub_time = 5
scrubber_datadir = %(scrubber_datadir)s
image_cache_dir = %(image_cache_dir)s
image_cache_driver = %(image_cache_driver)s
policy_file = %(policy_file)s
policy_default_rule = %(policy_default_rule)s
[paste_deploy]
flavor = %(deployment_flavor)s
"""
        self.paste_conf_base = """[pipeline:glance-api]
pipeline = versionnegotiation context apiv1app

[pipeline:glance-api-caching]
pipeline = versionnegotiation context cache apiv1app

[pipeline:glance-api-cachemanagement]
pipeline = versionnegotiation context cache cache_manage apiv1app

[pipeline:glance-api-fakeauth]
pipeline = versionnegotiation fakeauth context apiv1app

[app:apiv1app]
paste.app_factory = glance.common.wsgi:app_factory
glance.app_factory = glance.api.v1.router:API

[filter:versionnegotiation]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory =
 glance.api.middleware.version_negotiation:VersionNegotiationFilter

[filter:cache]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.api.middleware.cache:CacheFilter

[filter:cache_manage]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.api.middleware.cache_manage:CacheManageFilter

[filter:context]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.common.context:ContextMiddleware

[filter:fakeauth]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.tests.utils:FakeAuthMiddleware
"""


class RegistryServer(Server):

    """
    Server object that starts/stops/manages the Registry server
    """

    def __init__(self, test_dir, port):
        super(RegistryServer, self).__init__(test_dir, port)
        self.server_name = 'registry'

        default_sql_connection = 'sqlite:///'
        self.sql_connection = os.environ.get('GLANCE_TEST_SQL_CONNECTION',
                                             default_sql_connection)

        self.pid_file = os.path.join(self.test_dir,
                                         "registry.pid")
        self.log_file = os.path.join(self.test_dir, "registry.log")
        self.owner_is_tenant = True
        self.server_control_options = '--capture-output'
        self.conf_base = """[DEFAULT]
verbose = %(verbose)s
debug = %(debug)s
bind_host = 0.0.0.0
bind_port = %(bind_port)s
log_file = %(log_file)s
sql_connection = %(sql_connection)s
sql_idle_timeout = 3600
api_limit_max = 1000
limit_param_default = 25
owner_is_tenant = %(owner_is_tenant)s
[paste_deploy]
flavor = %(deployment_flavor)s
"""
        self.paste_conf_base = """[pipeline:glance-registry]
pipeline = context registryapp

[pipeline:glance-registry-fakeauth]
pipeline = fakeauth context registryapp

[app:registryapp]
paste.app_factory = glance.common.wsgi:app_factory
glance.app_factory = glance.registry.api.v1:API

[filter:context]
context_class = glance.registry.context.RequestContext
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.common.context:ContextMiddleware

[filter:fakeauth]
paste.filter_factory = glance.common.wsgi:filter_factory
glance.filter_factory = glance.tests.utils:FakeAuthMiddleware
"""


class ScrubberDaemon(Server):
    """
    Server object that starts/stops/manages the Scrubber server
    """

    def __init__(self, test_dir, registry_port, daemon=False):
        # NOTE(jkoelker): Set the port to 0 since we actually don't listen
        super(ScrubberDaemon, self).__init__(test_dir, 0)
        self.server_name = 'scrubber'
        self.daemon = daemon

        self.registry_port = registry_port
        self.scrubber_datadir = os.path.join(self.test_dir,
                                             "scrubber")
        self.pid_file = os.path.join(self.test_dir, "scrubber.pid")
        self.log_file = os.path.join(self.test_dir, "scrubber.log")
        self.conf_base = """[DEFAULT]
verbose = %(verbose)s
debug = %(debug)s
log_file = %(log_file)s
daemon = %(daemon)s
wakeup_time = 2
scrubber_datadir = %(scrubber_datadir)s
registry_host = 0.0.0.0
registry_port = %(registry_port)s
"""
        self.paste_conf_base = """[app:glance-scrubber]
paste.app_factory = glance.common.wsgi:app_factory
glance.app_factory = glance.store.scrubber:Scrubber
"""


class FunctionalTest(unittest.TestCase):

    """
    Base test class for any test that wants to test the actual
    servers and clients and not just the stubbed out interfaces
    """

    inited = False
    disabled = False
    log_files = []

    def setUp(self):
        self.test_id, self.test_dir = test_utils.get_isolated_test_env()

        self.api_protocol = 'http'
        self.api_port = get_unused_port()
        self.registry_port = get_unused_port()

        self.copy_data_file('policy.json', self.test_dir)
        self.policy_file = os.path.join(self.test_dir, 'policy.json')

        self.api_server = ApiServer(self.test_dir,
                                    self.api_port,
                                    self.registry_port,
                                    self.policy_file)
        self.registry_server = RegistryServer(self.test_dir,
                                              self.registry_port)

        self.scrubber_daemon = ScrubberDaemon(self.test_dir,
                                              self.registry_port)

        self.pid_files = [self.api_server.pid_file,
                          self.registry_server.pid_file,
                          self.scrubber_daemon.pid_file]
        self.files_to_destroy = []
        self.log_files = []

    def tearDown(self):
        if not self.disabled:
            self.cleanup()
            # We destroy the test data store between each test case,
            # and recreate it, which ensures that we have no side-effects
            # from the tests
            self._reset_database(self.registry_server.sql_connection)

    def set_policy_rules(self, rules):
        fap = open(self.policy_file, 'w')
        fap.write(json.dumps(rules))
        fap.close()

    def _reset_database(self, conn_string):
        conn_pieces = urlparse.urlparse(conn_string)
        if conn_string.startswith('sqlite'):
            # We can just delete the SQLite database, which is
            # the easiest and cleanest solution
            db_path = conn_pieces.path.strip('/')
            if db_path and os.path.exists(db_path):
                os.unlink(db_path)
            # No need to recreate the SQLite DB. SQLite will
            # create it for us if it's not there...
        elif conn_string.startswith('mysql'):
            # We can execute the MySQL client to destroy and re-create
            # the MYSQL database, which is easier and less error-prone
            # than using SQLAlchemy to do this via MetaData...trust me.
            database = conn_pieces.path.strip('/')
            loc_pieces = conn_pieces.netloc.split('@')
            host = loc_pieces[1]
            auth_pieces = loc_pieces[0].split(':')
            user = auth_pieces[0]
            password = ""
            if len(auth_pieces) > 1:
                if auth_pieces[1].strip():
                    password = "-p%s" % auth_pieces[1]
            sql = ("drop database if exists %(database)s; "
                   "create database %(database)s;") % locals()
            cmd = ("mysql -u%(user)s %(password)s -h%(host)s "
                   "-e\"%(sql)s\"") % locals()
            exitcode, out, err = execute(cmd)
            self.assertEqual(0, exitcode)

    def cleanup(self):
        """
        Makes sure anything we created or started up in the
        tests are destroyed or spun down
        """

        for pid_file in self.pid_files:
            if os.path.exists(pid_file):
                pid = int(open(pid_file).read().strip())
                try:
                    os.killpg(pid, signal.SIGTERM)
                except:
                    pass  # Ignore if the process group is dead
                os.unlink(pid_file)

        for f in self.files_to_destroy:
            if os.path.exists(f):
                os.unlink(f)

    def start_server(self,
                     server,
                     expect_launch,
                     expect_exit=True,
                     expected_exitcode=0,
                     **kwargs):
        """
        Starts a server on an unused port.

        Any kwargs passed to this method will override the configuration
        value in the conf file used in starting the server.

        :param server: the server to launch
        :param expect_launch: true iff the server is expected to
                              successfully start
        :param expect_exit: true iff the launched server is expected
                            to exit in a timely fashion
        :param expected_exitcode: expected exitcode from the launcher
        """
        self.cleanup()

        # Start up the requested server
        exitcode, out, err = server.start(expect_exit=expect_exit,
                                          expected_exitcode=expected_exitcode,
                                          **kwargs)
        if expect_exit:
            self.assertEqual(expected_exitcode, exitcode,
                             "Failed to spin up the requested server. "
                             "Got: %s" % err)

            self.assertTrue(re.search("Starting glance-[a-z]+ with", out))

        self.log_files.append(server.log_file)

        self.wait_for_servers([server.bind_port], expect_launch)

    def start_servers(self, **kwargs):
        """
        Starts the API and Registry servers (bin/glance-control api start
        & bin/glance-control registry start) on unused ports.

        Any kwargs passed to this method will override the configuration
        value in the conf file used in starting the servers.
        """
        self.cleanup()

        # Start up the API and default registry server
        exitcode, out, err = self.api_server.start(**kwargs)

        self.log_files.append(self.api_server.log_file)

        self.assertEqual(0, exitcode,
                         "Failed to spin up the API server. "
                         "Got: %s" % err)
        self.assertTrue("Starting glance-api with" in out)

        exitcode, out, err = self.registry_server.start(**kwargs)

        self.log_files.append(self.registry_server.log_file)

        self.assertEqual(0, exitcode,
                         "Failed to spin up the Registry server. "
                         "Got: %s" % err)
        self.assertTrue("Starting glance-registry with" in out)

        exitcode, out, err = self.scrubber_daemon.start(**kwargs)

        self.assertEqual(0, exitcode,
                         "Failed to spin up the Scrubber daemon. "
                         "Got: %s" % err)
        self.assertTrue("Starting glance-scrubber with" in out)

        self.wait_for_servers([self.api_port, self.registry_port])

    def ping_server(self, port):
        """
        Simple ping on the port. If responsive, return True, else
        return False.

        :note We use raw sockets, not ping here, since ping uses ICMP and
        has no concept of ports...
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except socket.error, e:
            return False

    def wait_for_servers(self, ports, expect_launch=True, timeout=3):
        """
        Tight loop, waiting for the given server port(s) to be available.
        Returns when all are pingable. There is a timeout on waiting
        for the servers to come up.

        :param ports: Glance server ports to ping
        :param expect_launch: Optional, true iff the server(s) are
                              expected to successfully start
        :param timeout: Optional, defaults to 3 seconds
        """
        now = datetime.datetime.now()
        timeout_time = now + datetime.timedelta(seconds=timeout)
        while (timeout_time > now):
            pinged = 0
            for port in ports:
                if self.ping_server(port):
                    pinged += 1
            if pinged == len(ports):
                self.assertTrue(expect_launch,
                                "Unexpected server launch status")
                return
            now = datetime.datetime.now()
            time.sleep(0.05)
        self.assertFalse(expect_launch, "Unexpected server launch status")

    def stop_server(self, server, name):
        """
        Called to stop a single server in a normal fashion using the
        glance-control stop method to gracefully shut the server down.

        :param server: the server to stop
        """
        # Spin down the requested server
        exitcode, out, err = server.stop()
        self.assertEqual(0, exitcode,
                         "Failed to spin down the %s server. Got: %s" %
                         (err, name))

    def stop_servers(self):
        """
        Called to stop the started servers in a normal fashion. Note
        that cleanup() will stop the servers using a fairly draconian
        method of sending a SIGTERM signal to the servers. Here, we use
        the glance-control stop method to gracefully shut the server down.
        This method also asserts that the shutdown was clean, and so it
        is meant to be called during a normal test case sequence.
        """

        # Spin down the API and default registry server
        self.stop_server(self.api_server, 'API server')
        self.stop_server(self.registry_server, 'Registry server')
        self.stop_server(self.scrubber_daemon, 'Scrubber daemon')

        # If all went well, then just remove the test directory.
        # We only want to check the logs and stuff if something
        # went wrong...
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

        # We do this here because the @runs_sql decorator above
        # actually resets the registry server's sql_connection
        # to the original (usually memory-based SQLite connection)
        # and this block of code is run *before* the finally:
        # block in that decorator...
        self._reset_database(self.registry_server.sql_connection)

    def run_sql_cmd(self, sql):
        """
        Provides a crude mechanism to run manual SQL commands for backend
        DB verification within the functional tests.
        The raw result set is returned.
        """
        engine = create_engine(self.registry_server.sql_connection,
                               pool_recycle=30)
        return engine.execute(sql)

    def copy_data_file(self, file_name, dst_dir):
        src_file_name = os.path.join('glance/tests/etc', file_name)
        shutil.copy(src_file_name, dst_dir)
        dst_file_name = os.path.join(dst_dir, file_name)
        return dst_file_name

    def dump_logs(self):
        dump = ''
        for log in self.log_files:
            dump += '\nContent of %s:\n\n' % log
            if os.path.exists(log):
                f = open(log, 'r')
                for line in f:
                    dump += line
            else:
                dump += '<empty>'
        return dump
