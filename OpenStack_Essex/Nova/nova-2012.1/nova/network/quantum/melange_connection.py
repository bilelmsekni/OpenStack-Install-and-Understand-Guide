# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import httplib
import json
import socket
import time
import urllib

from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg


melange_opts = [
    cfg.StrOpt('melange_host',
               default='127.0.0.1',
               help='HOST for connecting to melange'),
    cfg.IntOpt('melange_port',
               default=9898,
               help='PORT for connecting to melange'),
    cfg.IntOpt('melange_num_retries',
               default=0,
               help='Number retries when contacting melange'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(melange_opts)
LOG = logging.getLogger(__name__)

json_content_type = {'Content-type': "application/json"}


# FIXME(danwent): talk to the Melange folks about creating a
# client lib that we can import as a library, instead of
# have to have all of the client code in here.
class MelangeConnection(object):

    def __init__(self, host=None, port=None, use_ssl=False):
        if host is None:
            host = FLAGS.melange_host
        if port is None:
            port = FLAGS.melange_port
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.version = "v0.1"

    def get(self, path, params=None, headers=None):
        return self.do_request("GET", path, params=params, headers=headers,
                               retries=FLAGS.melange_num_retries)

    def post(self, path, body=None, headers=None):
        return self.do_request("POST", path, body=body, headers=headers)

    def delete(self, path, headers=None):
        return self.do_request("DELETE", path, headers=headers)

    def _get_connection(self):
        if self.use_ssl:
            return httplib.HTTPSConnection(self.host, self.port)
        else:
            return httplib.HTTPConnection(self.host, self.port)

    def do_request(self, method, path, body=None, headers=None, params=None,
                   content_type=".json", retries=0):
        headers = headers or {}
        params = params or {}

        url = "/%s/%s%s" % (self.version, path, content_type)
        if params:
            url += "?%s" % urllib.urlencode(params)
        for i in xrange(retries + 1):
            connection = self._get_connection()
            try:
                connection.request(method, url, body, headers)
                response = connection.getresponse()
                response_str = response.read()
                if response.status < 400:
                    return response_str
                raise Exception(_("Server returned error: %s") % response_str)
            except (socket.error, IOError), e:
                LOG.exception(_('Connection error contacting melange'
                                ' service, retrying'))

                time.sleep(1)

        raise exception.MelangeConnectionFailed(
                reason=_("Maximum attempts reached"))

    def allocate_ip(self, network_id, network_tenant_id, vif_id,
                    project_id=None, mac_address=None):
        LOG.info(_("allocate IP on network |%(network_id)s| "
                   "belonging to |%(network_tenant_id)s| "
                   "to this vif |%(vif_id)s| with mac |%(mac_address)s| "
                   "belonging to |%(project_id)s| ") % locals())
        tenant_scope = "/tenants/%s" % (network_tenant_id
                                        if network_tenant_id else "")
        request_body = (json.dumps(dict(network=dict(mac_address=mac_address,
                                                     tenant_id=project_id)))
                    if mac_address else None)
        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
               "interfaces/%(vif_id)s/ip_allocations" % locals())
        response = self.post(url, body=request_body, headers=json_content_type)
        return json.loads(response)['ip_addresses']

    def create_block(self, network_id, cidr,
                     project_id=None, gateway=None, dns1=None, dns2=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks" % locals()

        req_params = dict(ip_block=dict(cidr=cidr, network_id=network_id,
                                        type='private', gateway=gateway,
                                        dns1=dns1, dns2=dns2))
        self.post(url, body=json.dumps(req_params), headers=json_content_type)

    def delete_block(self, block_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks/%(block_id)s" % locals()

        self.delete(url, headers=json_content_type)

    def get_blocks(self, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks" % locals()

        response = self.get(url, headers=json_content_type)
        return json.loads(response)

    def get_routes(self, block_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = ("ipam%(tenant_scope)s/ip_blocks/%(block_id)s/ip_routes" %
               locals())

        response = self.get(url, headers=json_content_type)
        return json.loads(response)['ip_routes']

    def get_allocated_ips(self, network_id, vif_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
               "interfaces/%(vif_id)s/ip_allocations" % locals())

        response = self.get(url, headers=json_content_type)
        return json.loads(response)['ip_addresses']

    def get_allocated_ips_for_network(self, network_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""
        url = ("ipam%(tenant_scope)s/allocated_ip_addresses" % locals())
        # TODO(bgh): This request fails if you add the ".json" to the end so
        # it has to call do_request itself.  Melange bug?
        response = self.do_request("GET", url, content_type="")
        return json.loads(response)['ip_addresses']

    def deallocate_ips(self, network_id, vif_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
               "interfaces/%(vif_id)s/ip_allocations" % locals())

        self.delete(url, headers=json_content_type)

    def create_vif(self, vif_id, instance_id, project_id=None):
        url = "ipam/interfaces"

        request_body = dict(interface=dict(id=vif_id, tenant_id=project_id,
                                           device_id=instance_id))

        response = self.post(url, body=json.dumps(request_body),
                             headers=json_content_type)

        return json.loads(response)['interface']['mac_address']
