# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2010 Citrix Systems, Inc.
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

"""Test suite for XenAPI."""

import ast
import contextlib
import datetime
import functools
import os
import re

from nova import db
from nova import context
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.compute import aggregate_states
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import utils as compute_utils
from nova import exception
from nova.virt import xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import vm_utils
from nova.tests.db import fakes as db_fakes
from nova.tests.xenapi import stubs
from nova.tests.glance import stubs as glance_stubs
from nova.tests import fake_network
from nova.tests import fake_utils

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


def stub_vm_utils_with_vdi_attached_here(function, should_return=True):
    """
    vm_utils.with_vdi_attached_here needs to be stubbed out because it
    calls down to the filesystem to attach a vdi. This provides a
    decorator to handle that.
    """
    @functools.wraps(function)
    def decorated_function(self, *args, **kwargs):
        @contextlib.contextmanager
        def fake_vdi_attached_here(*args, **kwargs):
            fake_dev = 'fakedev'
            yield fake_dev

        def fake_stream_disk(*args, **kwargs):
            pass

        def fake_is_vdi_pv(*args, **kwargs):
            return should_return

        orig_vdi_attached_here = vm_utils.vdi_attached_here
        orig_stream_disk = vm_utils._stream_disk
        orig_is_vdi_pv = vm_utils._is_vdi_pv
        try:
            vm_utils.vdi_attached_here = fake_vdi_attached_here
            vm_utils._stream_disk = fake_stream_disk
            vm_utils._is_vdi_pv = fake_is_vdi_pv
            return function(self, *args, **kwargs)
        finally:
            vm_utils._is_vdi_pv = orig_is_vdi_pv
            vm_utils._stream_disk = orig_stream_disk
            vm_utils.vdi_attached_here = orig_vdi_attached_here

    return decorated_function


class XenAPIVolumeTestCase(test.TestCase):
    """Unit tests for Volume operations."""
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.flags(target_host='127.0.0.1',
                xenapi_connection_url='test_url',
                xenapi_connection_password='test_pass',
                firewall_driver='nova.virt.xenapi.firewall.'
                                'Dom0IptablesFirewallDriver')
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()
        self.instance_values = {'id': 1,
                  'project_id': self.user_id,
                  'user_id': 'fake',
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

    def _create_volume(self, size='0'):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['host'] = 'localhost'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(self.context, vol)

    @staticmethod
    def _make_info():
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'volume_id': 1,
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                'target_portal': '127.0.0.1:3260,fake',
                'target_lun': None,
                'auth_method': 'CHAP',
                'auth_method': 'fake',
                'auth_method': 'fake',
            }
        }

    def test_mountpoint_to_number(self):
        cases = {
            'sda': 0,
            'sdp': 15,
            'hda': 0,
            'hdp': 15,
            'vda': 0,
            'xvda': 0,
            '0': 0,
            '10': 10,
            'vdq': -1,
            'sdq': -1,
            'hdq': -1,
            'xvdq': -1,
        }

        for (input, expected) in cases.iteritems():
            func = volume_utils.VolumeHelper.mountpoint_to_number
            actual = func(input)
            self.assertEqual(actual, expected,
                    '%s yielded %s, not %s' % (input, actual, expected))

    def test_parse_volume_info_raise_exception(self):
        """This shows how to test helper classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.XenAPI = session.get_imported_xenapi()
        vol = self._create_volume()
        # oops, wrong mount point!
        self.assertRaises(volume_utils.StorageError,
                          helper.parse_volume_info,
                          self._make_info(),
                          'dev/sd'
                          )
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        """This shows how to test Ops classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.instance_values)
        vm = xenapi_fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(self._make_info(),
                                    instance.name, '/dev/sdc')

        # check that the VM has a VBD attached to it
        # Get XenAPI record for VBD
        vbds = xenapi_fake.get_all('VBD')
        vbd = xenapi_fake.get_record('VBD', vbds[0])
        vm_ref = vbd['VM']
        self.assertEqual(vm_ref, vm)

    def test_attach_volume_raise_exception(self):
        """This shows how to test when exceptions are raised."""
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.instance_values)
        xenapi_fake.create_vm(instance.name, 'Running')
        self.assertRaises(exception.VolumeDriverNotFound,
                          conn.attach_volume,
                          {'driver_volume_type': 'nonexist'},
                          instance.name,
                          '/dev/sdc')


def configure_instance(*args):
    pass


