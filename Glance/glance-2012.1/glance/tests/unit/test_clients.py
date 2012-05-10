# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack, LLC
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
import os
import StringIO
import tempfile
import unittest

import stubout
import webob

from glance import client
from glance.common import context
from glance.common import exception
from glance.common import utils
from glance.registry.db import api as db_api
from glance.registry.db import models as db_models
from glance.registry import client as rclient
from glance.registry import context as rcontext
from glance.tests import stubs
from glance.tests import utils as test_utils
from glance.tests.unit import base

CONF = {'sql_connection': 'sqlite://'}

_gen_uuid = utils.generate_uuid

UUID1 = _gen_uuid()
UUID2 = _gen_uuid()


class TestBadClients(unittest.TestCase):

    """Test exceptions raised for bad clients"""

    def test_bad_address(self):
        """Test ClientConnectionError raised"""
        c = client.Client("127.999.1.1")
        self.assertRaises(exception.ClientConnectionError,
                          c.get_image,
                          1)

    def test_ssl_no_key_file(self):
        """
        Test that when doing SSL connection, a key file is
        required if a cert file has been specified
        """
        try:
            with tempfile.NamedTemporaryFile() as cert_file:
                cert_file.write("bogus-cert")
                cert_file.flush()
            c = client.Client("0.0.0.0", use_ssl=True,
                              cert_file=cert_file.name)
        except exception.ClientConnectionError:
            return
        self.fail("Did not raise ClientConnectionError")

    def test_ssl_non_existing_key_file(self):
        """
        Test that when doing SSL connection, a specified key
        file is required to exist
        """
        try:
            c = client.Client("0.0.0.0", use_ssl=True,
                              key_file='nonexistingfile')
        except exception.ClientConnectionError:
            return
        self.fail("Did not raise ClientConnectionError")

    def test_ssl_no_cert_file(self):
        """
        Test that when doing SSL connection, a cert file is
        required if a key file has been specified
        """
        try:
            with tempfile.NamedTemporaryFile() as key_file:
                key_file.write("bogus-key")
                key_file.flush()
                c = client.Client("0.0.0.0", use_ssl=True,
                                  key_file=key_file.name)
        except exception.ClientConnectionError:
            return
        self.fail("Did not raise ClientConnectionError")

    def test_ssl_non_existing_cert_file(self):
        """
        Test that when doing SSL connection, a cert file is
        required to exist if specified
        """
        try:
            with tempfile.NamedTemporaryFile() as key_file:
                key_file.write("bogus-key")
                key_file.flush()
                c = client.Client("0.0.0.0", use_ssl=True,
                                  key_file=key_file.name,
                                  cert_file='nonexistingfile')
        except exception.ClientConnectionError:
            return
        self.fail("Did not raise ClientConnectionError")

    def test_ssl_non_existing_ca_file(self):
        """
        Test that when doing SSL connection, a specified CA file exists
        """
        try:
            c = client.Client("0.0.0.0", use_ssl=True,
                              ca_file='nonexistingfile')
        except exception.ClientConnectionError:
            return
        self.fail("Did not raise ClientConnectionError")

    def test_ssl_optional_ca_file(self):
        """
        Test that when doing SSL connection, a cert file and key file are
        required to exist if specified, but a CA file is optional.
        """
        try:
            with tempfile.NamedTemporaryFile() as key_file:
                key_file.write("bogus-key")
                key_file.flush()
                with tempfile.NamedTemporaryFile() as cert_file:
                    cert_file.write("bogus-cert")
                    cert_file.flush()
                    c = client.Client("0.0.0.0", use_ssl=True,
                                      key_file=key_file.name,
                                      cert_file=cert_file.name)
        except exception.ClientConnectionError:
            self.fail("Raised ClientConnectionError when it should not")


