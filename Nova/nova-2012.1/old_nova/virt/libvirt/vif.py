# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
# Copyright (C) 2011 Nicira, Inc
# Copyright 2011 OpenStack LLC.
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

"""VIF drivers for libvirt."""

from nova import exception
from nova import flags
from nova import log as logging
from nova.network import linux_net
from nova.openstack.common import cfg
from nova import utils
from nova.virt import netutils
from nova.virt import vif


LOG = logging.getLogger(__name__)

libvirt_ovs_bridge_opt = cfg.StrOpt('libvirt_ovs_bridge',
        default='br-int',
        help='Name of Integration Bridge used by Open vSwitch')

FLAGS = flags.FLAGS
FLAGS.register_opt(libvirt_ovs_bridge_opt)


class LibvirtBridgeDriver(vif.VIFDriver):
    """VIF driver for Linux bridge."""

    def _get_configurations(self, network, mapping):
        """Get a dictionary of VIF configurations for bridge type."""
        # Assume that the gateway also acts as the dhcp server.
        gateway_v6 = mapping.get('gateway_v6')
        mac_id = mapping['mac'].replace(':', '')

        if FLAGS.allow_same_net_traffic:
            template = "<parameter name=\"%s\" value=\"%s\" />\n"
            net, mask = netutils.get_net_and_mask(network['cidr'])
            values = [("PROJNET", net), ("PROJMASK", mask)]
            if FLAGS.use_ipv6:
                net_v6, prefixlen_v6 = netutils.get_net_and_prefixlen(
                                           network['cidr_v6'])
                values.extend([("PROJNETV6", net_v6),
                               ("PROJMASKV6", prefixlen_v6)])

            extra_params = "".join([template % value for value in values])
        else:
            extra_params = "\n"

        result = {
            'id': mac_id,
            'bridge_name': network['bridge'],
            'mac_address': mapping['mac'],
            'ip_address': mapping['ips'][0]['ip'],
            'dhcp_server': mapping['dhcp_server'],
            'extra_params': extra_params,
        }

        if gateway_v6:
            result['gateway_v6'] = gateway_v6 + "/128"

        return result

    def plug(self, instance, network, mapping):
        """Ensure that the bridge exists, and add VIF to it."""
        if (not network.get('multi_host') and
            mapping.get('should_create_bridge')):
            if mapping.get('should_create_vlan'):
                iface = FLAGS.vlan_interface or network['bridge_interface']
                LOG.debug(_('Ensuring vlan %(vlan)s and bridge %(bridge)s'),
                          {'vlan': network['vlan'],
                           'bridge': network['bridge']})
                linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                                             network['vlan'],
                                             network['bridge'],
                                             iface)
            else:
                iface = FLAGS.flat_interface or network['bridge_interface']
                LOG.debug(_("Ensuring bridge %s"), network['bridge'])
                linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                                        network['bridge'],
                                        iface)

        return self._get_configurations(network, mapping)

    def unplug(self, instance, network, mapping):
        """No manual unplugging required."""
        pass


class LibvirtOpenVswitchDriver(vif.VIFDriver):
    """VIF driver for Open vSwitch that uses type='ethernet'
       libvirt XML.  Used for libvirt versions that do not support
       OVS virtual port XML (0.9.10 or earlier)."""

    def get_dev_name(_self, iface_id):
        return "tap" + iface_id[0:11]

    def plug(self, instance, network, mapping):
        iface_id = mapping['vif_uuid']
        dev = self.get_dev_name(iface_id)
        if not linux_net._device_exists(dev):
            # Older version of the command 'ip' from the iproute2 package
            # don't have support for the tuntap option (lp:882568).  If it
            # turns out we're on an old version we work around this by using
            # tunctl.
            try:
                # First, try with 'ip'
                utils.execute('ip', 'tuntap', 'add', dev, 'mode', 'tap',
                          run_as_root=True)
            except exception.ProcessExecutionError:
                # Second option: tunctl
                utils.execute('tunctl', '-b', '-t', dev, run_as_root=True)
            utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
        utils.execute('ovs-vsctl', '--', '--may-exist', 'add-port',
                FLAGS.libvirt_ovs_bridge, dev,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-id=%s" % iface_id,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-status=active",
                '--', 'set', 'Interface', dev,
                "external-ids:attached-mac=%s" % mapping['mac'],
                '--', 'set', 'Interface', dev,
                "external-ids:vm-uuid=%s" % instance['uuid'],
                run_as_root=True)

        result = {
            'script': '',
            'name': dev,
            'mac_address': mapping['mac']}
        return result

    def unplug(self, instance, network, mapping):
        """Unplug the VIF from the network by deleting the port from
        the bridge."""
        dev = self.get_dev_name(mapping['vif_uuid'])
        try:
            utils.execute('ovs-vsctl', 'del-port',
                          FLAGS.libvirt_ovs_bridge, dev, run_as_root=True)
            utils.execute('ip', 'link', 'delete', dev, run_as_root=True)
        except exception.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif of instance '%s'"),
                        instance['name'])


class LibvirtOpenVswitchVirtualPortDriver(vif.VIFDriver):
    """VIF driver for Open vSwitch that uses integrated libvirt
       OVS virtual port XML (introduced in libvirt 0.9.11)."""

    def plug(self, instance, network, mapping):
        """ Pass data required to create OVS virtual port element"""
        return {
            'bridge_name': FLAGS.libvirt_ovs_bridge,
            'ovs_interfaceid': mapping['vif_uuid'],
            'mac_address': mapping['mac']}

    def unplug(self, instance, network, mapping):
        """No action needed.  Libvirt takes care of cleanup"""
        pass


class QuantumLinuxBridgeVIFDriver(vif.VIFDriver):
    """VIF driver for Linux Bridge when running Quantum."""

    def get_dev_name(self, iface_id):
        return "tap" + iface_id[0:11]

    def plug(self, instance, network, mapping):
        iface_id = mapping['vif_uuid']
        dev = self.get_dev_name(iface_id)
        linux_net.QuantumLinuxBridgeInterfaceDriver.create_tap_dev(dev)

        result = {
            'script': '',
            'name': dev,
            'mac_address': mapping['mac']}
        return result

    def unplug(self, instance, network, mapping):
        """Unplug the VIF from the network by deleting the port from
        the bridge."""
        dev = self.get_dev_name(mapping['vif_uuid'])
        try:
            utils.execute('ip', 'link', 'delete', dev, run_as_root=True)
        except exception.ProcessExecutionError:
            LOG.warning(_("Failed while unplugging vif of instance '%s'"),
                        instance['name'])
            raise
