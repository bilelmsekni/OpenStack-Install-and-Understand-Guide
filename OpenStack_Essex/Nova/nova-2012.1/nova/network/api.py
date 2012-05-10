# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from nova.db import base
from nova import exception
from nova import flags
from nova import log as logging
from nova.network import model as network_model
from nova import rpc
from nova.rpc import common as rpc_common


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for interacting with the network manager."""

    def get_all(self, context):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_all_networks'})

    def get(self, context, network_uuid):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_network',
                         'args': {'network_uuid': network_uuid}})

    def delete(self, context, network_uuid):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'delete_network',
                         'args': {'fixed_range': None,
                                  'uuid': network_uuid}})

    def disassociate(self, context, network_uuid):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'disassociate_network',
                         'args': {'network_uuid': network_uuid}})

    def get_fixed_ip(self, context, id):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_fixed_ip',
                         'args': {'id': id}})

    def get_fixed_ip_by_address(self, context, address):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_fixed_ip_by_address',
                         'args': {'address': address}})

    def get_floating_ip(self, context, id):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_floating_ip',
                         'args': {'id': id}})

    def get_floating_ip_pools(self, context):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_floating_pools'})

    def get_floating_ip_by_address(self, context, address):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_floating_ip_by_address',
                         'args': {'address': address}})

    def get_floating_ips_by_project(self, context):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_floating_ips_by_project'})

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_floating_ips_by_fixed_address',
                         'args': {'fixed_address': fixed_address}})

    def get_vifs_by_instance(self, context, instance):
        # NOTE(vish): When the db calls are converted to store network
        #             data by instance_uuid, this should pass uuid instead.
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_vifs_by_instance',
                         'args': {'instance_id': instance['id']}})

    def get_vif_by_mac_address(self, context, mac_address):
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_vif_by_mac_address',
                         'args': {'mac_address': mac_address}})

    def allocate_floating_ip(self, context, pool=None):
        """Adds a floating ip to a project from a pool. (allocates)"""
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'allocate_floating_ip',
                         'args': {'project_id': context.project_id,
                                  'pool': pool}})

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes floating ip with address from a project. (deallocates)"""
        rpc.cast(context,
                 FLAGS.network_topic,
                 {'method': 'deallocate_floating_ip',
                  'args': {'address': address,
                           'affect_auto_assigned': affect_auto_assigned}})

    def associate_floating_ip(self, context, floating_address, fixed_address,
                                                 affect_auto_assigned=False):
        """Associates a floating ip with a fixed ip.

        ensures floating ip is allocated to the project in context
        """
        rpc.call(context,
                 FLAGS.network_topic,
                 {'method': 'associate_floating_ip',
                  'args': {'floating_address': floating_address,
                           'fixed_address': fixed_address,
                           'affect_auto_assigned': affect_auto_assigned}})

    def disassociate_floating_ip(self, context, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating ip from fixed ip it is associated with."""
        rpc.cast(context,
                 FLAGS.network_topic,
                 {'method': 'disassociate_floating_ip',
                  'args': {'address': address}})

    def allocate_for_instance(self, context, instance, **kwargs):
        """Allocates all network structures for an instance.

        :returns: network info as from get_instance_nw_info() below
        """
        args = kwargs
        args['instance_id'] = instance['id']
        args['instance_uuid'] = instance['uuid']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        args['rxtx_factor'] = instance['instance_type']['rxtx_factor']

        nw_info = rpc.call(context, FLAGS.network_topic,
                           {'method': 'allocate_for_instance',
                             'args': args})

        return network_model.NetworkInfo.hydrate(nw_info)

    def deallocate_for_instance(self, context, instance, **kwargs):
        """Deallocates all network structures related to instance."""
        args = kwargs
        args['instance_id'] = instance['id']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'deallocate_for_instance',
                  'args': args})

    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Adds a fixed ip to instance from specified network."""
        args = {'instance_id': instance['id'],
                'host': instance['host'],
                'network_id': network_id}
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'add_fixed_ip_to_instance',
                  'args': args})

    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Removes a fixed ip from instance from specified network."""

        args = {'instance_id': instance['id'],
                'host': instance['host'],
                'address': address}
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'remove_fixed_ip_from_instance',
                  'args': args})

    def add_network_to_project(self, context, project_id):
        """Force adds another network to a project."""
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'add_network_to_project',
                  'args': {'project_id': project_id}})

    def get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        args = {'instance_id': instance['id'],
                'instance_uuid': instance['uuid'],
                'rxtx_factor': instance['instance_type']['rxtx_factor'],
                'host': instance['host'],
                'project_id': instance['project_id']}
        try:
            nw_info = rpc.call(context, FLAGS.network_topic,
                               {'method': 'get_instance_nw_info',
                                'args': args})
            return network_model.NetworkInfo.hydrate(nw_info)
        # FIXME(comstud) rpc calls raise RemoteError if the remote raises
        # an exception.  In the case here, because of a race condition,
        # it's possible the remote will raise a InstanceNotFound when
        # someone deletes the instance while this call is in progress.
        #
        # Unfortunately, we don't have access to the original exception
        # class now.. but we do have the exception class's name.  So,
        # we're checking it here and raising a new exception.
        #
        # Ultimately we need RPC to be able to serialize more things like
        # classes.
        except rpc_common.RemoteError as err:
            if err.exc_type == 'InstanceNotFound':
                raise exception.InstanceNotFound(instance_id=instance['id'])
            raise

    def validate_networks(self, context, requested_networks):
        """validate the networks passed at the time of creating
        the server
        """
        args = {'networks': requested_networks}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'validate_networks',
                         'args': args})

    def get_instance_uuids_by_ip_filter(self, context, filters):
        """Returns a list of dicts in the form of
        {'instance_uuid': uuid, 'ip': ip} that matched the ip_filter
        """
        args = {'filters': filters}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'get_instance_uuids_by_ip_filter',
                         'args': args})

    def get_dns_domains(self, context):
        """Returns a list of available dns domains.
        These can be used to create DNS entries for floating ips.
        """
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'get_dns_domains'})

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address"""
        args = {'address': address,
                'name': name,
                'dns_type': dns_type,
                'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'add_dns_entry',
                         'args': args})

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address"""
        args = {'address': address,
                'name': name,
                'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'modify_dns_entry',
                         'args': args})

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        args = {'name': name, 'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'delete_dns_entry',
                         'args': args})

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        args = {'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'delete_dns_domain',
                         'args': args})

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain"""
        args = {'address': address, 'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'get_dns_entries_by_address',
                         'args': args})

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain"""
        args = {'name': name, 'domain': domain}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'get_dns_entries_by_name',
                         'args': args})

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        args = {'domain': domain, 'av_zone': availability_zone}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'create_private_dns_domain',
                         'args': args})

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a private DNS domain with optional nova project."""
        args = {'domain': domain, 'project': project}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'create_public_dns_domain',
                         'args': args})

    def setup_networks_on_host(self, context, instance, host=None,
                                                        teardown=False):
        """Setup or teardown the network structures on hosts related to
           instance"""
        host = host or instance['host']
        # NOTE(tr3buchet): host is passed in cases where we need to setup
        # or teardown the networks on a host which has been migrated to/from
        # and instance['host'] is not yet or is no longer equal to
        args = {'instance_id': instance['id'],
                'host': host,
                'teardown': teardown}

        # NOTE(tr3buchet): the call is just to wait for completion
        rpc.call(context, FLAGS.network_topic,
                 {'method': 'setup_networks_on_host',
                  'args': args})