class XenAPIVMTestCase(test.TestCase):
    """Unit tests for VM operations."""
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.network = utils.import_object(FLAGS.network_manager)
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        xenapi_fake.reset()
        xenapi_fake.create_local_srs()
        xenapi_fake.create_local_pifs()
        db_fakes.stub_out_db_instance_api(self.stubs)
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        stubs.stubout_stream_disk(self.stubs)
        stubs.stubout_is_vdi_pv(self.stubs)
        self.stubs.Set(vmops.VMOps, '_configure_instance',
                configure_instance)
        stubs.stub_out_vm_methods(self.stubs)
        glance_stubs.stubout_glance_client(self.stubs)
        fake_utils.stub_out_utils_execute(self.stubs)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.conn = xenapi_conn.get_connection(False)

    def test_list_instances_0(self):
        instances = self.conn.list_instances()
        self.assertEquals(instances, [])

    def test_get_rrd_server(self):
        self.flags(xenapi_connection_url='myscheme://myaddress/')
        server_info = vm_utils.get_rrd_server()
        self.assertEqual(server_info[0], 'myscheme')
        self.assertEqual(server_info[1], 'myaddress')

    def test_get_diagnostics(self):
        def fake_get_rrd(host, vm_uuid):
            with open('xenapi/vm_rrd.xml') as f:
                return re.sub(r'\s', '', f.read())
        self.stubs.Set(vm_utils, 'get_rrd', fake_get_rrd)

        fake_diagnostics = {
            'vbd_xvdb_write': '0.0',
            'memory_target': '10961792000.0000',
            'memory_internal_free': '3612860.6020',
            'memory': '10961792000.0000',
            'vbd_xvda_write': '0.0',
            'cpu0': '0.0110',
            'vif_0_tx': '752.4007',
            'vbd_xvda_read': '0.0',
            'vif_0_rx': '4837.8805'
        }
        instance = self._create_instance()
        expected = self.conn.get_diagnostics(instance)
        self.assertDictMatch(fake_diagnostics, expected)

    def test_instance_snapshot_fails_with_no_primary_vdi(self):
        def create_bad_vbd(vm_ref, vdi_ref):
            vbd_rec = {'VM': vm_ref,
               'VDI': vdi_ref,
               'userdevice': 'fake',
               'currently_attached': False}
            vbd_ref = xenapi_fake._create_object('VBD', vbd_rec)
            xenapi_fake.after_VBD_create(vbd_ref, vbd_rec)
            return vbd_ref

        self.stubs.Set(xenapi_fake, 'create_vbd', create_bad_vbd)
        stubs.stubout_instance_snapshot(self.stubs)
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        instance = self._create_instance()

        name = "MySnapshot"
        self.assertRaises(exception.Error, self.conn.snapshot,
                          self.context, instance, name)

    def test_instance_snapshot(self):
        stubs.stubout_instance_snapshot(self.stubs)
        stubs.stubout_is_snapshot(self.stubs)
        # Stubbing out firewall driver as previous stub sets alters
        # xml rpc result parsing
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        instance = self._create_instance()

        name = "MySnapshot"
        template_vm_ref = self.conn.snapshot(self.context, instance, name)

        # Ensure VM was torn down
        vm_labels = []
        for vm_ref in xenapi_fake.get_all('VM'):
            vm_rec = xenapi_fake.get_record('VM', vm_ref)
            if not vm_rec["is_control_domain"]:
                vm_labels.append(vm_rec["name_label"])

        self.assertEquals(vm_labels, [instance.name])

        # Ensure VBDs were torn down
        vbd_labels = []
        for vbd_ref in xenapi_fake.get_all('VBD'):
            vbd_rec = xenapi_fake.get_record('VBD', vbd_ref)
            vbd_labels.append(vbd_rec["vm_name_label"])

        self.assertEquals(vbd_labels, [instance.name])

        # Ensure VDIs were torn down
        for vdi_ref in xenapi_fake.get_all('VDI'):
            vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
            name_label = vdi_rec["name_label"]
            self.assert_(not name_label.endswith('snapshot'))

    def create_vm_record(self, conn, os_type, instance_id=1):
        instances = conn.list_instances()
        self.assertEquals(instances, [str(instance_id)])

        # Get Nova record for VM
        vm_info = conn.get_info({'name': instance_id})
        # Get XenAPI record for VM
        vms = [rec for ref, rec
               in xenapi_fake.get_all_records('VM').iteritems()
               if not rec['is_control_domain']]
        vm = vms[0]
        self.vm_info = vm_info
        self.vm = vm

    def check_vm_record(self, conn, check_injection=False):
        # Check that m1.large above turned into the right thing.
        instance_type = db.instance_type_get_by_name(conn, 'm1.large')
        mem_kib = long(instance_type['memory_mb']) << 10
        mem_bytes = str(mem_kib << 10)
        vcpus = instance_type['vcpus']
        self.assertEquals(self.vm_info['max_mem'], mem_kib)
        self.assertEquals(self.vm_info['mem'], mem_kib)
        self.assertEquals(self.vm['memory_static_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_min'], mem_bytes)
        self.assertEquals(self.vm['VCPUs_max'], str(vcpus))
        self.assertEquals(self.vm['VCPUs_at_startup'], str(vcpus))

        # Check that the VM is running according to Nova
        self.assertEquals(self.vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to XenAPI.
        self.assertEquals(self.vm['power_state'], 'Running')

        if check_injection:
            xenstore_data = self.vm['xenstore_data']
            key = 'vm-data/networking/DEADBEEF0000'
            xenstore_value = xenstore_data[key]
            tcpip_data = ast.literal_eval(xenstore_value)
            self.assertEquals(tcpip_data,
                              {'broadcast': '192.168.0.255',
                               'dns': ['192.168.0.1'],
                               'gateway': '192.168.0.1',
                               'gateway_v6': 'dead:beef::1',
                               'ip6s': [{'enabled': '1',
                                         'ip': 'dead:beef::dcad:beff:feef:0',
                                               'netmask': '64'}],
                               'ips': [{'enabled': '1',
                                        'ip': '192.168.0.100',
                                        'netmask': '255.255.255.0'}],
                               'dhcp_server': '192.168.0.1',
                               'label': 'fake',
                               'mac': 'DE:AD:BE:EF:00:00',
                               'rxtx_cap': 3})

    def check_vm_params_for_windows(self):
        self.assertEquals(self.vm['platform']['nx'], 'true')
        self.assertEquals(self.vm['HVM_boot_params'], {'order': 'dc'})
        self.assertEquals(self.vm['HVM_boot_policy'], 'BIOS order')

        # check that these are not set
        self.assertEquals(self.vm['PV_args'], '')
        self.assertEquals(self.vm['PV_bootloader'], '')
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')

    def check_vm_params_for_linux(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], '')
        self.assertEquals(self.vm['PV_bootloader'], 'pygrub')

        # check that these are not set
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def check_vm_params_for_linux_with_external_kernel(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], 'root=/dev/xvda1')
        self.assertNotEquals(self.vm['PV_kernel'], '')
        self.assertNotEquals(self.vm['PV_ramdisk'], '')

        # check that these are not set
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def _list_vdis(self):
        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password
        session = xenapi_conn.XenAPISession(url, username, password)
        return session.call_xenapi('VDI.get_all')

    def _check_vdis(self, start_list, end_list):
        for vdi_ref in end_list:
            if not vdi_ref in start_list:
                vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
                # If the cache is turned on then the base disk will be
                # there even after the cleanup
                if 'other_config' in vdi_rec:
                    if vdi_rec['other_config']['image-id'] is None:
                        self.fail('Found unexpected VDI:%s' % vdi_ref)
                else:
                    self.fail('Found unexpected VDI:%s' % vdi_ref)

    def _test_spawn(self, image_ref, kernel_id, ramdisk_id,
                    instance_type_id="3", os_type="linux",
                    hostname="test", architecture="x86-64", instance_id=1,
                    check_injection=False,
                    create_record=True, empty_dns=False):
        stubs.stubout_loopingcall_start(self.stubs)
        if create_record:
            instance_values = {'id': instance_id,
                      'project_id': self.project_id,
                      'user_id': self.user_id,
                      'image_ref': image_ref,
                      'kernel_id': kernel_id,
                      'ramdisk_id': ramdisk_id,
                      'root_gb': 20,
                      'instance_type_id': instance_type_id,
                      'os_type': os_type,
                      'hostname': hostname,
                      'architecture': architecture}
            instance = db.instance_create(self.context, instance_values)
        else:
            instance = db.instance_get(self.context, instance_id)
        network_info = [({'bridge': 'fa0', 'id': 0,
                          'injected': True,
                          'cidr': '192.168.0.0/24',
                          'cidr_v6': 'dead:beef::1/120',
                          },
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                           'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'dhcp_server': '192.168.0.1',
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]
        if empty_dns:
            network_info[0][1]['dns'] = []

        image_meta = {'id': glance_stubs.FakeGlance.IMAGE_VHD,
                      'disk_format': 'vhd'}
        self.conn.spawn(self.context, instance, image_meta, network_info)
        self.create_vm_record(self.conn, os_type, instance_id)
        self.check_vm_record(self.conn, check_injection)
        self.assertTrue(instance.os_type)
        self.assertTrue(instance.architecture)

    def test_spawn_empty_dns(self):
        """Test spawning with an empty dns list"""
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64",
                         empty_dns=True)
        self.check_vm_params_for_linux()

    def test_spawn_not_enough_memory(self):
        self.assertRaises(exception.InsufficientFreeMemory,
                          self._test_spawn,
                          1, 2, 3, "4")  # m1.xlarge

    def test_spawn_fail_cleanup_1(self):
        """Simulates an error while downloading an image.

        Verifies that VDIs created are properly cleaned up.

        """
        vdi_recs_start = self._list_vdis()
        stubs.stubout_fetch_image_glance_disk(self.stubs, raise_failure=True)
        self.assertRaises(xenapi_fake.Failure,
                          self._test_spawn, 1, 2, 3)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        self._check_vdis(vdi_recs_start, vdi_recs_end)

    def test_spawn_fail_cleanup_2(self):
        """Simulates an error while creating VM record.

        It verifies that VDIs created are properly cleaned up.

        """
        vdi_recs_start = self._list_vdis()
        stubs.stubout_create_vm(self.stubs)
        self.assertRaises(xenapi_fake.Failure,
                          self._test_spawn, 1, 2, 3)
        # No additional VDI should be found.
        vdi_recs_end = self._list_vdis()
        self._check_vdis(vdi_recs_start, vdi_recs_end)

    @stub_vm_utils_with_vdi_attached_here
    def test_spawn_raw_glance(self):
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_RAW, None, None)
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_linux(self):
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_VHD, None, None,
                         os_type="linux", architecture="x86-64")
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_swapdisk(self):
        # Change the default host_call_plugin to one that'll return
        # a swap disk
        orig_func = stubs.FakeSessionForVMTests.host_call_plugin
        _host_call_plugin = stubs.FakeSessionForVMTests.host_call_plugin_swap
        stubs.FakeSessionForVMTests.host_call_plugin = _host_call_plugin
        # Stubbing out firewall driver as previous stub sets a particular
        # stub for async plugin calls
        stubs.stubout_firewall_driver(self.stubs, self.conn)
        try:
            # We'll steal the above glance linux test
            self.test_spawn_vhd_glance_linux()
        finally:
            # Make sure to put this back
            stubs.FakeSessionForVMTests.host_call_plugin = orig_func

        # We should have 2 VBDs.
        self.assertEqual(len(self.vm['VBDs']), 2)
        # Now test that we have 1.
        self.tearDown()
        self.setUp()
        self.test_spawn_vhd_glance_linux()
        self.assertEqual(len(self.vm['VBDs']), 1)

    def test_spawn_vhd_glance_windows(self):
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_VHD, None, None,
                         os_type="windows", architecture="i386")
        self.check_vm_params_for_windows()

    def test_spawn_iso_glance(self):
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_ISO, None, None,
                         os_type="windows", architecture="i386")
        self.check_vm_params_for_windows()

    def test_spawn_glance(self):
        stubs.stubout_fetch_image_glance_disk(self.stubs)
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK)
        self.check_vm_params_for_linux_with_external_kernel()

    def test_spawn_netinject_file(self):
        self.flags(flat_injected=True)
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _tee_handler(cmd, **kwargs):
            input = kwargs.get('process_input', None)
            self.assertNotEqual(input, None)
            config = [line.strip() for line in input.split("\n")]
            # Find the start of eth0 configuration and check it
            index = config.index('auto eth0')
            self.assertEquals(config[index + 1:index + 8], [
                'iface eth0 inet static',
                'address 192.168.0.100',
                'netmask 255.255.255.0',
                'broadcast 192.168.0.255',
                'gateway 192.168.0.1',
                'dns-nameservers 192.168.0.1',
                ''])
            self._tee_executed = True
            return '', ''

        fake_utils.fake_execute_set_repliers([
            # Capture the tee .../etc/network/interfaces command
            (r'tee.*interfaces', _tee_handler),
        ])
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK,
                         check_injection=True)
        self.assertTrue(self._tee_executed)

    def test_spawn_netinject_xenstore(self):
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _mount_handler(cmd, *ignore_args, **ignore_kwargs):
            # When mounting, create real files under the mountpoint to simulate
            # files in the mounted filesystem

            # mount point will be the last item of the command list
            self._tmpdir = cmd[len(cmd) - 1]
            LOG.debug(_('Creating files in %s to simulate guest agent') %
                self._tmpdir)
            os.makedirs(os.path.join(self._tmpdir, 'usr', 'sbin'))
            # Touch the file using open
            open(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'), 'w').close()
            return '', ''

        def _umount_handler(cmd, *ignore_args, **ignore_kwargs):
            # Umount would normall make files in the m,ounted filesystem
            # disappear, so do that here
            LOG.debug(_('Removing simulated guest agent files in %s') %
                self._tmpdir)
            os.remove(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'))
            os.rmdir(os.path.join(self._tmpdir, 'usr', 'sbin'))
            os.rmdir(os.path.join(self._tmpdir, 'usr'))
            return '', ''

        def _tee_handler(cmd, *ignore_args, **ignore_kwargs):
            self._tee_executed = True
            return '', ''

        fake_utils.fake_execute_set_repliers([
            (r'mount', _mount_handler),
            (r'umount', _umount_handler),
            (r'tee.*interfaces', _tee_handler)])
        self._test_spawn(1, 2, 3, check_injection=True)

        # tee must not run in this case, where an injection-capable
        # guest agent is detected
        self.assertFalse(self._tee_executed)

    def test_spawn_vlanmanager(self):
        self.flags(image_service='nova.image.glance.GlanceImageService',
                   network_manager='nova.network.manager.VlanManager',
                   vlan_interface='fake0')

        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(vmops.VMOps, 'create_vifs', dummy)
        # Reset network table
        xenapi_fake.reset_table('network')
        # Instance id = 2 will use vlan network (see db/fakes.py)
        ctxt = self.context.elevated()
        instance = self._create_instance(2, False)
        networks = self.network.db.network_get_all(ctxt)
        for network in networks:
            self.network.set_network_host(ctxt, network)

        self.network.allocate_for_instance(ctxt,
                          instance_id=2,
                          instance_uuid="00000000-0000-0000-0000-000000000000",
                          host=FLAGS.host,
                          vpn=None,
                          rxtx_factor=3,
                          project_id=self.project_id)
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK,
                         instance_id=2,
                         create_record=False)
        # TODO(salvatore-orlando): a complete test here would require
        # a check for making sure the bridge for the VM's VIF is
        # consistent with bridge specified in nova db

    def test_spawn_with_network_qos(self):
        self._create_instance()
        for vif_ref in xenapi_fake.get_all('VIF'):
            vif_rec = xenapi_fake.get_record('VIF', vif_ref)
            self.assertEquals(vif_rec['qos_algorithm_type'], 'ratelimit')
            self.assertEquals(vif_rec['qos_algorithm_params']['kbps'],
                              str(3 * 1024))

    def test_rescue(self):
        def _find_rescue_vbd_ref(*args):
            return vbd

        self.stubs.Set(vmops.VMOps, '_find_rescue_vbd_ref',
                _find_rescue_vbd_ref)
        instance = self._create_instance()
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        vm = vm_utils.VMHelper.lookup(session, instance.name)
        vbd = xenapi_fake.create_vbd(vm, None)
        conn = xenapi_conn.get_connection(False)
        conn.rescue(self.context, instance, [], None)

    def test_unrescue(self):
        instance = self._create_instance()
        conn = xenapi_conn.get_connection(False)
        # Ensure that it will not unrescue a non-rescued instance.
        self.assertRaises(exception.InstanceNotInRescueMode, conn.unrescue,
                          instance, None)

    def test_finish_revert_migration(self):
        instance = self._create_instance()

        class VMOpsMock():

            def __init__(self):
                self.finish_revert_migration_called = False

            def finish_revert_migration(self, instance):
                self.finish_revert_migration_called = True

        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)

        conn = xenapi_conn.get_connection(False)
        conn._vmops = VMOpsMock()
        conn.finish_revert_migration(instance, None)
        self.assertTrue(conn._vmops.finish_revert_migration_called)

    def _create_instance(self, instance_id=1, spawn=True):
        """Creates and spawns a test instance."""
        stubs.stubout_loopingcall_start(self.stubs)
        instance_values = {
            'id': instance_id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'image_ref': 1,
            'kernel_id': 2,
            'ramdisk_id': 3,
            'root_gb': 20,
            'instance_type_id': '3',  # m1.large
            'os_type': 'linux',
            'architecture': 'x86-64'}
        instance = db.instance_create(self.context, instance_values)
        network_info = [({'bridge': 'fa0', 'id': 0,
                          'injected': False,
                          'cidr': '192.168.0.0/24',
                          'cidr_v6': 'dead:beef::1/120',
                          },
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                           'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'dhcp_server': '192.168.0.1',
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]
        image_meta = {'id': glance_stubs.FakeGlance.IMAGE_VHD,
                      'disk_format': 'vhd'}
        if spawn:
            self.conn.spawn(self.context, instance, image_meta, network_info)
        return instance


class XenAPIDiffieHellmanTestCase(test.TestCase):
    """Unit tests for Diffie-Hellman code."""
    def setUp(self):
        super(XenAPIDiffieHellmanTestCase, self).setUp()
        self.alice = vmops.SimpleDH()
        self.bob = vmops.SimpleDH()

    def test_shared(self):
        alice_pub = self.alice.get_public()
        bob_pub = self.bob.get_public()
        alice_shared = self.alice.compute_shared(bob_pub)
        bob_shared = self.bob.compute_shared(alice_pub)
        self.assertEquals(alice_shared, bob_shared)

    def _test_encryption(self, message):
        enc = self.alice.encrypt(message)
        self.assertFalse(enc.endswith('\n'))
        dec = self.bob.decrypt(enc)
        self.assertEquals(dec, message)

    def test_encrypt_simple_message(self):
        self._test_encryption('This is a simple message.')

    def test_encrypt_message_with_newlines_at_end(self):
        self._test_encryption('This message has a newline at the end.\n')

    def test_encrypt_many_newlines_at_end(self):
        self._test_encryption('Message with lotsa newlines.\n\n\n')

    def test_encrypt_newlines_inside_message(self):
        self._test_encryption('Message\nwith\ninterior\nnewlines.')

    def test_encrypt_with_leading_newlines(self):
        self._test_encryption('\n\nMessage with leading newlines.')

    def test_encrypt_really_long_message(self):
        self._test_encryption(''.join(['abcd' for i in xrange(1024)]))


class XenAPIMigrateInstance(test.TestCase):
    """Unit test for verifying migration-related actions."""

    def setUp(self):
        super(XenAPIMigrateInstance, self).setUp()
        self.flags(target_host='127.0.0.1',
                xenapi_connection_url='test_url',
                xenapi_connection_password='test_pass',
                firewall_driver='nova.virt.xenapi.firewall.'
                                'Dom0IptablesFirewallDriver')
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': None,
                  'ramdisk_id': None,
                  'root_gb': 5,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        migration_values = {
            'source_compute': 'nova-compute',
            'dest_compute': 'nova-compute',
            'dest_host': '10.127.5.114',
            'status': 'post-migrating',
            'instance_uuid': '15f23e6a-cc6e-4d22-b651-d9bdaac316f7',
            'old_instance_type_id': 5,
            'new_instance_type_id': 1
        }
        self.migration = db.migration_create(
            context.get_admin_context(), migration_values)

        fake_utils.stub_out_utils_execute(self.stubs)
        stubs.stub_out_migration_methods(self.stubs)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        glance_stubs.stubout_glance_client(self.stubs)

    def test_resize_xenserver_6(self):
        instance = db.instance_create(self.context, self.instance_values)
        called = {'resize': False}

        def fake_vdi_resize(*args, **kwargs):
            called['resize'] = True

        self.stubs.Set(stubs.FakeSessionForMigrationTests,
                       "VDI_resize", fake_vdi_resize)
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForMigrationTests,
                              product_version=(6, 0, 0))
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        conn._vmops._resize_instance(instance, '')
        self.assertEqual(called['resize'], True)

    def test_migrate_disk_and_power_off(self):
        instance = db.instance_create(self.context, self.instance_values)
        instance_type = db.instance_type_get_by_name(self.context, 'm1.large')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        conn = xenapi_conn.get_connection(False)
        conn.migrate_disk_and_power_off(self.context, instance,
                                        '127.0.0.1', instance_type, None)

    def test_migrate_disk_and_power_off_passes_exceptions(self):
        instance = db.instance_create(self.context, self.instance_values)
        instance_type = db.instance_type_get_by_name(self.context, 'm1.large')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)

        def fake_raise(*args, **kwargs):
            raise exception.MigrationError(reason='test failure')
        self.stubs.Set(vmops.VMOps, "_migrate_vhd", fake_raise)

        conn = xenapi_conn.get_connection(False)
        self.assertRaises(exception.MigrationError,
                          conn.migrate_disk_and_power_off,
                          self.context, instance,
                          '127.0.0.1', instance_type, None)

    def test_revert_migrate(self):
        instance = db.instance_create(self.context, self.instance_values)
        self.called = False
        self.fake_vm_start_called = False
        self.fake_finish_revert_migration_called = False

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        def fake_finish_revert_migration(*args, **kwargs):
            self.fake_finish_revert_migration_called = True

        self.stubs.Set(stubs.FakeSessionForMigrationTests,
                       "VDI_resize_online", fake_vdi_resize)
        self.stubs.Set(vmops.VMOps, '_start', fake_vm_start)
        self.stubs.Set(vmops.VMOps, 'finish_revert_migration',
                       fake_finish_revert_migration)

        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        network_info = [({'bridge': 'fa0', 'id': 0, 'injected': False},
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                     'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)
        self.assertEqual(self.called, True)
        self.assertEqual(self.fake_vm_start_called, True)

        conn.finish_revert_migration(instance, network_info)
        self.assertEqual(self.fake_finish_revert_migration_called, True)

    def test_finish_migrate(self):
        instance = db.instance_create(self.context, self.instance_values)
        self.called = False
        self.fake_vm_start_called = False

        def fake_vm_start(*args, **kwargs):
            self.fake_vm_start_called = True

        def fake_vdi_resize(*args, **kwargs):
            self.called = True

        self.stubs.Set(vmops.VMOps, '_start', fake_vm_start)
        self.stubs.Set(stubs.FakeSessionForMigrationTests,
                       "VDI_resize_online", fake_vdi_resize)

        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        network_info = [({'bridge': 'fa0', 'id': 0, 'injected': False},
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                           'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)
        self.assertEqual(self.called, True)
        self.assertEqual(self.fake_vm_start_called, True)

    def test_finish_migrate_no_local_storage(self):
        tiny_type = instance_types.get_instance_type_by_name('m1.tiny')
        tiny_type_id = tiny_type['id']
        self.instance_values.update({'instance_type_id': tiny_type_id,
                                     'root_gb': 0})
        instance = db.instance_create(self.context, self.instance_values)

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stubs.Set(stubs.FakeSessionForMigrationTests,
                       "VDI_resize_online", fake_vdi_resize)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        network_info = [({'bridge': 'fa0', 'id': 0, 'injected': False},
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                           'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=True)

    def test_finish_migrate_no_resize_vdi(self):
        instance = db.instance_create(self.context, self.instance_values)

        def fake_vdi_resize(*args, **kwargs):
            raise Exception("This shouldn't be called")

        self.stubs.Set(stubs.FakeSessionForMigrationTests,
                "VDI_resize_online", fake_vdi_resize)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        network_info = [({'bridge': 'fa0', 'id': 0, 'injected': False},
                          {'broadcast': '192.168.0.255',
                           'dns': ['192.168.0.1'],
                           'gateway': '192.168.0.1',
                           'gateway_v6': 'dead:beef::1',
                           'ip6s': [{'enabled': '1',
                                     'ip': 'dead:beef::dcad:beff:feef:0',
                                           'netmask': '64'}],
                           'ips': [{'enabled': '1',
                                    'ip': '192.168.0.100',
                                    'netmask': '255.255.255.0'}],
                           'label': 'fake',
                           'mac': 'DE:AD:BE:EF:00:00',
                           'rxtx_cap': 3})]

        # Resize instance would be determined by the compute call
        image_meta = {'id': instance.image_ref, 'disk_format': 'vhd'}
        conn.finish_migration(self.context, self.migration, instance,
                              dict(base_copy='hurr', cow='durr'),
                              network_info, image_meta, resize_instance=False)


class XenAPIImageTypeTestCase(test.TestCase):
    """Test ImageType class."""

    def test_to_string(self):
        """Can convert from type id to type string."""
        self.assertEquals(
            vm_utils.ImageType.to_string(vm_utils.ImageType.KERNEL),
            vm_utils.ImageType.KERNEL_STR)

    def test_from_string(self):
        """Can convert from string to type id."""
        self.assertEquals(
            vm_utils.ImageType.from_string(vm_utils.ImageType.KERNEL_STR),
            vm_utils.ImageType.KERNEL)


class XenAPIDetermineDiskImageTestCase(test.TestCase):
    """Unit tests for code that detects the ImageType."""
    def setUp(self):
        super(XenAPIDetermineDiskImageTestCase, self).setUp()
        glance_stubs.stubout_glance_client(self.stubs)

        class FakeInstance(object):
            pass

        self.fake_instance = FakeInstance()
        self.fake_instance.id = 42
        self.fake_instance.os_type = 'linux'
        self.fake_instance.architecture = 'x86-64'

    def assert_disk_type(self, image_meta, expected_disk_type):
        actual = vm_utils.VMHelper.determine_disk_image_type(image_meta)
        self.assertEqual(expected_disk_type, actual)

    def test_machine(self):
        image_meta = {'id': 'a', 'disk_format': 'ami'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK)

    def test_raw(self):
        image_meta = {'id': 'a', 'disk_format': 'raw'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_RAW)

    def test_vhd(self):
        image_meta = {'id': 'a', 'disk_format': 'vhd'}
        self.assert_disk_type(image_meta, vm_utils.ImageType.DISK_VHD)


class CompareVersionTestCase(test.TestCase):
    def test_less_than(self):
        """Test that cmp_version compares a as less than b"""
        self.assertTrue(vmops.cmp_version('1.2.3.4', '1.2.3.5') < 0)

    def test_greater_than(self):
        """Test that cmp_version compares a as greater than b"""
        self.assertTrue(vmops.cmp_version('1.2.3.5', '1.2.3.4') > 0)

    def test_equal(self):
        """Test that cmp_version compares a as equal to b"""
        self.assertTrue(vmops.cmp_version('1.2.3.4', '1.2.3.4') == 0)

    def test_non_lexical(self):
        """Test that cmp_version compares non-lexically"""
        self.assertTrue(vmops.cmp_version('1.2.3.10', '1.2.3.4') > 0)

    def test_length(self):
        """Test that cmp_version compares by length as last resort"""
        self.assertTrue(vmops.cmp_version('1.2.3', '1.2.3.4') < 0)


class XenAPIHostTestCase(test.TestCase):
    """Tests HostState, which holds metrics from XenServer that get
    reported back to the Schedulers."""

    def setUp(self):
        super(XenAPIHostTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        xenapi_fake.reset()
        xenapi_fake.create_local_srs()
        self.conn = xenapi_conn.get_connection(False)

    def test_host_state(self):
        stats = self.conn.get_host_stats()
        self.assertEquals(stats['disk_total'], 10000)
        self.assertEquals(stats['disk_used'], 20000)
        self.assertEquals(stats['host_memory_total'], 10)
        self.assertEquals(stats['host_memory_overhead'], 20)
        self.assertEquals(stats['host_memory_free'], 30)
        self.assertEquals(stats['host_memory_free_computed'], 40)

    def _test_host_action(self, method, action, expected=None):
        result = method('host', action)
        if not expected:
            expected = action
        self.assertEqual(result, expected)

    def test_host_reboot(self):
        self._test_host_action(self.conn.host_power_action, 'reboot')

    def test_host_shutdown(self):
        self._test_host_action(self.conn.host_power_action, 'shutdown')

    def test_host_startup(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_power_action, 'host', 'startup')

    def test_host_maintenance_on(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               True, 'on_maintenance')

    def test_host_maintenance_off(self):
        self._test_host_action(self.conn.host_maintenance_mode,
                               False, 'off_maintenance')

    def test_set_enable_host_enable(self):
        self._test_host_action(self.conn.set_host_enabled, True, 'enabled')

    def test_set_enable_host_disable(self):
        self._test_host_action(self.conn.set_host_enabled, False, 'disabled')


class XenAPIAutoDiskConfigTestCase(test.TestCase):
    def setUp(self):
        super(XenAPIAutoDiskConfigTestCase, self).setUp()
        self.flags(target_host='127.0.0.1',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        xenapi_fake.reset()
        self.conn = xenapi_conn.get_connection(False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        @classmethod
        def fake_create_vbd(cls, session, vm_ref, vdi_ref, userdevice,
                            vbd_type='disk', read_only=False, bootable=True):
            pass

        self.stubs.Set(vm_utils.VMHelper,
                       "create_vbd",
                       fake_create_vbd)

    def assertIsPartitionCalled(self, called):
        marker = {"partition_called": False}

        def fake_resize_part_and_fs(dev, start, old, new):
            marker["partition_called"] = True
        self.stubs.Set(vm_utils, "_resize_part_and_fs",
                       fake_resize_part_and_fs)

        instance = db.instance_create(self.context, self.instance_values)
        disk_image_type = vm_utils.ImageType.DISK_VHD
        vm_ref = "blah"
        first_vdi_ref = "blah"
        vdis = ["blah"]

        self.conn._vmops._attach_disks(
            instance, disk_image_type, vm_ref, first_vdi_ref, vdis)

        self.assertEqual(marker["partition_called"], called)

    def test_instance_not_auto_disk_config(self):
        """Should not partition unless instance is marked as
        auto_disk_config.
        """
        self.instance_values['auto_disk_config'] = False
        self.assertIsPartitionCalled(False)

    @stub_vm_utils_with_vdi_attached_here
    def test_instance_auto_disk_config_doesnt_pass_fail_safes(self):
        """Should not partition unless fail safes pass"""
        self.instance_values['auto_disk_config'] = True

        def fake_get_partitions(dev):
            return [(1, 0, 100, 'ext4'), (2, 100, 200, 'ext4')]
        self.stubs.Set(vm_utils, "_get_partitions",
                       fake_get_partitions)

        self.assertIsPartitionCalled(False)

    @stub_vm_utils_with_vdi_attached_here
    def test_instance_auto_disk_config_passes_fail_safes(self):
        """Should partition if instance is marked as auto_disk_config=True and
        virt-layer specific fail-safe checks pass.
        """
        self.instance_values['auto_disk_config'] = True

        def fake_get_partitions(dev):
            return [(1, 0, 100, 'ext4')]
        self.stubs.Set(vm_utils, "_get_partitions",
                       fake_get_partitions)

        self.assertIsPartitionCalled(True)


class XenAPIGenerateLocal(test.TestCase):
    """Test generating of local disks, like swap and ephemeral"""
    def setUp(self):
        super(XenAPIGenerateLocal, self).setUp()
        self.flags(target_host='127.0.0.1',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   xenapi_generate_swap=True,
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        db_fakes.stub_out_db_instance_api(self.stubs)
        xenapi_fake.reset()
        self.conn = xenapi_conn.get_connection(False)

        self.user_id = 'fake'
        self.project_id = 'fake'

        self.instance_values = {'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'root_gb': 20,
                  'instance_type_id': '3',  # m1.large
                  'os_type': 'linux',
                  'architecture': 'x86-64'}

        self.context = context.RequestContext(self.user_id, self.project_id)

        @classmethod
        def fake_create_vbd(cls, session, vm_ref, vdi_ref, userdevice,
                            vbd_type='disk', read_only=False, bootable=True):
            pass

        self.stubs.Set(vm_utils.VMHelper,
                       "create_vbd",
                       fake_create_vbd)

    def assertCalled(self, instance):
        disk_image_type = vm_utils.ImageType.DISK_VHD
        vm_ref = "blah"
        first_vdi_ref = "blah"
        vdis = ["blah"]

        self.called = False
        self.conn._vmops._attach_disks(instance, disk_image_type,
                                       vm_ref, first_vdi_ref, vdis)
        self.assertTrue(self.called)

    def test_generate_swap(self):
        """Test swap disk generation."""
        instance = db.instance_create(self.context, self.instance_values)
        instance = db.instance_update(self.context, instance['id'],
                                      {'instance_type_id': 5})

        @classmethod
        def fake_generate_swap(cls, *args, **kwargs):
            self.called = True
        self.stubs.Set(vm_utils.VMHelper, 'generate_swap',
                       fake_generate_swap)

        self.assertCalled(instance)

    def test_generate_ephemeral(self):
        """Test ephemeral disk generation."""
        instance = db.instance_create(self.context, self.instance_values)
        instance = db.instance_update(self.context, instance['id'],
                                      {'instance_type_id': 4})

        @classmethod
        def fake_generate_ephemeral(cls, *args):
            self.called = True
        self.stubs.Set(vm_utils.VMHelper, 'generate_ephemeral',
                       fake_generate_ephemeral)

        self.assertCalled(instance)


class XenAPIBWUsageTestCase(test.TestCase):
    def setUp(self):
        super(XenAPIBWUsageTestCase, self).setUp()
        self.stubs.Set(vm_utils.VMHelper, "compile_metrics",
                       XenAPIBWUsageTestCase._fake_compile_metrics)
        self.flags(target_host='127.0.0.1',
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        xenapi_fake.reset()
        self.conn = xenapi_conn.get_connection(False)

    @classmethod
    def _fake_compile_metrics(cls, start_time, stop_time=None):
        raise exception.CouldNotFetchMetrics()

    def test_get_all_bw_usage_in_failure_case(self):
        """Test that get_all_bw_usage returns an empty list when metrics
        compilation failed.  c.f. bug #910045.
        """
        result = self.conn.get_all_bw_usage(datetime.datetime.utcnow())
        self.assertEqual(result, [])


# TODO(salvatore-orlando): this class and
# nova.tests.test_libvirt.IPTablesFirewallDriverTestCase share a lot of code.
# Consider abstracting common code in a base class for firewall driver testing.
class XenAPIDom0IptablesFirewallTestCase(test.TestCase):

    _in_nat_rules = [
      '# Generated by iptables-save v1.4.10 on Sat Feb 19 00:03:19 2011',
      '*nat',
      ':PREROUTING ACCEPT [1170:189210]',
      ':INPUT ACCEPT [844:71028]',
      ':OUTPUT ACCEPT [5149:405186]',
      ':POSTROUTING ACCEPT [5063:386098]',
    ]

    _in_filter_rules = [
      '# Generated by iptables-save v1.4.4 on Mon Dec  6 11:54:13 2010',
      '*filter',
      ':INPUT ACCEPT [969615:281627771]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [915599:63811649]',
      ':nova-block-ipv4 - [0:0]',
      '-A INPUT -i virbr0 -p tcp -m tcp --dport 67 -j ACCEPT ',
      '-A FORWARD -d 192.168.122.0/24 -o virbr0 -m state --state RELATED'
      ',ESTABLISHED -j ACCEPT ',
      '-A FORWARD -s 192.168.122.0/24 -i virbr0 -j ACCEPT ',
      '-A FORWARD -i virbr0 -o virbr0 -j ACCEPT ',
      '-A FORWARD -o virbr0 -j REJECT --reject-with icmp-port-unreachable ',
      '-A FORWARD -i virbr0 -j REJECT --reject-with icmp-port-unreachable ',
      'COMMIT',
      '# Completed on Mon Dec  6 11:54:13 2010',
    ]

    _in6_filter_rules = [
      '# Generated by ip6tables-save v1.4.4 on Tue Jan 18 23:47:56 2011',
      '*filter',
      ':INPUT ACCEPT [349155:75810423]',
      ':FORWARD ACCEPT [0:0]',
      ':OUTPUT ACCEPT [349256:75777230]',
      'COMMIT',
      '# Completed on Tue Jan 18 23:47:56 2011',
    ]

    def setUp(self):
        super(XenAPIDom0IptablesFirewallTestCase, self).setUp()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        xenapi_fake.reset()
        xenapi_fake.create_local_srs()
        xenapi_fake.create_local_pifs()
        self.user_id = 'mappin'
        self.project_id = 'fake'
        stubs.stubout_session(self.stubs, stubs.FakeSessionForFirewallTests,
                              test_case=self)
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.network = utils.import_object(FLAGS.network_manager)
        self.conn = xenapi_conn.get_connection(False)
        self.fw = self.conn._vmops.firewall_driver

    def _create_instance_ref(self):
        return db.instance_create(self.context,
                                  {'user_id': self.user_id,
                                   'project_id': self.project_id,
                                   'instance_type_id': 1})

    def _create_test_security_group(self):
        admin_ctxt = context.get_admin_context()
        secgroup = db.security_group_create(admin_ctxt,
                                {'user_id': self.user_id,
                                 'project_id': self.project_id,
                                 'name': 'testgroup',
                                 'description': 'test group'})
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': -1,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'icmp',
                                       'from_port': 8,
                                       'to_port': -1,
                                       'cidr': '192.168.11.0/24'})

        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'cidr': '192.168.10.0/24'})
        return secgroup

    def _validate_security_group(self):
        in_rules = filter(lambda l: not l.startswith('#'),
                          self._in_filter_rules)
        for rule in in_rules:
            if not 'nova' in rule:
                self.assertTrue(rule in self._out_rules,
                                'Rule went missing: %s' % rule)

        instance_chain = None
        for rule in self._out_rules:
            # This is pretty crude, but it'll do for now
            # last two octets change
            if re.search('-d 192.168.[0-9]{1,3}.[0-9]{1,3} -j', rule):
                instance_chain = rule.split(' ')[-1]
                break
        self.assertTrue(instance_chain, "The instance chain wasn't added")
        security_group_chain = None
        for rule in self._out_rules:
            # This is pretty crude, but it'll do for now
            if '-A %s -j' % instance_chain in rule:
                security_group_chain = rule.split(' ')[-1]
                break
        self.assertTrue(security_group_chain,
                        "The security group chain wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p icmp -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "ICMP acceptance rule wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p icmp -m icmp --icmp-type 8'
                           ' -s 192.168.11.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "ICMP Echo Request acceptance rule wasn't added")

        regex = re.compile('-A .* -j ACCEPT -p tcp --dport 80:81'
                           ' -s 192.168.10.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "TCP port 80/81 acceptance rule wasn't added")

    def test_static_filters(self):
        instance_ref = self._create_instance_ref()
        src_instance_ref = self._create_instance_ref()
        admin_ctxt = context.get_admin_context()
        secgroup = self._create_test_security_group()

        src_secgroup = db.security_group_create(admin_ctxt,
                                                {'user_id': self.user_id,
                                                 'project_id': self.project_id,
                                                 'name': 'testsourcegroup',
                                                 'description': 'src group'})
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'tcp',
                                       'from_port': 80,
                                       'to_port': 81,
                                       'group_id': src_secgroup['id']})

        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        db.instance_add_security_group(admin_ctxt, src_instance_ref['uuid'],
                                       src_secgroup['id'])
        instance_ref = db.instance_get(admin_ctxt, instance_ref['id'])
        src_instance_ref = db.instance_get(admin_ctxt, src_instance_ref['id'])

        network_model = fake_network.fake_get_instance_nw_info(self.stubs,
                                                      1, spectacular=True)

        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs,
                                      lambda *a, **kw: network_model)

        network_info = compute_utils.legacy_network_info(network_model)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)

        self._validate_security_group()
        # Extra test for TCP acceptance rules
        for ip in network_model.fixed_ips():
            if ip['version'] != 4:
                continue
            regex = re.compile('-A .* -j ACCEPT -p tcp'
                               ' --dport 80:81 -s %s' % ip['address'])
            self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                            "TCP port 80/81 acceptance rule wasn't added")

        db.instance_destroy(admin_ctxt, instance_ref['id'])

    def test_filters_for_instance_with_ip_v6(self):
        self.flags(use_ipv6=True)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 1)

    def test_filters_for_instance_without_ip_v6(self):
        self.flags(use_ipv6=False)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1)
        rulesv4, rulesv6 = self.fw._filters_for_instance("fake", network_info)
        self.assertEquals(len(rulesv4), 2)
        self.assertEquals(len(rulesv6), 0)

    def test_multinic_iptables(self):
        ipv4_rules_per_addr = 1
        ipv4_addr_per_network = 2
        ipv6_rules_per_addr = 1
        ipv6_addr_per_network = 1
        networks_count = 5
        instance_ref = self._create_instance_ref()
        _get_instance_nw_info = fake_network.fake_get_instance_nw_info
        network_info = _get_instance_nw_info(self.stubs,
                                             networks_count,
                                             ipv4_addr_per_network)
        ipv4_len = len(self.fw.iptables.ipv4['filter'].rules)
        ipv6_len = len(self.fw.iptables.ipv6['filter'].rules)
        inst_ipv4, inst_ipv6 = self.fw.instance_rules(instance_ref,
                                                      network_info)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        ipv4 = self.fw.iptables.ipv4['filter'].rules
        ipv6 = self.fw.iptables.ipv6['filter'].rules
        ipv4_network_rules = len(ipv4) - len(inst_ipv4) - ipv4_len
        ipv6_network_rules = len(ipv6) - len(inst_ipv6) - ipv6_len
        self.assertEquals(ipv4_network_rules,
                  ipv4_rules_per_addr * ipv4_addr_per_network * networks_count)
        self.assertEquals(ipv6_network_rules,
                  ipv6_rules_per_addr * ipv6_addr_per_network * networks_count)

    def test_do_refresh_security_group_rules(self):
        admin_ctxt = context.get_admin_context()
        instance_ref = self._create_instance_ref()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)
        secgroup = self._create_test_security_group()
        db.instance_add_security_group(admin_ctxt, instance_ref['uuid'],
                                       secgroup['id'])
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.instances[instance_ref['id']] = instance_ref
        self._validate_security_group()
        # add a rule to the security group
        db.security_group_rule_create(admin_ctxt,
                                      {'parent_group_id': secgroup['id'],
                                       'protocol': 'udp',
                                       'from_port': 200,
                                       'to_port': 299,
                                       'cidr': '192.168.99.0/24'})
        #validate the extra rule
        self.fw.refresh_security_group_rules(secgroup)
        regex = re.compile('-A .* -j ACCEPT -p udp --dport 200:299'
                           ' -s 192.168.99.0/24')
        self.assertTrue(len(filter(regex.match, self._out_rules)) > 0,
                        "Rules were not updated properly."
                        "The rule for UDP acceptance is missing")

    def test_provider_firewall_rules(self):
        # setup basic instance data
        instance_ref = self._create_instance_ref()
        # FRAGILE: as in libvirt tests
        # peeks at how the firewall names chains
        chain_name = 'inst-%s' % instance_ref['id']

        network_info = fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.assertTrue('provider' in self.fw.iptables.ipv4['filter'].chains)
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(0, len(rules))

        admin_ctxt = context.get_admin_context()
        # add a rule and send the update message, check for 1 rule
        provider_fw0 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'tcp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))

        # Add another, refresh, and make sure number of rules goes to two
        provider_fw1 = db.provider_fw_rule_create(admin_ctxt,
                                                  {'protocol': 'udp',
                                                   'cidr': '10.99.99.99/32',
                                                   'from_port': 1,
                                                   'to_port': 65535})
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(2, len(rules))

        # create the instance filter and make sure it has a jump rule
        self.fw.prepare_instance_filter(instance_ref, network_info)
        self.fw.apply_instance_filter(instance_ref, network_info)
        inst_rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                           if rule.chain == chain_name]
        jump_rules = [rule for rule in inst_rules if '-j' in rule.rule]
        provjump_rules = []
        # IptablesTable doesn't make rules unique internally
        for rule in jump_rules:
            if 'provider' in rule.rule and rule not in provjump_rules:
                provjump_rules.append(rule)
        self.assertEqual(1, len(provjump_rules))

        # remove a rule from the db, cast to compute to refresh rule
        db.provider_fw_rule_destroy(admin_ctxt, provider_fw1['id'])
        self.fw.refresh_provider_fw_rules()
        rules = [rule for rule in self.fw.iptables.ipv4['filter'].rules
                      if rule.chain == 'provider']
        self.assertEqual(1, len(rules))