class TestRegistryClient(base.IsolatedUnitTest):

    """
    Test proper actions made for both valid and invalid requests
    against a Registry service
    """

    def setUp(self):
        """Establish a clean test environment"""
        super(TestRegistryClient, self).setUp()
        db_api.configure_db(self.conf)
        self.context = rcontext.RequestContext(is_admin=True)
        self.FIXTURES = [
            {'id': UUID1,
             'name': 'fake image #1',
             'status': 'active',
             'disk_format': 'ami',
             'container_format': 'ami',
             'is_public': False,
             'created_at': datetime.datetime.utcnow(),
             'updated_at': datetime.datetime.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': None,
             'size': 13,
             'location': "swift://user:passwd@acct/container/obj.tar.0",
             'properties': {'type': 'kernel'}},
            {'id': UUID2,
             'name': 'fake image #2',
             'status': 'active',
             'disk_format': 'vhd',
             'container_format': 'ovf',
             'is_public': True,
             'created_at': datetime.datetime.utcnow(),
             'updated_at': datetime.datetime.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': None,
             'size': 19,
             'location': "file:///tmp/glance-tests/2",
             'properties': {}}]
        self.destroy_fixtures()
        self.create_fixtures()
        self.client = rclient.RegistryClient("0.0.0.0")

    def tearDown(self):
        """Clear the test environment"""
        super(TestRegistryClient, self).tearDown()
        self.destroy_fixtures()

    def create_fixtures(self):
        for fixture in self.FIXTURES:
            db_api.image_create(self.context, fixture)

    def destroy_fixtures(self):
        # Easiest to just drop the models and re-create them...
        db_models.unregister_models(db_api._ENGINE)
        db_models.register_models(db_api._ENGINE)

    def test_get_image_index(self):
        """Test correct set of public image returned"""
        fixture = {
            'id': UUID2,
            'name': 'fake image #2'
        }
        images = self.client.get_images()
        self.assertEquals(len(images), 1)

        for k, v in fixture.items():
            self.assertEquals(v, images[0][k])

    def test_create_image_with_null_min_disk_min_ram(self):
        UUID3 = _gen_uuid()
        extra_fixture = {
            'id': UUID3,
            'status': 'active',
            'is_public': True,
            'disk_format': 'vhd',
            'container_format': 'ovf',
            'name': 'asdf',
            'size': 19,
            'checksum': None,
            'min_disk': None,
            'min_ram': None,
        }
        db_api.image_create(self.context, extra_fixture)
        image = self.client.get_image(UUID3)
        self.assertEqual(0, image["min_ram"])
        self.assertEqual(0, image["min_disk"])

    def test_get_index_sort_name_asc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted alphabetically by name in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='name', sort_dir='asc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID2)
        self.assertEquals(images[2]['id'], UUID4)

    def test_get_index_sort_status_desc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted alphabetically by status in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'queued',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='status', sort_dir='desc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID2)

    def test_get_index_sort_disk_format_asc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted alphabetically by disk_format in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vdi',
                         'container_format': 'ovf',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='disk_format',
                                        sort_dir='asc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID2)

    def test_get_index_sort_container_format_desc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted alphabetically by container_format in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'iso',
                         'container_format': 'bare',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='container_format',
                                        sort_dir='desc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID2)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID3)

    def test_get_index_sort_size_asc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted by size in ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'asdf',
                         'size': 100,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'iso',
                         'container_format': 'bare',
                         'name': 'xyz',
                         'size': 2,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='size', sort_dir='asc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID4)
        self.assertEquals(images[1]['id'], UUID2)
        self.assertEquals(images[2]['id'], UUID3)

    def test_get_index_sort_created_at_asc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted by created_at in ascending order.
        """
        now = datetime.datetime.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'created_at': time1}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 20,
                         'checksum': None,
                         'created_at': time2}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='created_at', sort_dir='asc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID2)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID3)

    def test_get_index_sort_updated_at_desc(self):
        """
        Tests that the /images registry API returns list of
        public images sorted by updated_at in descending order.
        """
        now = datetime.datetime.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'created_at': None,
                         'updated_at': time1}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 20,
                         'checksum': None,
                         'created_at': None,
                         'updated_at': time2}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='updated_at', sort_dir='desc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID2)

    def test_get_image_index_marker(self):
        """Test correct set of images returned with marker param."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(marker=UUID4)

        self.assertEquals(len(images), 2)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID2)

    def test_get_image_index_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_images,
                          marker=_gen_uuid())

    def test_get_image_index_limit(self):
        """Test correct number of images returned with limit param."""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(limit=2)
        self.assertEquals(len(images), 2)

    def test_get_image_index_marker_limit(self):
        """Test correct set of images returned with marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(marker=UUID3, limit=1)

        self.assertEquals(len(images), 1)
        self.assertEquals(images[0]['id'], UUID2)

    def test_get_image_index_limit_None(self):
        """Test correct set of images returned with limit param == None."""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(limit=None)
        self.assertEquals(len(images), 3)

    def test_get_image_index_by_name(self):
        """
        Test correct set of public, name-filtered image returned. This
        is just a sanity check, we test the details call more in-depth.
        """
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(filters={'name': 'new name! #123'})
        self.assertEquals(len(images), 1)

        for image in images:
            self.assertEquals('new name! #123', image['name'])

    def test_get_image_details(self):
        """Tests that the detailed info about public images returned"""
        fixture = {'id': UUID2,
                   'name': 'fake image #2',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'active',
                   'size': 19,
                   'properties': {}}

        images = self.client.get_images_detailed()

        self.assertEquals(len(images), 1)
        for k, v in fixture.items():
            self.assertEquals(v, images[0][k])

    def test_get_image_details_marker_limit(self):
        """Test correct set of images returned with marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(marker=UUID3, limit=1)

        self.assertEquals(len(images), 1)
        self.assertEquals(images[0]['id'], UUID2)

    def test_get_image_details_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_images_detailed,
                          marker=_gen_uuid())

    def test_get_image_details_by_name(self):
        """Tests that a detailed call can be filtered by name"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        filters = {'name': 'new name! #123'}
        images = self.client.get_images_detailed(filters=filters)

        self.assertEquals(len(images), 1)
        for image in images:
            self.assertEquals('new name! #123', image['name'])

    def test_get_image_details_by_status(self):
        """Tests that a detailed call can be filtered by status"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(filters={'status': 'saving'})

        self.assertEquals(len(images), 1)
        for image in images:
            self.assertEquals('saving', image['status'])

    def test_get_image_details_by_container_format(self):
        """Tests that a detailed call can be filtered by container_format"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        filters = {'container_format': 'ovf'}
        images = self.client.get_images_detailed(filters=filters)

        self.assertEquals(len(images), 2)
        for image in images:
            self.assertEquals('ovf', image['container_format'])

    def test_get_image_details_by_disk_format(self):
        """Tests that a detailed call can be filtered by disk_format"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        filters = {'disk_format': 'vhd'}
        images = self.client.get_images_detailed(filters=filters)

        self.assertEquals(len(images), 2)
        for image in images:
            self.assertEquals('vhd', image['disk_format'])

    def test_get_image_details_with_maximum_size(self):
        """Tests that a detailed call can be filtered by size_max"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 21,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(filters={'size_max': 20})

        self.assertEquals(len(images), 1)
        for image in images:
            self.assertTrue(image['size'] <= 20)

    def test_get_image_details_with_minimum_size(self):
        """Tests that a detailed call can be filtered by size_min"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(filters={'size_min': 20})

        self.assertEquals(len(images), 1)
        for image in images:
            self.assertTrue(image['size'] >= 20)

    def test_get_image_details_with_changes_since(self):
        """Tests that a detailed call can be filtered by size_min"""
        dt1 = datetime.datetime.utcnow() - datetime.timedelta(1)
        iso1 = utils.isotime(dt1)

        dt2 = datetime.datetime.utcnow() + datetime.timedelta(1)
        iso2 = utils.isotime(dt2)

        dt3 = datetime.datetime.utcnow() + datetime.timedelta(2)
        iso3 = utils.isotime(dt3)

        dt4 = datetime.datetime.utcnow() + datetime.timedelta(3)
        iso4 = utils.isotime(dt4)

        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'fake image #3',
                         'size': 18,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)
        db_api.image_destroy(self.context, 3)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'fake image #4',
                         'size': 20,
                         'checksum': None,
                         'created_at': dt3,
                         'updated_at': dt3}

        db_api.image_create(self.context, extra_fixture)

        # Check a standard list, 4 images in db (2 deleted)
        images = self.client.get_images_detailed(filters={})
        self.assertEquals(len(images), 2)
        self.assertEqual(images[0]['id'], UUID4)
        self.assertEqual(images[1]['id'], UUID2)

        # Expect 3 images (1 deleted)
        filters = {'changes-since': iso1}
        images = self.client.get_images(filters=filters)
        self.assertEquals(len(images), 3)
        self.assertEqual(images[0]['id'], UUID4)
        self.assertEqual(images[1]['id'], UUID3)  # deleted
        self.assertEqual(images[2]['id'], UUID2)

        # Expect 1 images (0 deleted)
        filters = {'changes-since': iso2}
        images = self.client.get_images_detailed(filters=filters)
        self.assertEquals(len(images), 1)
        self.assertEqual(images[0]['id'], UUID4)

        # Expect 0 images (0 deleted)
        filters = {'changes-since': iso4}
        images = self.client.get_images(filters=filters)
        self.assertEquals(len(images), 0)

    def test_get_image_details_with_changes_since(self):
        """Tests that a detailed call can be filtered by changes-since"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(filters={'size_min': 20})
        self.assertEquals(len(images), 1)

        for image in images:
            self.assertTrue(image['size'] >= 20)

    def test_get_image_details_by_property(self):
        """Tests that a detailed call can be filtered by a property"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'properties': {'p a': 'v a'}}

        db_api.image_create(self.context, extra_fixture)

        filters = {'property-p a': 'v a'}
        images = self.client.get_images_detailed(filters=filters)
        self.assertEquals(len(images), 1)

        for image in images:
            self.assertEquals('v a', image['properties']['p a'])

    def test_get_image_details_sort_disk_format_asc(self):
        """
        Tests that a detailed call returns list of
        public images sorted alphabetically by disk_format in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vdi',
                         'container_format': 'ovf',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(sort_key='disk_format',
                                                 sort_dir='asc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID2)

    def test_get_image(self):
        """Tests that the detailed info about an image returned"""
        fixture = {'id': UUID1,
                   'name': 'fake image #1',
                   'is_public': False,
                   'disk_format': 'ami',
                   'container_format': 'ami',
                   'status': 'active',
                   'size': 13,
                   'properties': {'type': 'kernel'}}

        data = self.client.get_image(UUID1)

        for k, v in fixture.items():
            el = data[k]
            self.assertEquals(v, data[k],
                              "Failed v != data[k] where v = %(v)s and "
                              "k = %(k)s and data[k] = %(el)s" % locals())

    def test_get_image_non_existing(self):
        """Tests that NotFound is raised when getting a non-existing image"""
        self.assertRaises(exception.NotFound,
                          self.client.get_image,
                          _gen_uuid())

    def test_add_image_basic(self):
        """Tests that we can add image metadata and returns the new id"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                  }

        new_image = self.client.add_image(fixture)

        # Test all other attributes set
        data = self.client.get_image(new_image['id'])

        for k, v in fixture.items():
            self.assertEquals(v, data[k])

        # Test status was updated properly
        self.assertTrue('status' in data.keys())
        self.assertEquals('active', data['status'])

    def test_add_image_with_properties(self):
        """Tests that we can add image metadata with properties"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "file:///tmp/glance-tests/2",
                   'properties': {'distro': 'Ubuntu 10.04 LTS'}}

        new_image = self.client.add_image(fixture)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEquals(v, new_image[k])

        # Test status was updated properly
        self.assertTrue('status' in new_image.keys())
        self.assertEquals('active', new_image['status'])

    def test_add_image_already_exists(self):
        """Tests proper exception is raised if image with ID already exists"""
        fixture = {'id': UUID2,
                   'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "file:///tmp/glance-tests/2",
                  }

        self.assertRaises(exception.Duplicate,
                          self.client.add_image,
                          fixture)

    def test_add_image_with_bad_status(self):
        """Tests proper exception is raised if a bad status is set"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'status': 'bad status',
                   'size': 19,
                   'location': "file:///tmp/glance-tests/2",
                  }

        self.assertRaises(exception.Invalid,
                          self.client.add_image,
                          fixture)

    def test_add_image_with_acceptably_long_name(self):
        """Tests adding image with acceptably long name"""
        name = 'x' * 255
        fixture = {'name': name,
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "file:///tmp/glance-tests/2",
                  }

        new_image = self.client.add_image(fixture)

        data = self.client.get_image(new_image['id'])
        self.assertEquals(name, data['name'])

    def test_add_image_with_excessively_long_name(self):
        """Tests adding image with excessively long name"""
        name = 'x' * 256
        fixture = {'name': name,
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "file:///tmp/glance-tests/2",
                  }

        self.assertRaises(exception.Invalid,
                          self.client.add_image,
                          fixture)

    def test_update_image_with_acceptably_long_name(self):
        """Tests updating image with acceptably long name"""
        name = 'x' * 255
        fixture = {'name': name}

        self.assertTrue(self.client.update_image(UUID2, fixture))

        data = self.client.get_image(UUID2)
        self.assertEquals(name, data['name'])

    def test_update_image_with_excessively_long_name(self):
        """Tests updating image with excessively long name"""
        name = 'x' * 256
        fixture = {'name': name}

        self.assertRaises(exception.Invalid,
                          self.client.update_image,
                          UUID2,
                          fixture)

    def test_update_image(self):
        """Tests that the /images PUT registry API updates the image"""
        fixture = {'name': 'fake public image #2',
                   'disk_format': 'vmdk'}

        self.assertTrue(self.client.update_image(UUID2, fixture))

        # Test all other attributes set
        data = self.client.get_image(UUID2)

        for k, v in fixture.items():
            self.assertEquals(v, data[k])

    def test_update_image_not_existing(self):
        """Tests non existing image update doesn't work"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'status': 'bad status',
                  }

        self.assertRaises(exception.NotFound,
                          self.client.update_image,
                          _gen_uuid(),
                          fixture)

    def test_delete_image(self):
        """Tests that image metadata is deleted properly"""
        # Grab the original number of images
        orig_num_images = len(self.client.get_images())

        # Delete image #2
        self.assertTrue(self.client.delete_image(UUID2))

        # Verify one less image
        new_num_images = len(self.client.get_images())

        self.assertEquals(new_num_images, orig_num_images - 1)

    def test_delete_image_not_existing(self):
        """Tests cannot delete non-existing image"""
        self.assertRaises(exception.NotFound,
                          self.client.delete_image,
                          _gen_uuid())

    def test_get_image_members(self):
        """Tests getting image members"""
        memb_list = self.client.get_image_members(UUID2)
        num_members = len(memb_list)
        self.assertEquals(num_members, 0)

    def test_get_image_members_not_existing(self):
        """Tests getting non-existant image members"""
        self.assertRaises(exception.NotFound,
                          self.client.get_image_members,
                          _gen_uuid())

    def test_get_member_images(self):
        """Tests getting member images"""
        memb_list = self.client.get_member_images('pattieblack')
        num_members = len(memb_list)
        self.assertEquals(num_members, 0)

    def test_replace_members(self):
        """Tests replacing image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.replace_members, UUID2,
                          dict(member_id='pattieblack'))

    def test_add_member(self):
        """Tests adding image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.add_member, UUID2, 'pattieblack')

    def test_delete_member(self):
        """Tests deleting image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.delete_member, UUID2, 'pattieblack')


