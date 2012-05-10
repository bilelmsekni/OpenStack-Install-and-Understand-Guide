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
from lxml import etree

from nova.api.openstack.compute.contrib import extended_server_attributes
from nova import compute
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS


UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    return fakes.stub_instance(1, uuid=UUID3, host="host-fake")


def fake_compute_get_all(*args, **kwargs):
    return [
        fakes.stub_instance(1, uuid=UUID1, host="host-1"),
        fakes.stub_instance(2, uuid=UUID2, host="host-2")
    ]


class ExtendedServerAttributesTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-SRV-ATTR:'

    def setUp(self):
        super(ExtendedServerAttributesTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app())
        return res

    def _get_server(self, body):
        return json.loads(body).get('server')

    def _get_servers(self, body):
        return json.loads(body).get('servers')

    def assertServerAttributes(self, server, host, instance_name):
        self.assertEqual(server.get('%shost' % self.prefix), host)
        self.assertEqual(server.get('%sinstance_name' % self.prefix),
                         instance_name)

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerAttributes(self._get_server(res.body),
                                host='host-fake',
                                instance_name='instance-1')

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerAttributes(server,
                                    host='host-%s' % (i + 1),
                                    instance_name='instance-%s' % (i + 1))

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound()

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        url = '/v2/fake/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class ExtendedServerAttributesXmlTest(ExtendedServerAttributesTest):
    content_type = 'application/xml'
    ext = extended_server_attributes
    prefix = '{%s}' % ext.Extended_server_attributes.namespace

    def _get_server(self, body):
        return etree.XML(body)

    def _get_servers(self, body):
        return etree.XML(body).getchildren()