class XenAPISRSelectionTestCase(test.TestCase):
    """Unit tests for testing we find the right SR."""
    def setUp(self):
        super(XenAPISRSelectionTestCase, self).setUp()
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()

    def test_safe_find_sr_raise_exception(self):
        """Ensure StorageRepositoryNotFound is raise when wrong filter."""
        self.flags(sr_matching_filter='yadayadayada')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = vm_utils.VMHelper
        helper.XenAPI = session.get_imported_xenapi()
        self.assertRaises(exception.StorageRepositoryNotFound,
                          helper.safe_find_sr, session)

    def test_safe_find_sr_local_storage(self):
        """Ensure the default local-storage is found."""
        self.flags(sr_matching_filter='other-config:i18n-key=local-storage')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = vm_utils.VMHelper
        helper.XenAPI = session.get_imported_xenapi()
        host_ref = xenapi_fake.get_all('host')[0]
        local_sr = xenapi_fake.create_sr(
                              name_label='Fake Storage',
                              type='lvm',
                              other_config={'i18n-original-value-name_label':
                                            'Local storage',
                                            'i18n-key': 'local-storage'},
                              host_ref=host_ref)
        expected = helper.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_by_other_criteria(self):
        """Ensure the SR is found when using a different filter."""
        self.flags(sr_matching_filter='other-config:my_fake_sr=true')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = vm_utils.VMHelper
        helper.XenAPI = session.get_imported_xenapi()
        host_ref = xenapi_fake.get_all('host')[0]
        local_sr = xenapi_fake.create_sr(name_label='Fake Storage',
                                         type='lvm',
                                         other_config={'my_fake_sr': 'true'},
                                         host_ref=host_ref)
        expected = helper.safe_find_sr(session)
        self.assertEqual(local_sr, expected)

    def test_safe_find_sr_default(self):
        """Ensure the default SR is found regardless of other-config."""
        self.flags(sr_matching_filter='default-sr:true')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = vm_utils.VMHelper
        pool_ref = xenapi_fake.create_pool('')
        helper.XenAPI = session.get_imported_xenapi()
        expected = helper.safe_find_sr(session)
        self.assertEqual(session.call_xenapi('pool.get_default_SR', pool_ref),
                         expected)


