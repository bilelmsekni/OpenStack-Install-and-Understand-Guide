# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Generic Node base class for all workers that run on hosts."""

import inspect
import os

import eventlet
import greenlet

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import rpc
from nova import utils
from nova import version
from nova import wsgi


LOG = logging.getLogger(__name__)

service_opts = [
    cfg.IntOpt('report_interval',
               default=10,
               help='seconds between nodes reporting state to datastore'),
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between running periodic tasks'),
    cfg.StrOpt('ec2_listen',
               default="0.0.0.0",
               help='IP address for EC2 API to listen'),
    cfg.IntOpt('ec2_listen_port',
               default=8773,
               help='port for ec2 api to listen'),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help='IP address for OpenStack API to listen'),
    cfg.IntOpt('osapi_compute_listen_port',
               default=8774,
               help='list port for osapi compute'),
    cfg.StrOpt('metadata_manager',
               default='nova.api.manager.MetadataManager',
               help='OpenStack metadata service manager'),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help='IP address for metadata api to listen'),
    cfg.IntOpt('metadata_listen_port',
               default=8775,
               help='port for metadata api to listen'),
    cfg.StrOpt('osapi_volume_listen',
               default="0.0.0.0",
               help='IP address for OpenStack Volume API to listen'),
    cfg.IntOpt('osapi_volume_listen_port',
               default=8776,
               help='port for os volume api to listen'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(service_opts)


class Launcher(object):
    """Launch one or more services and wait for them to complete."""

    def __init__(self):
        """Initialize the service launcher.

        :returns: None

        """
        self._services = []

    @staticmethod
    def run_server(server):
        """Start and wait for a server to finish.

        :param service: Server to run and wait for.
        :returns: None

        """
        server.start()
        server.wait()

    def launch_server(self, server):
        """Load and start the given server.

        :param server: The server you would like to start.
        :returns: None

        """
        gt = eventlet.spawn(self.run_server, server)
        self._services.append(gt)

    def stop(self):
        """Stop all services which are currently running.

        :returns: None

        """
        for service in self._services:
            service.kill()

    def wait(self):
        """Waits until all services have been stopped, and then returns.

        :returns: None

        """
        for service in self._services:
            try:
                service.wait()
            except greenlet.GreenletExit:
                pass


class Service(object):
    """Service object for binaries running on hosts.

    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    it state to the database services table."""

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        manager_class = utils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        super(Service, self).__init__(*args, **kwargs)
        self.saved_args, self.saved_kwargs = args, kwargs
        self.timers = []

    def start(self):
        vcs_string = version.version_string_with_vcs()
        LOG.audit(_('Starting %(topic)s node (version %(vcs_string)s)'),
                  {'topic': self.topic, 'vcs_string': vcs_string})
        utils.cleanup_file_locks()
        self.manager.init_host()
        self.model_disconnected = False
        ctxt = context.get_admin_context()
        try:
            service_ref = db.service_get_by_args(ctxt,
                                                 self.host,
                                                 self.binary)
            self.service_id = service_ref['id']
        except exception.NotFound:
            self._create_service_ref(ctxt)

        if 'nova-compute' == self.binary:
            self.manager.update_available_resource(ctxt)

        self.conn = rpc.create_connection(new=True)
        LOG.debug(_("Creating Consumer connection for Service %s") %
                  self.topic)

        # Share this same connection for these Consumers
        self.conn.create_consumer(self.topic, self, fanout=False)

        node_topic = '%s.%s' % (self.topic, self.host)
        self.conn.create_consumer(node_topic, self, fanout=False)

        self.conn.create_consumer(self.topic, self, fanout=True)

        # Consume from all consumers in a thread
        self.conn.consume_in_thread()

        if self.report_interval:
            pulse = utils.LoopingCall(self.report_state)
            pulse.start(interval=self.report_interval, now=False)
            self.timers.append(pulse)

        if self.periodic_interval:
            periodic = utils.LoopingCall(self.periodic_tasks)
            periodic.start(interval=self.periodic_interval, now=False)
            self.timers.append(periodic)

    def _create_service_ref(self, context):
        zone = FLAGS.node_availability_zone
        service_ref = db.service_create(context,
                                        {'host': self.host,
                                         'binary': self.binary,
                                         'topic': self.topic,
                                         'report_count': 0,
                                         'availability_zone': zone})
        self.service_id = service_ref['id']

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_interval=None):
        """Instantiates class and passes back application object.

        :param host: defaults to FLAGS.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to FLAGS.<topic>_manager
        :param report_interval: defaults to FLAGS.report_interval
        :param periodic_interval: defaults to FLAGS.periodic_interval

        """
        if not host:
            host = FLAGS.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition('nova-')[2]
        if not manager:
            manager = FLAGS.get('%s_manager' % topic, None)
        if not report_interval:
            report_interval = FLAGS.report_interval
        if not periodic_interval:
            periodic_interval = FLAGS.periodic_interval
        service_obj = cls(host, binary, topic, manager,
                          report_interval, periodic_interval)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore."""
        self.stop()
        try:
            db.service_destroy(context.get_admin_context(), self.service_id)
        except exception.NotFound:
            LOG.warn(_('Service killed that has no database entry'))

    def stop(self):
        # Try to shut the connection down, but if we get any sort of
        # errors, go ahead and ignore them.. as we're shutting down anyway
        try:
            self.conn.close()
        except Exception:
            pass
        for x in self.timers:
            try:
                x.stop()
            except Exception:
                pass
        self.timers = []

    def wait(self):
        for x in self.timers:
            try:
                x.wait()
            except Exception:
                pass

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)

    def report_state(self):
        """Update the state of this service in the datastore."""
        ctxt = context.get_admin_context()
        zone = FLAGS.node_availability_zone
        state_catalog = {}
        try:
            try:
                service_ref = db.service_get(ctxt, self.service_id)
            except exception.NotFound:
                LOG.debug(_('The service database object disappeared, '
                            'Recreating it.'))
                self._create_service_ref(ctxt)
                service_ref = db.service_get(ctxt, self.service_id)

            state_catalog['report_count'] = service_ref['report_count'] + 1
            if zone != service_ref['availability_zone']:
                state_catalog['availability_zone'] = zone

            db.service_update(ctxt,
                             self.service_id, state_catalog)

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, 'model_disconnected', False):
                self.model_disconnected = False
                LOG.error(_('Recovered model server connection!'))

        # TODO(vish): this should probably only catch connection errors
        except Exception:  # pylint: disable=W0702
            if not getattr(self, 'model_disconnected', False):
                self.model_disconnected = True
                LOG.exception(_('model server went away'))


class WSGIService(object):
    """Provides ability to launch API from a 'paste' configuration."""

    def __init__(self, name, loader=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param loader: Loads the WSGI application using the given name.
        :returns: None

        """
        self.name = name
        self.manager = self._get_manager()
        self.loader = loader or wsgi.Loader()
        self.app = self.loader.load_app(name)
        self.host = getattr(FLAGS, '%s_listen' % name, "0.0.0.0")
        self.port = getattr(FLAGS, '%s_listen_port' % name, 0)
        self.server = wsgi.Server(name,
                                  self.app,
                                  host=self.host,
                                  port=self.port)

    def _get_manager(self):
        """Initialize a Manager object appropriate for this service.

        Use the service name to look up a Manager subclass from the
        configuration and initialize an instance. If no class name
        is configured, just return None.

        :returns: a Manager instance, or None.

        """
        fl = '%s_manager' % self.name
        if not fl in FLAGS:
            return None

        manager_class_name = FLAGS.get(fl, None)
        if not manager_class_name:
            return None

        manager_class = utils.import_class(manager_class_name)
        return manager_class()

    def start(self):
        """Start serving this service using loaded configuration.

        Also, retrieve updated port number in case '0' was passed in, which
        indicates a random port should be used.

        :returns: None

        """
        utils.cleanup_file_locks()
        if self.manager:
            self.manager.init_host()
        self.server.start()
        self.port = self.server.port

    def stop(self):
        """Stop serving this API.

        :returns: None

        """
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None

        """
        self.server.wait()


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(*servers):
    global _launcher
    if not _launcher:
        _launcher = Launcher()
    for server in servers:
        _launcher.launch_server(server)


def wait():
    LOG.debug(_('Full set of FLAGS:'))
    for flag in FLAGS:
        flag_get = FLAGS.get(flag, None)
        # hide flag contents from log if contains a password
        # should use secret flag when switch over to openstack-common
        if ("_password" in flag or "_key" in flag or
                (flag == "sql_connection" and "mysql:" in flag_get)):
            LOG.debug(_('%(flag)s : FLAG SET ') % locals())
        else:
            LOG.debug('%(flag)s : %(flag_get)s' % locals())
    try:
        _launcher.wait()
    except KeyboardInterrupt:
        _launcher.stop()
    rpc.cleanup()
