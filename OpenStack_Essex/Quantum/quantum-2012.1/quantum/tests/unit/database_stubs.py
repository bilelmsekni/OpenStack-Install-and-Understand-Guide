# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011, Cisco Systems, Inc.
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
# @author: Rohit Agarwalla, Cisco Systems, Inc.

"""
stubs.py provides interface methods for
the database test cases
"""
import logging
import unittest

from quantum.db import api as db


LOG = logging.getLogger('quantum.tests.database_stubs')


class QuantumDB(object):
    """Class conisting of methods to call Quantum db methods"""
    def get_all_networks(self, tenant_id):
        """Get all networks"""
        nets = []
        try:
            for net in db.network_list(tenant_id):
                LOG.debug("Getting network: %s", net.uuid)
                net_dict = {}
                net_dict["tenant_id"] = net.tenant_id
                net_dict["id"] = str(net.uuid)
                net_dict["name"] = net.name
                nets.append(net_dict)
        except Exception, exc:
            LOG.error("Failed to get all networks: %s", str(exc))
        return nets

    def get_network(self, network_id):
        """Get a network"""
        net = []
        try:
            for net in db.network_get(network_id):
                LOG.debug("Getting network: %s", net.uuid)
                net_dict = {}
                net_dict["tenant_id"] = net.tenant_id
                net_dict["id"] = str(net.uuid)
                net_dict["name"] = net.name
                net.append(net_dict)
        except Exception, exc:
            LOG.error("Failed to get network: %s", str(exc))
        return net

    def create_network(self, tenant_id, net_name):
        """Create a network"""
        net_dict = {}
        try:
            res = db.network_create(tenant_id, net_name)
            LOG.debug("Created network: %s", res.uuid)
            net_dict["tenant_id"] = res.tenant_id
            net_dict["id"] = str(res.uuid)
            net_dict["name"] = res.name
            return net_dict
        except Exception, exc:
            LOG.error("Failed to create network: %s", str(exc))

    def delete_network(self, net_id):
        """Delete a network"""
        try:
            net = db.network_destroy(net_id)
            LOG.debug("Deleted network: %s", net.uuid)
            net_dict = {}
            net_dict["id"] = str(net.uuid)
            return net_dict
        except Exception, exc:
            LOG.error("Failed to delete network: %s", str(exc))

    def update_network(self, tenant_id, net_id, param_data):
        """Rename a network"""
        try:
            print param_data
            net = db.network_update(net_id, tenant_id, **param_data)
            LOG.debug("Updated network: %s", net.uuid)
            net_dict = {}
            net_dict["id"] = str(net.uuid)
            net_dict["name"] = net.name
            return net_dict
        except Exception, exc:
            LOG.error("Failed to update network: %s", str(exc))

    def get_all_ports(self, net_id):
        """Get all ports"""
        ports = []
        try:
            for port in db.port_list(net_id):
                LOG.debug("Getting port: %s", port.uuid)
                port_dict = {}
                port_dict["id"] = str(port.uuid)
                port_dict["net-id"] = str(port.network_id)
                port_dict["attachment"] = port.interface_id
                port_dict["state"] = port.state
                ports.append(port_dict)
            return ports
        except Exception, exc:
            LOG.error("Failed to get all ports: %s", str(exc))

    def get_port(self, net_id, port_id):
        """Get a port"""
        port_list = []
        port = db.port_get(port_id, net_id)
        try:
            LOG.debug("Getting port: %s", port.uuid)
            port_dict = {}
            port_dict["id"] = str(port.uuid)
            port_dict["net-id"] = str(port.network_id)
            port_dict["attachment"] = port.interface_id
            port_dict["state"] = port.state
            port_list.append(port_dict)
            return port_list
        except Exception, exc:
            LOG.error("Failed to get port: %s", str(exc))

    def create_port(self, net_id):
        """Add a port"""
        port_dict = {}
        try:
            port = db.port_create(net_id)
            LOG.debug("Creating port %s", port.uuid)
            port_dict["id"] = str(port.uuid)
            port_dict["net-id"] = str(port.network_id)
            port_dict["attachment"] = port.interface_id
            port_dict["state"] = port.state
            return port_dict
        except Exception, exc:
            LOG.error("Failed to create port: %s", str(exc))

    def delete_port(self, net_id, port_id):
        """Delete a port"""
        try:
            port = db.port_destroy(port_id, net_id)
            LOG.debug("Deleted port %s", port.uuid)
            port_dict = {}
            port_dict["id"] = str(port.uuid)
            return port_dict
        except Exception, exc:
            LOG.error("Failed to delete port: %s", str(exc))

    def update_port(self, net_id, port_id, **kwargs):
        """Update a port"""
        try:
            port = db.port_set_state(net_id, port_id, **kwargs)
            LOG.debug("Updated port %s", port.uuid)
            port_dict = {}
            port_dict["id"] = str(port.uuid)
            port_dict["net-id"] = str(port.network_id)
            port_dict["attachment"] = port.interface_id
            port_dict["state"] = port.state
            return port_dict
        except Exception, exc:
            LOG.error("Failed to update port state: %s", str(exc))

    def plug_interface(self, net_id, port_id, int_id):
        """Plug interface to a port"""
        try:
            port = db.port_set_attachment(port_id, net_id, int_id)
            LOG.debug("Attached interface to port %s", port.uuid)
            port_dict = {}
            port_dict["id"] = str(port.uuid)
            port_dict["net-id"] = str(port.network_id)
            port_dict["attachment"] = port.interface_id
            port_dict["state"] = port.state
            return port_dict
        except Exception, exc:
            LOG.error("Failed to plug interface: %s", str(exc))

    def unplug_interface(self, net_id, port_id):
        """Unplug interface to a port"""
        try:
            db.port_unset_attachment(port_id, net_id)
            LOG.debug("Detached interface from port %s", port_id)
        except Exception, exc:
            LOG.error("Failed to unplug interface: %s", str(exc))
