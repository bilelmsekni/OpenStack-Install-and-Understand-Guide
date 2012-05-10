# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

import datetime
import json

import webob

from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
from nova.compute import instance_types
from nova.api.openstack.compute.contrib import flavormanage


def fake_get_instance_type_by_flavor_id(flavorid):
    if flavorid == 'failtest':
        raise exception.NotFound("Not found sucka!")
    elif not str(flavorid) == '1234':
        raise Exception("This test expects flavorid 1234, not %s" % flavorid)

    return {
        'root_gb': 1,
        'ephemeral_gb': 1,
        'name': u'frob',
        'deleted': False,
        'created_at': datetime.datetime(2012, 1, 19, 18, 49, 30, 877329),
        'updated_at': None,
        'memory_mb': 256,
        'vcpus': 1,
        'flavorid': flavorid,
        'swap': 0,
        'rxtx_factor': 1.0,
        'extra_specs': {},
        'deleted_at': None,
        'vcpu_weight': None,
        'id': 7
    }


def fake_destroy(flavorname):
    pass


def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                flavorid, swap, rxtx_factor):
    newflavor = fake_get_instance_type_by_flavor_id(flavorid)

    newflavor["name"] = name
    newflavor["memory_mb"] = int(memory_mb)
    newflavor["vcpus"] = int(vcpus)
    newflavor["root_gb"] = int(root_gb)
    newflavor["ephemeral_gb"] = int(ephemeral_gb)
    newflavor["swap"] = swap
    newflavor["rxtx_factor"] = float(rxtx_factor)

    return newflavor


class FlavorManageTest(test.TestCase):
    def setUp(self):
        super(FlavorManageTest, self).setUp()
        self.stubs.Set(instance_types,
                       "get_instance_type_by_flavor_id",
                       fake_get_instance_type_by_flavor_id)
        self.stubs.Set(instance_types, "destroy", fake_destroy)
        self.stubs.Set(instance_types, "create", fake_create)

        self.controller = flavormanage.FlavorManageController()

    def test_delete(self):
        req = fakes.HTTPRequest.blank('/v2/123/flavors/1234')
        res = self.controller._delete(req, 1234)
        self.assertEqual(res.status_int, 202)

        # subsequent delete should fail
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._delete, req, "failtest")

    def test_create(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": 1234,
                "swap": 512,
                "rxtx_factor": 1,
            }
        }

        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        body = json.loads(res.body)
        for key in expected["flavor"]:
            self.assertEquals(body["flavor"][key], expected["flavor"][key])

    def test_instance_type_exists_exception_returns_409(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": 1235,
                "swap": 512,
                "rxtx_factor": 1,
            }
        }

        def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                        flavorid, swap, rxtx_factor):
            raise exception.InstanceTypeExists()

        self.stubs.Set(instance_types, "create", fake_create)
        url = '/v2/fake/flavors'
        req = webob.Request.blank(url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(expected)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 409)
