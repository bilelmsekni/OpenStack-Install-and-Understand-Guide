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

import json

import webob

from nova import compute
from nova import test
from nova.tests.api.openstack import fakes


UUID = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
last_add_fixed_ip = (None, None)
last_remove_fixed_ip = (None, None)


def compute_api_add_fixed_ip(self, context, instance, network_id):
    global last_add_fixed_ip

    last_add_fixed_ip = (instance['uuid'], network_id)


def compute_api_remove_fixed_ip(self, context, instance, address):
    global last_remove_fixed_ip

    last_remove_fixed_ip = (instance['uuid'], address)


def compute_api_get(self, context, instance_id):
    return {'id': 1, 'uuid': instance_id}


class FixedIpTest(test.TestCase):
    def setUp(self):
        super(FixedIpTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(compute.api.API, "add_fixed_ip",
                       compute_api_add_fixed_ip)
        self.stubs.Set(compute.api.API, "remove_fixed_ip",
                       compute_api_remove_fixed_ip)
        self.stubs.Set(compute.api.API, 'get', compute_api_get)

    def test_add_fixed_ip(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict(networkId='test_net'))
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(last_add_fixed_ip, (UUID, 'test_net'))

    def test_add_fixed_ip_no_network(self):
        global last_add_fixed_ip
        last_add_fixed_ip = (None, None)

        body = dict(addFixedIp=dict())
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 422)
        self.assertEqual(last_add_fixed_ip, (None, None))

    def test_remove_fixed_ip(self):
        global last_remove_fixed_ip
        last_remove_fixed_ip = (None, None)

        body = dict(removeFixedIp=dict(address='10.10.10.1'))
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertEqual(last_remove_fixed_ip, (UUID, '10.10.10.1'))

    def test_remove_fixed_ip_no_address(self):
        global last_remove_fixed_ip
        last_remove_fixed_ip = (None, None)

        body = dict(removeFixedIp=dict())
        req = webob.Request.blank('/v2/fake/servers/%s/action' % UUID)
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 422)
        self.assertEqual(last_remove_fixed_ip, (None, None))
