# Copyright 2011 OpenStack LLC.
# aLL Rights Reserved.
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

from lxml import etree
import webob

from nova.api.openstack.volume import types
from nova import exception
from nova import test
from nova import log as logging
from nova.volume import volume_types
from nova.tests.api.openstack import fakes


LOG = logging.getLogger(__name__)
last_param = {}


def stub_volume_type(id):
    specs = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5"}
    return dict(id=id, name='vol_type_%s' % str(id), extra_specs=specs)


def return_volume_types_get_all_types(context):
    return dict(vol_type_1=stub_volume_type(1),
                vol_type_2=stub_volume_type(2),
                vol_type_3=stub_volume_type(3))


def return_empty_volume_types_get_all_types(context):
    return {}


def return_volume_types_get_volume_type(context, id):
    if id == "777":
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return stub_volume_type(int(id))


def return_volume_types_destroy(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    pass


def return_volume_types_create(context, name, specs):
    pass


def return_volume_types_get_by_name(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    return stub_volume_type(int(name.split("_")[2]))


class VolumeTypesApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.controller = types.VolumeTypesController()

    def test_volume_types_index(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/123/os-volume-types')
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['volume_types']))

        expected_names = ['vol_type_1', 'vol_type_2', 'vol_type_3']
        actual_names = map(lambda e: e['name'], res_dict['volume_types'])
        self.assertEqual(set(actual_names), set(expected_names))
        for entry in res_dict['volume_types']:
            self.assertEqual('value1', entry['extra_specs']['key1'])

    def test_volume_types_index_no_data(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_empty_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/123/os-volume-types')
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['volume_types']))

    def test_volume_types_show(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        req = fakes.HTTPRequest.blank('/v2/123/os-volume-types/1')
        res_dict = self.controller.show(req, 1)

        self.assertEqual(1, len(res_dict))
        self.assertEqual('1', res_dict['volume_type']['id'])
        self.assertEqual('vol_type_1', res_dict['volume_type']['name'])

    def test_volume_types_show_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        req = fakes.HTTPRequest.blank('/v2/123/os-volume-types/777')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, '777')


class VolumeTypesSerializerTest(test.TestCase):
    def _verify_volume_type(self, vtype, tree):
        self.assertEqual('volume_type', tree.tag)
        self.assertEqual(vtype['name'], tree.get('name'))
        self.assertEqual(str(vtype['id']), tree.get('id'))
        self.assertEqual(1, len(tree))
        extra_specs = tree[0]
        self.assertEqual('extra_specs', extra_specs.tag)
        seen = set(vtype['extra_specs'].keys())
        for child in extra_specs:
            self.assertTrue(child.tag in seen)
            self.assertEqual(vtype['extra_specs'][child.tag], child.text)
            seen.remove(child.tag)
        self.assertEqual(len(seen), 0)

    def test_index_serializer(self):
        serializer = types.VolumeTypesTemplate()

        # Just getting some input data
        vtypes = return_volume_types_get_all_types(None)
        text = serializer.serialize({'volume_types': vtypes.values()})

        print text
        tree = etree.fromstring(text)

        self.assertEqual('volume_types', tree.tag)
        self.assertEqual(len(vtypes), len(tree))
        for child in tree:
            name = child.get('name')
            self.assertTrue(name in vtypes)
            self._verify_volume_type(vtypes[name], child)

    def test_voltype_serializer(self):
        serializer = types.VolumeTypeTemplate()

        vtype = stub_volume_type(1)
        text = serializer.serialize(dict(volume_type=vtype))

        print text
        tree = etree.fromstring(text)

        self._verify_volume_type(vtype, tree)
