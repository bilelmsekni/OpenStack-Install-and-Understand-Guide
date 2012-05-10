# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack, LLC
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

"""Tests the filesystem backend store"""

import errno
import StringIO
import hashlib
import unittest

import stubout

from glance.common import exception
from glance.common import utils
from glance.store.location import get_location_from_uri
from glance.store.filesystem import Store, ChunkedFile
from glance.tests.unit import base


class TestStore(base.IsolatedUnitTest):

    def setUp(self):
        """Establish a clean test environment"""
        super(TestStore, self).setUp()
        self.orig_chunksize = ChunkedFile.CHUNKSIZE
        ChunkedFile.CHUNKSIZE = 10
        self.store = Store(self.conf)

    def tearDown(self):
        """Clear the test environment"""
        super(TestStore, self).tearDown()
        ChunkedFile.CHUNKSIZE = self.orig_chunksize

    def test_get(self):
        """Test a "normal" retrieval of an image in chunks"""
        # First add an image...
        image_id = utils.generate_uuid()
        file_contents = "chunk00000remainder"
        location = "file://%s/%s" % (self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        location, size, checksum = self.store.add(image_id,
                                                  image_file,
                                                  len(file_contents))

        # Now read it back...
        uri = "file:///%s/%s" % (self.test_dir, image_id)
        loc = get_location_from_uri(uri)
        (image_file, image_size) = self.store.get(loc)

        expected_data = "chunk00000remainder"
        expected_num_chunks = 2
        data = ""
        num_chunks = 0

        for chunk in image_file:
            num_chunks += 1
            data += chunk
        self.assertEqual(expected_data, data)
        self.assertEqual(expected_num_chunks, num_chunks)

    def test_get_non_existing(self):
        """
        Test that trying to retrieve a file that doesn't exist
        raises an error
        """
        loc = get_location_from_uri("file:///%s/non-existing" % self.test_dir)
        self.assertRaises(exception.NotFound,
                          self.store.get,
                          loc)

    def test_add(self):
        """Test that we can add an image via the filesystem backend"""
        ChunkedFile.CHUNKSIZE = 1024
        expected_image_id = utils.generate_uuid()
        expected_file_size = 1024 * 5  # 5K
        expected_file_contents = "*" * expected_file_size
        expected_checksum = hashlib.md5(expected_file_contents).hexdigest()
        expected_location = "file://%s/%s" % (self.test_dir,
                                              expected_image_id)
        image_file = StringIO.StringIO(expected_file_contents)

        location, size, checksum = self.store.add(expected_image_id,
                                                  image_file,
                                                  expected_file_size)

        self.assertEquals(expected_location, location)
        self.assertEquals(expected_file_size, size)
        self.assertEquals(expected_checksum, checksum)

        uri = "file:///%s/%s" % (self.test_dir, expected_image_id)
        loc = get_location_from_uri(uri)
        (new_image_file, new_image_size) = self.store.get(loc)
        new_image_contents = ""
        new_image_file_size = 0

        for chunk in new_image_file:
            new_image_file_size += len(chunk)
            new_image_contents += chunk

        self.assertEquals(expected_file_contents, new_image_contents)
        self.assertEquals(expected_file_size, new_image_file_size)

    def test_add_already_existing(self):
        """
        Tests that adding an image with an existing identifier
        raises an appropriate exception
        """
        ChunkedFile.CHUNKSIZE = 1024
        image_id = utils.generate_uuid()
        file_size = 1024 * 5  # 5K
        file_contents = "*" * file_size
        location = "file://%s/%s" % (self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        location, size, checksum = self.store.add(image_id,
                                                  image_file,
                                                  file_size)
        image_file = StringIO.StringIO("nevergonnamakeit")
        self.assertRaises(exception.Duplicate,
                          self.store.add,
                          image_id, image_file, 0)

    def _do_test_add_failure(self, errno, exception):
        ChunkedFile.CHUNKSIZE = 1024
        image_id = utils.generate_uuid()
        file_size = 1024 * 5  # 5K
        file_contents = "*" * file_size
        location = "file://%s/%s" % (self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        def fake_IO_Error(size):
            e = IOError()
            e.errno = errno
            raise e

        self.stubs.Set(image_file, 'read', fake_IO_Error)
        self.assertRaises(exception,
                          self.store.add,
                          image_id, image_file, 0)

    def test_add_storage_full(self):
        """
        Tests that adding an image without enough space on disk
        raises an appropriate exception
        """
        self._do_test_add_failure(errno.ENOSPC, exception.StorageFull)

    def test_add_file_too_big(self):
        """
        Tests that adding an excessively large image file
        raises an appropriate exception
        """
        self._do_test_add_failure(errno.EFBIG, exception.StorageFull)

    def test_add_storage_write_denied(self):
        """
        Tests that adding an image with insufficient filestore permissions
        raises an appropriate exception
        """
        self._do_test_add_failure(errno.EACCES, exception.StorageWriteDenied)

    def test_add_other_failure(self):
        """
        Tests that a non-space-related IOError does not raise a
        StorageFull exception.
        """
        self._do_test_add_failure(errno.ENOTDIR, IOError)

    def test_delete(self):
        """
        Test we can delete an existing image in the filesystem store
        """
        # First add an image
        image_id = utils.generate_uuid()
        file_size = 1024 * 5  # 5K
        file_contents = "*" * file_size
        location = "file://%s/%s" % (self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        location, size, checksum = self.store.add(image_id,
                                                  image_file,
                                                  file_size)

        # Now check that we can delete it
        uri = "file:///%s/%s" % (self.test_dir, image_id)
        loc = get_location_from_uri(uri)
        self.store.delete(loc)

        self.assertRaises(exception.NotFound, self.store.get, loc)

    def test_delete_non_existing(self):
        """
        Test that trying to delete a file that doesn't exist
        raises an error
        """
        loc = get_location_from_uri("file:///tmp/glance-tests/non-existing")
        self.assertRaises(exception.NotFound,
                          self.store.delete,
                          loc)
