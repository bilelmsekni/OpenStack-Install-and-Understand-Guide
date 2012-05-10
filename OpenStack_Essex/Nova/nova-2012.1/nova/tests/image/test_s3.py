# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Isaku Yamahata
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

import os

from nova import context
import nova.db.api
from nova import exception
from nova import test
from nova.image import s3


ami_manifest_xml = """<?xml version="1.0" ?>
<manifest>
        <version>2011-06-17</version>
        <bundler>
                <name>test-s3</name>
                <version>0</version>
                <release>0</release>
        </bundler>
        <machine_configuration>
                <architecture>x86_64</architecture>
                <block_device_mapping>
                        <mapping>
                                <virtual>ami</virtual>
                                <device>sda1</device>
                        </mapping>
                        <mapping>
                                <virtual>root</virtual>
                                <device>/dev/sda1</device>
                        </mapping>
                        <mapping>
                                <virtual>ephemeral0</virtual>
                                <device>sda2</device>
                        </mapping>
                        <mapping>
                                <virtual>swap</virtual>
                                <device>sda3</device>
                        </mapping>
                </block_device_mapping>
                <kernel_id>aki-00000001</kernel_id>
                <ramdisk_id>ari-00000001</ramdisk_id>
        </machine_configuration>
</manifest>
"""


class TestS3ImageService(test.TestCase):
    def setUp(self):
        super(TestS3ImageService, self).setUp()
        self.flags(image_service='nova.image.fake.FakeImageService')
        self.image_service = s3.S3ImageService()
        self.context = context.RequestContext(None, None)

        # set up one fixture to test shows, should have id '1'
        nova.db.api.s3_image_create(self.context,
                                    '155d900f-4e14-4e4c-a73d-069cbf4541e6')

    def _assertEqualList(self, list0, list1, keys):
        self.assertEqual(len(list0), len(list1))
        key = keys[0]
        for x in list0:
            self.assertEqual(len(x), len(keys))
            self.assertTrue(key in x)
            for y in list1:
                self.assertTrue(key in y)
                if x[key] == y[key]:
                    for k in keys:
                        self.assertEqual(x[k], y[k])

    def test_show_cannot_use_uuid(self):
        self.assertRaises(exception.ImageNotFound,
                          self.image_service.show, self.context,
                          '155d900f-4e14-4e4c-a73d-069cbf4541e6')

    def test_show_translates_correctly(self):
        self.image_service.show(self.context, '1')

    def test_detail(self):
        self.image_service.detail(self.context)

    def test_s3_create(self):
        metadata = {'properties': {
            'root_device_name': '/dev/sda1',
            'block_device_mapping': [
                {'device_name': '/dev/sda1',
                 'snapshot_id': 'snap-12345678',
                 'delete_on_termination': True},
                {'device_name': '/dev/sda2',
                 'virutal_name': 'ephemeral0'},
                {'device_name': '/dev/sdb0',
                 'no_device': True}]}}
        _manifest, image, image_uuid = self.image_service._s3_parse_manifest(
            self.context, metadata, ami_manifest_xml)

        ret_image = self.image_service.show(self.context, image['id'])
        self.assertTrue('properties' in ret_image)
        properties = ret_image['properties']

        self.assertTrue('mappings' in properties)
        mappings = properties['mappings']
        expected_mappings = [
            {"device": "sda1", "virtual": "ami"},
            {"device": "/dev/sda1", "virtual": "root"},
            {"device": "sda2", "virtual": "ephemeral0"},
            {"device": "sda3", "virtual": "swap"}]
        self._assertEqualList(mappings, expected_mappings,
            ['device', 'virtual'])

        self.assertTrue('block_device_mapping', properties)
        block_device_mapping = properties['block_device_mapping']
        expected_bdm = [
            {'device_name': '/dev/sda1',
             'snapshot_id': 'snap-12345678',
             'delete_on_termination': True},
            {'device_name': '/dev/sda2',
             'virutal_name': 'ephemeral0'},
            {'device_name': '/dev/sdb0',
             'no_device': True}]
        self.assertEqual(block_device_mapping, expected_bdm)

    def test_s3_malicious_tarballs(self):
        self.assertRaises(exception.Error,
            self.image_service._test_for_malicious_tarball,
            "/unused", os.path.join(os.path.dirname(__file__), 'abs.tar.gz'))
        self.assertRaises(exception.Error,
            self.image_service._test_for_malicious_tarball,
            "/unused", os.path.join(os.path.dirname(__file__), 'rel.tar.gz'))