class TestClient(base.IsolatedUnitTest):

    """
    Test proper actions made for both valid and invalid requests
    against a Glance service
    """

    def setUp(self):
        """Establish a clean test environment"""
        super(TestClient, self).setUp()
        db_api.configure_db(self.conf)
        self.client = client.Client("0.0.0.0")
        self.FIXTURES = [
            {'id': UUID1,
             'name': 'fake image #1',
             'status': 'active',
             'disk_format': 'ami',
             'container_format': 'ami',
             'is_public': False,
             'created_at': datetime.datetime.utcnow(),
             'updated_at': datetime.datetime.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': None,
             'size': 13,
             'location': "file:///%s/%s" % (self.test_dir, UUID1),
             'properties': {'type': 'kernel'}},
            {'id': UUID2,
             'name': 'fake image #2',
             'status': 'active',
             'disk_format': 'vhd',
             'container_format': 'ovf',
             'is_public': True,
             'created_at': datetime.datetime.utcnow(),
             'updated_at': datetime.datetime.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': None,
             'size': 19,
             'location': "file:///%s/%s" % (self.test_dir, UUID2),
             'properties': {}}]
        self.context = rcontext.RequestContext(is_admin=True)
        self.destroy_fixtures()
        self.create_fixtures()

    def tearDown(self):
        """Clear the test environment"""
        super(TestClient, self).tearDown()
        self.destroy_fixtures()

    def create_fixtures(self):
        for fixture in self.FIXTURES:
            db_api.image_create(self.context, fixture)
            # We write a fake image file to the filesystem
            with open("%s/%s" % (self.test_dir, fixture['id']), 'wb') as image:
                image.write("chunk00000remainder")
                image.flush()

    def destroy_fixtures(self):
        # Easiest to just drop the models and re-create them...
        db_models.unregister_models(db_api._ENGINE)
        db_models.register_models(db_api._ENGINE)

    def test_get_image(self):
        """Test a simple file backend retrieval works as expected"""
        expected_image = 'chunk00000remainder'
        expected_meta = {'id': UUID2,
                   'name': 'fake image #2',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'active',
                   'size': 19,
                   'properties': {}}
        meta, image_chunks = self.client.get_image(UUID2)

        image_data = ""
        for image_chunk in image_chunks:
            image_data += image_chunk

        self.assertEquals(expected_image, image_data)
        for k, v in expected_meta.items():
            self.assertEquals(v, meta[k])

    def test_get_image_not_existing(self):
        """Test retrieval of a non-existing image returns a 404"""
        self.assertRaises(exception.NotFound,
                          self.client.get_image,
                          _gen_uuid())

    def test_get_image_index_sort_container_format_desc(self):
        """
        Tests that the client returns list of public images
        sorted alphabetically by container_format in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'iso',
                         'container_format': 'bare',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(sort_key='container_format',
                                        sort_dir='desc')

        self.assertEquals(len(images), 3)
        self.assertEquals(images[0]['id'], UUID2)
        self.assertEquals(images[1]['id'], UUID4)
        self.assertEquals(images[2]['id'], UUID3)

    def test_get_image_index(self):
        """Test correct set of public image returned"""
        fixture = {'id': UUID2,
                   'name': 'fake image #2'}
        images = self.client.get_images()
        self.assertEquals(len(images), 1)

        for k, v in fixture.items():
            self.assertEquals(v, images[0][k])

    def test_get_image_index_marker(self):
        """Test correct set of public images returned with marker param."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(marker=UUID4)

        self.assertEquals(len(images), 2)
        self.assertEquals(images[0]['id'], UUID3)
        self.assertEquals(images[1]['id'], UUID2)

    def test_get_image_index_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_images,
                          marker=_gen_uuid())

    def test_get_image_index_limit(self):
        """Test correct number of public images returned with limit param."""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(limit=2)
        self.assertEquals(len(images), 2)

    def test_get_image_index_marker_limit(self):
        """Test correct set of images returned with marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images(marker=UUID3, limit=1)
        self.assertEquals(len(images), 1)

        self.assertEquals(images[0]['id'], UUID2)

    def test_get_image_index_by_base_attribute(self):
        """Tests that an index call can be filtered by a base attribute"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        filters = {'name': 'new name! #123'}
        images = self.client.get_images(filters=filters)

        self.assertEquals(len(images), 1)
        self.assertEquals('new name! #123', images[0]['name'])

    def test_get_image_index_by_property(self):
        """Tests that an index call can be filtered by a property"""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'properties': {'p a': 'v a'}}

        db_api.image_create(self.context, extra_fixture)

        filters = {'property-p a': 'v a'}
        images = self.client.get_images(filters=filters)

        self.assertEquals(len(images), 1)
        self.assertEquals(images[0]['id'], UUID3)

    def test_get_image_details(self):
        """Tests that the detailed info about public images returned"""
        expected = {'id': UUID2,
                   'name': 'fake image #2',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'active',
                   'size': 19,
                   'properties': {}}

        images = self.client.get_images_detailed()
        self.assertEquals(len(images), 1)

        for k, v in expected.items():
            self.assertEquals(v, images[0][k])

    def test_get_image_details_marker_limit(self):
        """Test detailed calls are filtered by marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #125',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(marker=UUID3, limit=1)
        self.assertEquals(len(images), 1)

        self.assertEquals(images[0]['id'], UUID2)

    def test_get_image_details_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_images_detailed,
                          marker=_gen_uuid())

    def test_get_image_details_by_base_attribute(self):
        """Tests that a detailed call can be filtered by a base attribute"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)

        filters = {'name': 'new name! #123'}
        images = self.client.get_images_detailed(filters=filters)
        self.assertEquals(len(images), 1)

        for image in images:
            self.assertEquals('new name! #123', image['name'])

    def test_get_image_details_with_changes_since(self):
        """Tests that a detailed call can be filtered by size_min"""
        dt1 = datetime.datetime.utcnow() - datetime.timedelta(1)
        iso1 = utils.isotime(dt1)

        dt2 = datetime.datetime.utcnow() + datetime.timedelta(1)
        iso2 = utils.isotime(dt2)

        dt3 = datetime.datetime.utcnow() + datetime.timedelta(2)
        iso3 = utils.isotime(dt3)

        dt4 = datetime.datetime.utcnow() + datetime.timedelta(3)
        iso4 = utils.isotime(dt4)

        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'fake image #3',
                         'size': 18,
                         'checksum': None}

        db_api.image_create(self.context, extra_fixture)
        db_api.image_destroy(self.context, UUID3)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'fake image #4',
                         'size': 20,
                         'checksum': None,
                         'created_at': dt3,
                         'updated_at': dt3}

        db_api.image_create(self.context, extra_fixture)

        # Check a standard list, 4 images in db (2 deleted)
        images = self.client.get_images_detailed(filters={})
        self.assertEquals(len(images), 2)
        self.assertEqual(images[0]['id'], UUID4)
        self.assertEqual(images[1]['id'], UUID2)

        # Expect 3 images (1 deleted)
        filters = {'changes-since': iso1}
        images = self.client.get_images(filters=filters)
        self.assertEquals(len(images), 3)
        self.assertEqual(images[0]['id'], UUID4)
        self.assertEqual(images[1]['id'], UUID3)  # deleted
        self.assertEqual(images[2]['id'], UUID2)

        # Expect 1 images (0 deleted)
        filters = {'changes-since': iso2}
        images = self.client.get_images_detailed(filters=filters)
        self.assertEquals(len(images), 1)
        self.assertEqual(images[0]['id'], UUID4)

        # Expect 0 images (0 deleted)
        filters = {'changes-since': iso4}
        images = self.client.get_images(filters=filters)
        self.assertEquals(len(images), 0)

    def test_get_image_details_by_property(self):
        """Tests that a detailed call can be filtered by a property"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'properties': {'p a': 'v a'}}

        db_api.image_create(self.context, extra_fixture)

        filters = {'property-p a': 'v a'}
        images = self.client.get_images_detailed(filters=filters)
        self.assertEquals(len(images), 1)

        for image in images:
            self.assertEquals('v a', image['properties']['p a'])

    def test_get_image_bad_filters_with_other_params(self):
        """Tests that a detailed call can be filtered by a property"""
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'saving',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'new name! #123',
                         'size': 19,
                         'checksum': None,
                         'properties': {'p a': 'v a'}}

        db_api.image_create(self.context, extra_fixture)

        images = self.client.get_images_detailed(filters=None, limit=1)
        self.assertEquals(len(images), 1)

    def test_get_image_meta(self):
        """Tests that the detailed info about an image returned"""
        fixture = {'id': UUID2,
                   'name': 'fake image #2',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'active',
                   'size': 19,
                   'properties': {}}

        data = self.client.get_image_meta(UUID2)

        for k, v in fixture.items():
            self.assertEquals(v, data[k])

    def test_get_image_iso_meta(self):
        """Tests that the detailed info about an ISO image is returned"""
        fixture = {'name': 'fake iso image',
                   'is_public': False,
                   'disk_format': 'iso',
                   'container_format': 'bare',
                   'status': 'active',
                   'size': 19,
                   'location': "http://localhost/glance-tests/3",
                   'properties': {}}

        new_image = self.client.add_image(fixture)
        new_image_id = new_image['id']

        # Test all other attributes set
        data = self.client.get_image_meta(new_image_id)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEquals(v, data[k])

    def test_get_image_non_existing(self):
        """Tests that NotFound is raised when getting a non-existing image"""
        self.assertRaises(exception.NotFound,
                          self.client.get_image,
                          _gen_uuid())

    def test_add_image_without_location_or_raw_data(self):
        """Tests client returns image as queued"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                  }
        image_meta = self.client.add_image(fixture)
        self.assertEquals('queued', image_meta['status'])
        self.assertEquals(0, image_meta['size'])

    def test_add_image_basic(self):
        """Tests that we can add image metadata and returns the new id"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "http://localhost/glance-tests/2",
                  }
        new_image = self.client.add_image(fixture)
        new_image_id = new_image['id']

        # Test all other attributes set
        data = self.client.get_image_meta(new_image_id)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEquals(v, data[k])

        # Test status was updated properly
        self.assertTrue('status' in data.keys())
        self.assertEquals('active', data['status'])

    def test_add_image_with_properties(self):
        """Tests that we can add image metadata with properties"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 19,
                   'location': "http://localhost/glance-tests/2",
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }
        new_image = self.client.add_image(fixture)
        new_image_id = new_image['id']

        # Test all other attributes set
        data = self.client.get_image_meta(new_image_id)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEquals(v, data[k])

        # Test status was updated properly
        self.assertTrue('status' in data)
        self.assertEquals('active', data['status'])

    def test_add_image_with_iso_properties(self):
        """Tests that we can add image metadata with ISO disk format"""
        fixture = {'name': 'fake public iso',
                   'is_public': True,
                   'disk_format': 'iso',
                   'container_format': 'bare',
                   'size': 19,
                   'location': "http://localhost/glance-tests/2",
                   'properties': {'install': 'Bindows Heaven'},
                  }
        new_image = self.client.add_image(fixture)
        new_image_id = new_image['id']

        # Test all other attributes set
        data = self.client.get_image_meta(new_image_id)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEquals(v, data[k])

        # Test status was updated properly
        self.assertTrue('status' in data)
        self.assertEquals('active', data['status'])

    def test_add_image_with_bad_iso_properties(self):
        """
        Verify that ISO with invalid container format is rejected.
        Intended to exercise error path once rather than be exhaustive
        set of mismatches
        """
        fixture = {'name': 'fake public iso',
                   'is_public': True,
                   'disk_format': 'iso',
                   'container_format': 'vhd',
                   'size': 19,
                   'location': "http://localhost/glance-tests/3",
                   'properties': {'install': 'Bindows Heaven'},
                  }

        self.assertRaises(exception.Invalid,
            self.client.add_image,
            fixture)

    def test_add_image_already_exists(self):
        """Tests proper exception is raised if image with ID already exists"""
        fixture = {'id': UUID2,
                   'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'bad status',
                   'size': 19,
                   'location': "http://localhost/glance-tests/2",
                  }

        self.assertRaises(exception.Duplicate,
                          self.client.add_image,
                          fixture)

    def test_add_image_with_bad_status(self):
        """Tests a bad status is set to a proper one by server"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'bad status',
                   'size': 19,
                   'location': "http://localhost/glance-tests/2",
                  }

        new_image = self.client.add_image(fixture)
        self.assertEquals(new_image['status'], 'active')

    def test_add_image_with_image_data_as_string(self):
        """Tests can add image by passing image data as string"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 19,
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }

        image_data_fixture = r"chunk00000remainder"

        new_image = self.client.add_image(fixture, image_data_fixture)
        new_image_id = new_image['id']

        new_meta, new_image_chunks = self.client.get_image(new_image_id)

        new_image_data = ""
        for image_chunk in new_image_chunks:
            new_image_data += image_chunk

        self.assertEquals(image_data_fixture, new_image_data)
        for k, v in fixture.items():
            self.assertEquals(v, new_meta[k])

    def test_add_image_with_image_data_as_file(self):
        """Tests can add image by passing image data as file"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 19,
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }

        image_data_fixture = r"chunk00000remainder"

        tmp_image_filepath = '/tmp/rubbish-image'

        if os.path.exists(tmp_image_filepath):
            os.unlink(tmp_image_filepath)

        tmp_file = open(tmp_image_filepath, 'wb')
        tmp_file.write(image_data_fixture)
        tmp_file.close()

        new_image = self.client.add_image(fixture, open(tmp_image_filepath))
        new_image_id = new_image['id']

        if os.path.exists(tmp_image_filepath):
            os.unlink(tmp_image_filepath)

        new_meta, new_image_chunks = self.client.get_image(new_image_id)

        new_image_data = ""
        for image_chunk in new_image_chunks:
            new_image_data += image_chunk

        self.assertEquals(image_data_fixture, new_image_data)
        for k, v in fixture.items():
            self.assertEquals(v, new_meta[k])

    def _add_image_as_iterable(self):
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 10 * 65536,
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }

        class Zeros(object):
            def __init__(self, chunks):
                self.chunks = chunks
                self.zeros = open('/dev/zero', 'rb')

            def __iter__(self):
                while self.chunks > 0:
                    self.chunks -= 1
                    chunk = self.zeros.read(65536)
                    yield chunk

        new_image = self.client.add_image(fixture, Zeros(10))
        new_image_id = new_image['id']

        new_meta, new_image_chunks = self.client.get_image(new_image_id)

        return (fixture, new_meta, new_image_chunks)

    def _verify_image_iterable(self, fixture, meta, chunks):
        image_data_len = 0
        for image_chunk in chunks:
            image_data_len += len(image_chunk)
        self.assertEquals(10 * 65536, image_data_len)

        for k, v in fixture.items():
            self.assertEquals(v, meta[k])

    def test_add_image_with_image_data_as_iterable(self):
        """Tests we can add image by passing image data as an iterable"""
        fixture, new_meta, new_chunks = self._add_image_as_iterable()

        self._verify_image_iterable(fixture, new_meta, new_chunks)

    def test_roundtrip_image_with_image_data_as_iterable(self):
        """Tests we can roundtrip image as an iterable"""
        fixture, new_meta, new_chunks = self._add_image_as_iterable()

        # duplicate directly from iterable returned from get
        dup_image = self.client.add_image(fixture, new_chunks)
        dup_image_id = dup_image['id']

        roundtrip_meta, roundtrip_chunks = self.client.get_image(dup_image_id)

        self._verify_image_iterable(fixture, roundtrip_meta, roundtrip_chunks)

    def test_add_image_with_image_data_as_string_and_no_size(self):
        """Tests add image by passing image data as string w/ no size attr"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }

        image_data_fixture = r"chunk00000remainder"

        new_image = self.client.add_image(fixture, image_data_fixture)
        new_image_id = new_image['id']
        new_meta, new_image_chunks = self.client.get_image(new_image_id)

        new_image_data = ""
        for image_chunk in new_image_chunks:
            new_image_data += image_chunk

        self.assertEquals(image_data_fixture, new_image_data)
        for k, v in fixture.items():
            self.assertEquals(v, new_meta[k])

        self.assertEquals(19, new_meta['size'])

    def test_add_image_with_bad_store(self):
        """Tests BadRequest raised when supplying bad store name in meta"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'size': 19,
                   'store': 'bad',
                   'properties': {'distro': 'Ubuntu 10.04 LTS'},
                  }

        image_data_fixture = r"chunk00000remainder"

        self.assertRaises(exception.Invalid,
                          self.client.add_image,
                          fixture,
                          image_data_fixture)

    def test_update_image(self):
        """Tests that the /images PUT registry API updates the image"""
        fixture = {'name': 'fake public image #2',
                   'disk_format': 'vmdk'}

        self.assertTrue(self.client.update_image(UUID2, fixture))

        # Test all other attributes set
        data = self.client.get_image_meta(UUID2)

        for k, v in fixture.items():
            self.assertEquals(v, data[k])

    def test_update_image_not_existing(self):
        """Tests non existing image update doesn't work"""
        fixture = {'name': 'fake public image',
                   'is_public': True,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'bad status',
                  }

        self.assertRaises(exception.NotFound,
                          self.client.update_image,
                          _gen_uuid(),
                          fixture)

    def test_delete_image(self):
        """Tests that image metadata is deleted properly"""
        # Grab the original number of images
        orig_num_images = len(self.client.get_images())

        # Delete image #2
        self.assertTrue(self.client.delete_image(UUID2))

        # Verify one less image
        new_num_images = len(self.client.get_images())

        self.assertEquals(new_num_images, orig_num_images - 1)

    def test_delete_image_not_existing(self):
        """Tests cannot delete non-existing image"""
        self.assertRaises(exception.NotFound,
                          self.client.delete_image,
                          _gen_uuid())

    def test_get_member_images(self):
        """Tests getting image members"""
        memb_list = self.client.get_image_members(UUID2)
        num_members = len(memb_list)
        self.assertEquals(num_members, 0)

    def test_get_image_members_not_existing(self):
        """Tests getting non-existant image members"""
        self.assertRaises(exception.NotFound,
                          self.client.get_image_members,
                          _gen_uuid())

    def test_get_member_images(self):
        """Tests getting member images"""
        memb_list = self.client.get_member_images('pattieblack')
        num_members = len(memb_list)
        self.assertEquals(num_members, 0)

    def test_replace_members(self):
        """Tests replacing image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.replace_members, UUID2,
                          dict(member_id='pattieblack'))

    def test_add_member(self):
        """Tests adding image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.add_member, UUID2, 'pattieblack')

    def test_delete_member(self):
        """Tests deleting image members"""
        self.assertRaises(exception.NotAuthenticated,
                          self.client.delete_member, UUID2, 'pattieblack')


class TestConfigureClientFromURL(unittest.TestCase):
    def setUp(self):
        self.client = client.Client("0.0.0.0", doc_root="")

    def assertConfiguration(self, url, host, port, use_ssl, doc_root):
        self.client.configure_from_url(url)
        self.assertEquals(host, self.client.host)
        self.assertEquals(port, self.client.port)
        self.assertEquals(use_ssl, self.client.use_ssl)
        self.assertEquals(doc_root, self.client.doc_root)

    def test_no_port_no_ssl_no_doc_root(self):
        self.assertConfiguration(
            url='http://www.example.com',
            host='www.example.com',
            port=80,
            use_ssl=False,
            doc_root=''
        )

    def test_port_ssl_doc_root(self):
        self.assertConfiguration(
            url='https://www.example.com:8000/prefix/',
            host='www.example.com',
            port=8000,
            use_ssl=True,
            doc_root='/prefix/'
        )
