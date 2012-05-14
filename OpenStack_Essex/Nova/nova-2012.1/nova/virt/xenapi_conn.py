# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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
A connection to XenServer or Xen Cloud Platform.

The concurrency model for this class is as follows:

All XenAPI calls are on a green thread (using eventlet's "tpool"
thread pool). They are remote calls, and so may hang for the usual
reasons.

**Related Flags**

:xenapi_connection_url:  URL for connection to XenServer/Xen Cloud Platform.
:xenapi_connection_username:  Username for connection to XenServer/Xen Cloud
                              Platform (default: root).
:xenapi_connection_password:  Password for connection to XenServer/Xen Cloud
                              Platform.
:target_host:                the iSCSI Target Host IP address, i.e. the IP
                             address for the nova-volume host
:target_port:                iSCSI Target Port, 3260 Default
:iqn_prefix:                 IQN Prefix, e.g. 'iqn.2010-10.org.openstack'

**Variable Naming Scheme**

- suffix "_ref" for opaque references
- suffix "_uuid" for UUIDs
- suffix "_rec" for record objects
"""

import contextlib
import time
import urlparse
import xmlrpclib

from eventlet import greenthread
from eventlet import queue
from eventlet import tpool
from eventlet import timeout

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova.virt import driver
from nova.virt.xenapi import host
from nova.virt.xenapi import pool
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volumeops


LOG = logging.getLogger(__name__)

xenapi_opts = [
    cfg.StrOpt('xenapi_connection_url',
               default=None,
               help='URL for connection to XenServer/Xen Cloud Platform. '
                    'Required if connection_type=xenapi.'),
    cfg.StrOpt('xenapi_connection_username',
               default='root',
               help='Username for connection to XenServer/Xen Cloud Platform. '
                    'Used only if connection_type=xenapi.'),
    cfg.StrOpt('xenapi_connection_password',
               default=None,
               help='Password for connection to XenServer/Xen Cloud Platform. '
                    'Used only if connection_type=xenapi.'),
    cfg.IntOpt('xenapi_connection_concurrent',
               default=5,
               help='Maximum number of concurrent XenAPI connections. '
                    'Used only if connection_type=xenapi.'),
    cfg.FloatOpt('xenapi_vhd_coalesce_poll_interval',
                 default=5.0,
                 help='The interval used for polling of coalescing vhds. '
                      'Used only if connection_type=xenapi.'),
    cfg.IntOpt('xenapi_vhd_coalesce_max_attempts',
               default=5,
               help='Max number of times to poll for VHD to coalesce. '
                    'Used only if connection_type=xenapi.'),
    cfg.StrOpt('xenapi_agent_path',
               default='usr/sbin/xe-update-networking',
               help='Specifies the path in which the xenapi guest agent '
                    'should be located. If the agent is present, network '
                    'configuration is not injected into the image. '
                    'Used if connection_type=xenapi and flat_injected=True'),
    cfg.StrOpt('xenapi_sr_base_path',
               default='/var/run/sr-mount',
               help='Base path to the storage repository'),
    cfg.StrOpt('target_host',
               default=None,
               help='iSCSI Target Host'),
    cfg.StrOpt('target_port',
               default='3260',
               help='iSCSI Target Port, 3260 Default'),
    cfg.StrOpt('iqn_prefix',
               default='iqn.2010-10.org.openstack',
               help='IQN Prefix'),
    # NOTE(sirp): This is a work-around for a bug in Ubuntu Maverick,
    # when we pull support for it, we should remove this
    cfg.BoolOpt('xenapi_remap_vbd_dev',
                default=False,
                help='Used to enable the remapping of VBD dev '
                     '(Works around an issue in Ubuntu Maverick)'),
    cfg.StrOpt('xenapi_remap_vbd_dev_prefix',
               default='sd',
               help='Specify prefix to remap VBD dev to '
                    '(ex. /dev/xvdb -> /dev/sdb)'),
    cfg.IntOpt('xenapi_login_timeout',
               default=10,
               help='Timeout in seconds for XenAPI login.'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(xenapi_opts)


def get_connection(_read_only):
    """Note that XenAPI doesn't have a read-only connection mode, so
    the read_only parameter is ignored."""
    url = FLAGS.xenapi_connection_url
    username = FLAGS.xenapi_connection_username
    password = FLAGS.xenapi_connection_password
    if not url or password is None:
        raise Exception(_('Must specify xenapi_connection_url, '
                          'xenapi_connection_username (optionally), and '
                          'xenapi_connection_password to use '
                          'connection_type=xenapi'))
    return XenAPIConnection(url, username, password)


class XenAPIConnection(driver.ComputeDriver):
    """A connection to XenServer or Xen Cloud Platform"""

    def __init__(self, url, user, pw):
        super(XenAPIConnection, self).__init__()
        self._session = XenAPISession(url, user, pw)
        self._volumeops = volumeops.VolumeOps(self._session)
        self._host_state = None
        self._host = host.Host(self._session)
        self._product_version = self._session.get_product_version()
        self._vmops = vmops.VMOps(self._session, self._product_version)
        self._initiator = None
        self._pool = pool.ResourcePool(self._session)

    @property
    def host_state(self):
        if not self._host_state:
            self._host_state = host.HostState(self._session)
        return self._host_state

    def init_host(self, host):
        #FIXME(armando): implement this
        #NOTE(armando): would we need a method
        #to call when shutting down the host?
        #e.g. to do session logout?
        pass

    def list_instances(self):
        """List VM instances"""
        return self._vmops.list_instances()

    def list_instances_detail(self):
        return self._vmops.list_instances_detail()

    def spawn(self, context, instance, image_meta,
              network_info=None, block_device_info=None):
        """Create VM instance"""
        self._vmops.spawn(context, instance, image_meta, network_info)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM"""
        # TODO(Vek): Need to pass context in for access to auth_token
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, instance, network_info):
        """Finish reverting a resize, powering back on the instance"""
        # NOTE(vish): Xen currently does not use network info.
        self._vmops.finish_revert_migration(instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False):
        """Completes a resize, turning on the migrated instance"""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance)

    def snapshot(self, context, instance, image_id):
        """ Create snapshot from a running VM instance """
        self._vmops.snapshot(context, instance, image_id)

    def reboot(self, instance, network_info, reboot_type):
        """Reboot VM instance"""
        self._vmops.reboot(instance, reboot_type)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance"""
        self._vmops.set_admin_password(instance, new_pass)

    def inject_file(self, instance, b64_path, b64_contents):
        """Create a file on the VM instance. The file path and contents
        should be base64-encoded.
        """
        self._vmops.inject_file(instance, b64_path, b64_contents)

    def destroy(self, instance, network_info, block_device_info=None):
        """Destroy VM instance"""
        self._vmops.destroy(instance, network_info)

    def pause(self, instance):
        """Pause VM instance"""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance"""
        self._vmops.unpause(instance)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info):
        """Transfers the VHD of a running instance to another host, then shuts
        off the instance copies over the COW disk"""
        # NOTE(vish): Xen currently does not use network info.
        return self._vmops.migrate_disk_and_power_off(context, instance,
                                                      dest, instance_type)

    def suspend(self, instance):
        """suspend the specified instance"""
        self._vmops.suspend(instance)

    def resume(self, instance):
        """resume the specified instance"""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta):
        """Rescue the specified instance"""
        self._vmops.rescue(context, instance, network_info, image_meta)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance"""
        self._vmops.unrescue(instance)

    def power_off(self, instance):
        """Power off the specified instance"""
        self._vmops.power_off(instance)

    def power_on(self, instance):
        """Power on the specified instance"""
        self._vmops.power_on(instance)

    def poll_rebooting_instances(self, timeout):
        """Poll for rebooting instances"""
        self._vmops.poll_rebooting_instances(timeout)

    def poll_rescued_instances(self, timeout):
        """Poll for rescued instances"""
        self._vmops.poll_rescued_instances(timeout)

    def poll_unconfirmed_resizes(self, resize_confirm_window):
        """Poll for unconfirmed resizes"""
        self._vmops.poll_unconfirmed_resizes(resize_confirm_window)

    def reset_network(self, instance):
        """reset networking for specified instance"""
        self._vmops.reset_network(instance)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance"""
        self._vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance_ref, network_info):
        """Plug VIFs into networks."""
        self._vmops.plug_vifs(instance_ref, network_info)

    def unplug_vifs(self, instance_ref, network_info):
        """Unplug VIFs from networks."""
        self._vmops.unplug_vifs(instance_ref, network_info)

    def get_info(self, instance):
        """Return data about VM instance"""
        return self._vmops.get_info(instance)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        return self._vmops.get_diagnostics(instance)

    def get_all_bw_usage(self, start_time, stop_time=None):
        """Return bandwidth usage info for each interface on each
           running VM"""
        bwusage = []
        start_time = time.mktime(start_time.timetuple())
        if stop_time:
            stop_time = time.mktime(stop_time.timetuple())
        for iusage in self._vmops.get_all_bw_usage(start_time,
                                                   stop_time).values():
            for macaddr, usage in iusage.iteritems():
                bwusage.append(dict(mac_address=macaddr,
                                    bw_in=usage['bw_in'],
                                    bw_out=usage['bw_out']))
        return bwusage

    def get_console_output(self, instance):
        """Return snapshot of console"""
        return self._vmops.get_console_output(instance)

    def get_vnc_console(self, instance):
        """Return link to instance's VNC console"""
        return self._vmops.get_vnc_console(instance)

    def get_volume_connector(self, _instance):
        """Return volume connector information"""
        if not self._initiator:
            stats = self.get_host_stats(refresh=True)
            try:
                self._initiator = stats['host_other-config']['iscsi_iqn']
            except (TypeError, KeyError):
                LOG.warn(_('Could not determine iscsi initiator name'))
                self._initiator = None
        return {
            'ip': self.get_host_ip_addr(),
            'initiator': self._initiator
        }

    @staticmethod
    def get_host_ip_addr():
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return xs_url.netloc

    def attach_volume(self, connection_info, instance_name, mountpoint):
        """Attach volume storage to VM instance"""
        return self._volumeops.attach_volume(connection_info,
                                             instance_name,
                                             mountpoint)

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        return self._volumeops.detach_volume(connection_info,
                                             instance_name,
                                             mountpoint)

    def get_console_pool_info(self, console_type):
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return  {'address': xs_url.netloc,
                 'username': FLAGS.xenapi_connection_username,
                 'password': FLAGS.xenapi_connection_password}

    def update_available_resource(self, ctxt, host):
        """Updates compute manager resource info on ComputeNode table.

        This method is called when nova-compute launches, and
        whenever admin executes "nova-manage service update_resource".

        :param ctxt: security context
        :param host: hostname that compute manager is currently running

        """
        try:
            service_ref = db.service_get_all_compute_by_host(ctxt, host)[0]
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=host)

        host_stats = self.get_host_stats(refresh=True)

        # Updating host information
        total_ram_mb = host_stats['host_memory_total'] / (1024 * 1024)
        free_ram_mb = host_stats['host_memory_free'] / (1024 * 1024)
        total_disk_gb = host_stats['disk_total'] / (1024 * 1024 * 1024)
        used_disk_gb = host_stats['disk_used'] / (1024 * 1024 * 1024)

        dic = {'vcpus': 0,
               'memory_mb': total_ram_mb,
               'local_gb': total_disk_gb,
               'vcpus_used': 0,
               'memory_mb_used': total_ram_mb - free_ram_mb,
               'local_gb_used': used_disk_gb,
               'hypervisor_type': 'xen',
               'hypervisor_version': 0,
               'hypervisor_hostname': host_stats['host_hostname'],
               'service_id': service_ref['id'],
               'cpu_info': host_stats['host_cpu_info']['cpu_count']}

        compute_node_ref = service_ref['compute_node']
        if not compute_node_ref:
            LOG.info(_('Compute_service record created for %s ') % host)
            db.compute_node_create(ctxt, dic)
        else:
            LOG.info(_('Compute_service record updated for %s ') % host)
            db.compute_node_update(ctxt, compute_node_ref[0]['id'], dic)

    def compare_cpu(self, xml):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        """This method is supported only libvirt."""
        # NOTE(salvatore-orlando): it enforces security groups on
        # host initialization and live migration.
        # Live migration is not supported by XenAPI (as of 2011-11-09)
        # In XenAPI we do not assume instances running upon host initialization
        return

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """This method is supported only by libvirt."""
        return

    def unfilter_instance(self, instance_ref, network_info):
        """Removes security groups configured for an instance."""
        return self._vmops.unfilter_instance(instance_ref, network_info)

    def refresh_security_group_rules(self, security_group_id):
        """ Updates security group rules for all instances
            associated with a given security group
            Invoked when security group rules are updated
        """
        return self._vmops.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        """ Updates security group rules for all instances
            associated with a given security group
            Invoked when instances are added/removed to a security group
        """
        return self._vmops.refresh_security_group_members(security_group_id)

    def refresh_provider_fw_rules(self):
        return self._vmops.refresh_provider_fw_rules()

    def update_host_status(self):
        """Update the status info of the host, and return those values
            to the calling program."""
        return self.host_state.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
        return self.host_state.get_host_stats(refresh=refresh)

    def host_power_action(self, host, action):
        """The only valid values for 'action' on XenServer are 'reboot' or
        'shutdown', even though the API also accepts 'startup'. As this is
        not technically possible on XenServer, since the host is the same
        physical machine as the hypervisor, if this is requested, we need to
        raise an exception.
        """
        if action in ("reboot", "shutdown"):
            return self._host.host_power_action(host, action)
        else:
            msg = _("Host startup on XenServer is not supported.")
            raise NotImplementedError(msg)

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self._host.set_host_enabled(host, enabled)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        return self._host.host_maintenance_mode(host, mode)

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        """Add a compute host to an aggregate."""
        return self._pool.add_to_aggregate(context, aggregate, host, **kwargs)

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        """Remove a compute host from an aggregate."""
        return self._pool.remove_from_aggregate(context,
                                                aggregate, host, **kwargs)


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls"""

    def __init__(self, url, user, pw):
        self.XenAPI = self.get_imported_xenapi()
        self._sessions = queue.Queue()
        self.host_uuid = None
        self.is_slave = False
        exception = self.XenAPI.Failure(_("Unable to log in to XenAPI "
                                          "(is the Dom0 disk full?)"))
        url = self._create_first_session(url, user, pw, exception)
        self._populate_session_pool(url, user, pw, exception)
        self._populate_host_uuid()

    def _create_first_session(self, url, user, pw, exception):
        try:
            session = self._create_session(url)
            with timeout.Timeout(FLAGS.xenapi_login_timeout, exception):
                session.login_with_password(user, pw)
        except self.XenAPI.Failure, e:
            # if user and pw of the master are different, we're doomed!
            if e.details[0] == 'HOST_IS_SLAVE':
                master = e.details[1]
                url = pool.swap_xapi_host(url, master)
                session = self.XenAPI.Session(url)
                session.login_with_password(user, pw)
                self.is_slave = True
            else:
                raise
        self._sessions.put(session)
        return url

    def _populate_session_pool(self, url, user, pw, exception):
        for i in xrange(FLAGS.xenapi_connection_concurrent - 1):
            session = self._create_session(url)
            with timeout.Timeout(FLAGS.xenapi_login_timeout, exception):
                session.login_with_password(user, pw)
            self._sessions.put(session)

    def _populate_host_uuid(self):
        if self.is_slave:
            try:
                aggr = db.aggregate_get_by_host(context.get_admin_context(),
                                                FLAGS.host)
                self.host_uuid = aggr.metadetails[FLAGS.host]
            except exception.AggregateHostNotFound:
                LOG.exception(_('Host is member of a pool, but DB '
                                'says otherwise'))
                raise
        else:
            with self._get_session() as session:
                host_ref = session.xenapi.session.get_this_host(session.handle)
                self.host_uuid = session.xenapi.host.get_uuid(host_ref)

    def get_product_version(self):
        """Return a tuple of (major, minor, rev) for the host version"""
        host = self.get_xenapi_host()
        software_version = self.call_xenapi('host.get_software_version',
                                            host)
        product_version = software_version['product_version']
        return tuple(int(part) for part in product_version.split('.'))

    def get_imported_xenapi(self):
        """Stubout point. This can be replaced with a mock xenapi module."""
        return __import__('XenAPI')

    def get_session_id(self):
        """Return a string session_id.  Used for vnc consoles."""
        with self._get_session() as session:
            return str(session._session)

    @contextlib.contextmanager
    def _get_session(self):
        """Return exclusive session for scope of with statement"""
        session = self._sessions.get()
        try:
            yield session
        finally:
            self._sessions.put(session)

    def get_xenapi_host(self):
        """Return the xenapi host on which nova-compute runs on."""
        with self._get_session() as session:
            return session.xenapi.host.get_by_uuid(self.host_uuid)

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread."""
        with self._get_session() as session:
            f = session.xenapi
            for m in method.split('.'):
                f = getattr(f, m)
            return tpool.execute(f, *args)

    def call_xenapi_request(self, method, *args):
        """Some interactions with dom0, such as interacting with xenstore's
        param record, require using the xenapi_request method of the session
        object. This wraps that call on a background thread.
        """
        with self._get_session() as session:
            f = session.xenapi_request
            return tpool.execute(f, method, *args)

    def call_plugin(self, plugin, fn, args):
        """Call host.call_plugin on a background thread."""
        # NOTE(johannes): Fetch host before we acquire a session. Since
        # get_xenapi_host() acquires a session too, it can result in a
        # deadlock if multiple greenthreads race with each other. See
        # bug 924918
        host = self.get_xenapi_host()

        # NOTE(armando): pass the host uuid along with the args so that
        # the plugin gets executed on the right host when using XS pools
        args['host_uuid'] = self.host_uuid

        with self._get_session() as session:
            return tpool.execute(self._unwrap_plugin_exceptions,
                                 session.xenapi.host.call_plugin,
                                 host, plugin, fn, args)

    def _create_session(self, url):
        """Stubout point. This can be replaced with a mock session."""
        return self.XenAPI.Session(url)

    def _unwrap_plugin_exceptions(self, func, *args, **kwargs):
        """Parse exception details"""
        try:
            return func(*args, **kwargs)
        except self.XenAPI.Failure, exc:
            LOG.debug(_("Got exception: %s"), exc)
            if (len(exc.details) == 4 and
                exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
                exc.details[2] == 'Failure'):
                params = None
                try:
                    params = eval(exc.details[3])
                except Exception:
                    raise exc
                raise self.XenAPI.Failure(params)
            else:
                raise
        except xmlrpclib.ProtocolError, exc:
            LOG.debug(_("Got exception: %s"), exc)
            raise


def _parse_xmlrpc_value(val):
    """Parse the given value as if it were an XML-RPC value. This is
    sometimes used as the format for the task.result field."""
    if not val:
        return val
    x = xmlrpclib.loads(
        '<?xml version="1.0"?><methodResponse><params><param>' +
        val +
        '</param></params></methodResponse>')
    return x[0][0]
