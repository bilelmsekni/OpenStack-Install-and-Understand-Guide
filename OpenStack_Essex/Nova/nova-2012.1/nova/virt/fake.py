# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
A fake (in-memory) hypervisor+api.

Allows nova testing w/o a hypervisor.  This module also documents the
semantics of real hypervisor connections.

"""

from nova.compute import power_state
from nova import db
from nova import exception
from nova import log as logging
from nova import utils
from nova.virt import driver


LOG = logging.getLogger(__name__)


def get_connection(_read_only):
    # The read_only parameter is ignored.
    return FakeConnection.instance()


class FakeInstance(object):

    def __init__(self, name, state):
        self.name = name
        self.state = state


class FakeConnection(driver.ComputeDriver):
    """Fake hypervisor driver"""

    def __init__(self):
        self.instances = {}
        self.host_status = {
          'host_name-description': 'Fake Host',
          'host_hostname': 'fake-mini',
          'host_memory_total': 8000000000,
          'host_memory_overhead': 10000000,
          'host_memory_free': 7900000000,
          'host_memory_free_computed': 7900000000,
          'host_other_config': {},
          'host_ip_address': '192.168.1.109',
          'host_cpu_info': {},
          'disk_available': 500000000000,
          'disk_total': 600000000000,
          'disk_used': 100000000000,
          'host_uuid': 'cedb9b39-9388-41df-8891-c5c9a0c0fe5f',
          'host_name_label': 'fake-mini'}
        self._mounts = {}

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def init_host(self, host):
        return

    def list_instances(self):
        return self.instances.keys()

    def _map_to_instance_info(self, instance):
        instance = utils.check_isinstance(instance, FakeInstance)
        info = driver.InstanceInfo(instance.name, instance.state)
        return info

    def list_instances_detail(self):
        info_list = []
        for instance in self.instances.values():
            info_list.append(self._map_to_instance_info(instance))
        return info_list

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        pass

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        pass

    def spawn(self, context, instance, image_meta,
              network_info=None, block_device_info=None):
        name = instance.name
        state = power_state.RUNNING
        fake_instance = FakeInstance(name, state)
        self.instances[name] = fake_instance

    def snapshot(self, context, instance, name):
        if not instance['name'] in self.instances:
            raise exception.InstanceNotRunning()

    def reboot(self, instance, network_info, reboot_type):
        pass

    @staticmethod
    def get_host_ip_addr():
        return '192.168.0.1'

    def resize(self, instance, flavor):
        pass

    def set_admin_password(self, instance, new_pass):
        pass

    def inject_file(self, instance, b64_path, b64_contents):
        pass

    def agent_update(self, instance, url, md5hash):
        pass

    def rescue(self, context, instance, network_info, image_meta):
        pass

    def unrescue(self, instance, network_info):
        pass

    def poll_rebooting_instances(self, timeout):
        pass

    def poll_rescued_instances(self, timeout):
        pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info):
        pass

    def finish_revert_migration(self, instance, network_info):
        pass

    def poll_unconfirmed_resizes(self, resize_confirm_window):
        pass

    def pause(self, instance):
        pass

    def unpause(self, instance):
        pass

    def suspend(self, instance):
        pass

    def resume(self, instance):
        pass

    def destroy(self, instance, network_info, block_device_info=None):
        key = instance['name']
        if key in self.instances:
            del self.instances[key]
        else:
            LOG.warning("Key '%s' not in instances '%s'" %
                        (key, self.instances))

    def attach_volume(self, connection_info, instance_name, mountpoint):
        """Attach the disk to the instance at mountpoint using info"""
        if not instance_name in self._mounts:
            self._mounts[instance_name] = {}
        self._mounts[instance_name][mountpoint] = connection_info
        return True

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Detach the disk attached to the instance"""
        try:
            del self._mounts[instance_name][mountpoint]
        except KeyError:
            pass
        return True

    def get_info(self, instance):
        if instance['name'] not in self.instances:
            raise exception.InstanceNotFound(instance_id=instance['name'])
        i = self.instances[instance['name']]
        return {'state': i.state,
                'max_mem': 0,
                'mem': 0,
                'num_cpu': 2,
                'cpu_time': 0}

    def get_diagnostics(self, instance_name):
        return 'FAKE_DIAGNOSTICS'

    def get_all_bw_usage(self, start_time, stop_time=None):
        """Return bandwidth usage info for each interface on each
           running VM"""
        bwusage = []
        return bwusage

    def list_disks(self, instance_name):
        return ['A_DISK']

    def list_interfaces(self, instance_name):
        return ['A_VIF']

    def block_stats(self, instance_name, disk_id):
        return [0L, 0L, 0L, 0L, None]

    def interface_stats(self, instance_name, iface_id):
        return [0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L]

    def get_console_output(self, instance):
        return 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE'

    def get_vnc_console(self, instance):
        return {'internal_access_path': 'FAKE',
                'host': 'fakevncconsole.com',
                'port': 6969}

    def get_console_pool_info(self, console_type):
        return  {'address': '127.0.0.1',
                 'username': 'fakeuser',
                 'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        return True

    def refresh_security_group_members(self, security_group_id):
        return True

    def refresh_provider_fw_rules(self):
        pass

    def update_available_resource(self, ctxt, host):
        """Updates compute manager resource info on ComputeNode table.

           Since we don't have a real hypervisor, pretend we have lots of
           disk and ram.
        """

        try:
            service_ref = db.service_get_all_compute_by_host(ctxt, host)[0]
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=host)

        # Updating host information
        dic = {'vcpus': 1,
               'memory_mb': 4096,
               'local_gb': 1028,
               'vcpus_used': 0,
               'memory_mb_used': 0,
               'local_gb_used': 0,
               'hypervisor_type': 'fake',
               'hypervisor_version': '1.0',
                  'service_id': service_ref['id'],
                 'cpu_info': '?'}

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
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def get_instance_disk_info(self, instance_name):
        """This method is supported only by libvirt."""
        return

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """This method is supported only by libvirt."""
        return

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance):
        return

    def confirm_migration(self, migration, instance, network_info):
        return

    def pre_live_migration(self, block_device_info):
        """This method is supported only by libvirt."""
        return

    def unfilter_instance(self, instance_ref, network_info):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def test_remove_vm(self, instance_name):
        """ Removes the named VM, as if it crashed. For testing"""
        self.instances.pop(instance_name)

    def update_host_status(self):
        """Return fake Host Status of ram, disk, network."""
        return self.host_status

    def get_host_stats(self, refresh=False):
        """Return fake Host Status of ram, disk, network."""
        return self.host_status

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        pass

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        pass

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass

    def get_disk_available_least(self):
        """ """
        pass

    def get_volume_connector(self, instance):
        return {'ip': '127.0.0.1', 'initiator': 'fake'}