class XenAPIAggregateTestCase(test.TestCase):
    """Unit tests for aggregate operations."""
    def setUp(self):
        super(XenAPIAggregateTestCase, self).setUp()
        self.flags(xenapi_connection_url='http://test_url',
                   xenapi_connection_username='test_user',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver',
                   host='host')
        xenapi_fake.reset()
        host_ref = xenapi_fake.get_all('host')[0]
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.context = context.get_admin_context()
        self.conn = xenapi_conn.get_connection(False)
        self.fake_metadata = {'master_compute': 'host',
                              'host': xenapi_fake.get_record('host',
                                                             host_ref)['uuid']}

    def test_add_to_aggregate_called(self):
        def fake_add_to_aggregate(context, aggregate, host):
            fake_add_to_aggregate.called = True
        self.stubs.Set(self.conn._pool,
                       "add_to_aggregate",
                       fake_add_to_aggregate)

        self.conn.add_to_aggregate(None, None, None)
        self.assertTrue(fake_add_to_aggregate.called)

    def test_add_to_aggregate_for_first_host_sets_metadata(self):
        def fake_init_pool(id, name):
            fake_init_pool.called = True
        self.stubs.Set(self.conn._pool, "_init_pool", fake_init_pool)

        aggregate = self._aggregate_setup()
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        result = db.aggregate_get(self.context, aggregate.id)
        self.assertTrue(fake_init_pool.called)
        self.assertDictMatch(self.fake_metadata, result.metadetails)
        self.assertEqual(aggregate_states.ACTIVE, result.operational_state)

    def test_join_slave(self):
        """Ensure join_slave gets called when the request gets to master."""
        def fake_join_slave(id, compute_uuid, host, url, user, password):
            fake_join_slave.called = True
        self.stubs.Set(self.conn._pool, "_join_slave", fake_join_slave)

        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)
        self.conn._pool.add_to_aggregate(self.context, aggregate, "host2",
                                         compute_uuid='fake_uuid',
                                         url='fake_url',
                                         user='fake_user',
                                         passwd='fake_pass',
                                         xenhost_uuid='fake_uuid')
        self.assertTrue(fake_join_slave.called)

    def test_add_to_aggregate_first_host(self):
        def fake_pool_set_name_label(self, session, pool_ref, name):
            fake_pool_set_name_label.called = True
        self.stubs.Set(xenapi_fake.SessionBase, "pool_set_name_label",
                       fake_pool_set_name_label)
        self.conn._session.call_xenapi("pool.create", {"name": "asdf"})

        values = {"name": 'fake_aggregate',
                  "availability_zone": 'fake_zone'}
        result = db.aggregate_create(self.context, values)
        db.aggregate_host_add(self.context, result.id, "host")
        aggregate = db.aggregate_get(self.context, result.id)
        self.assertEqual(["host"], aggregate.hosts)
        self.assertEqual({}, aggregate.metadetails)

        self.conn._pool.add_to_aggregate(self.context, aggregate, "host")
        self.assertTrue(fake_pool_set_name_label.called)

    def test_remove_from_aggregate_called(self):
        def fake_remove_from_aggregate(context, aggregate, host):
            fake_remove_from_aggregate.called = True
        self.stubs.Set(self.conn._pool,
                       "remove_from_aggregate",
                       fake_remove_from_aggregate)

        self.conn.remove_from_aggregate(None, None, None)
        self.assertTrue(fake_remove_from_aggregate.called)

    def test_remove_from_empty_aggregate(self):
        values = {"name": 'fake_aggregate',
                  "availability_zone": 'fake_zone'}
        result = db.aggregate_create(self.context, values)
        self.assertRaises(exception.AggregateError,
                          self.conn._pool.remove_from_aggregate,
                          None, result, "test_host")

    def test_remove_slave(self):
        """Ensure eject slave gets called."""
        def fake_eject_slave(id, compute_uuid, host_uuid):
            fake_eject_slave.called = True
        self.stubs.Set(self.conn._pool, "_eject_slave", fake_eject_slave)

        self.fake_metadata['host2'] = 'fake_host2_uuid'
        aggregate = self._aggregate_setup(hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host2")
        self.assertTrue(fake_eject_slave.called)

    def test_remove_master_solo(self):
        """Ensure metadata are cleared after removal."""
        def fake_clear_pool(id):
            fake_clear_pool.called = True
        self.stubs.Set(self.conn._pool, "_clear_pool", fake_clear_pool)

        aggregate = self._aggregate_setup(aggr_state=aggregate_states.ACTIVE,
                                          metadata=self.fake_metadata)
        self.conn._pool.remove_from_aggregate(self.context, aggregate, "host")
        result = db.aggregate_get(self.context, aggregate.id)
        self.assertTrue(fake_clear_pool.called)
        self.assertDictMatch({}, result.metadetails)
        self.assertEqual(aggregate_states.ACTIVE, result.operational_state)

    def test_remote_master_non_empty_pool(self):
        """Ensure AggregateError is raised if removing the master."""
        aggregate = self._aggregate_setup(aggr_state=aggregate_states.ACTIVE,
                                          hosts=['host', 'host2'],
                                          metadata=self.fake_metadata)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.conn._pool.remove_from_aggregate,
                          self.context, aggregate, "host")

    def _aggregate_setup(self, aggr_name='fake_aggregate',
                         aggr_zone='fake_zone',
                         aggr_state=aggregate_states.CREATED,
                         hosts=['host'], metadata=None):
        values = {"name": aggr_name,
                  "availability_zone": aggr_zone,
                  "operational_state": aggr_state, }
        result = db.aggregate_create(self.context, values)
        for host in hosts:
            db.aggregate_host_add(self.context, result.id, host)
        if metadata:
            db.aggregate_metadata_add(self.context, result.id, metadata)
        return db.aggregate_get(self.context, result.id)
