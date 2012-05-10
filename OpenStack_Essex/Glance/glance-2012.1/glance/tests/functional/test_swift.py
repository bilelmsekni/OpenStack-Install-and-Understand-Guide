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

"""
Tests a Glance API server which uses an Swift backend by default

This test requires that a real Swift account is available. It looks
in a file GLANCE_TEST_SWIFT_CONF environ variable for the credentials to
use.

Note that this test clears the entire container from the Swift account
for use by the test case, so make sure you supply credentials for
test accounts only.

If a connection cannot be established, all the test cases are
skipped.
"""

import hashlib
import httplib
import httplib2
import json

from glance.common import crypt
import glance.store.swift  # Needed to register driver for location
from glance.store.location import get_location_from_uri
from glance.tests.functional import test_api
from glance.tests.utils import skip_if_disabled, requires, minimal_headers
from glance.tests.functional.store_utils import (setup_swift,
                                                 teardown_swift,
                                                 get_swift_uri,
                                                 setup_s3,
                                                 teardown_s3,
                                                 get_s3_uri,
                                                 setup_http,
                                                 teardown_http,
                                                 get_http_uri)

FIVE_KB = 5 * 1024
FIVE_MB = 5 * 1024 * 1024


class TestSwift(test_api.TestApi):

    """Functional tests for the Swift backend"""

    def setUp(self):
        """
        Test a connection to an Swift store using the credentials
        found in the environs or /tests/functional/test_swift.conf, if found.
        If the connection fails, mark all tests to skip.
        """
        if self.disabled:
            return

        setup_swift(self)

        self.default_store = 'swift'

        super(TestSwift, self).setUp()

    def tearDown(self):
        if not self.disabled:
            self.clear_container()
        super(TestSwift, self).tearDown()

    def clear_container(self):
        from swift.common import client as swift_client
        try:
            self.swift_conn.delete_container(self.swift_store_container)
        except swift_client.ClientException, e:
            if e.http_status == httplib.CONFLICT:
                pass
            else:
                raise
        self.swift_conn.put_container(self.swift_store_container)

    @skip_if_disabled
    def test_large_objects(self):
        """
        We test the large object manifest code path in the Swift driver.
        In the case where an image file is bigger than the config variable
        swift_store_large_object_size, then we chunk the image into
        Swift, and add a manifest put_object at the end.

        We test that the delete of the large object cleans up all the
        chunks in Swift, in addition to the manifest file (LP Bug# 833285)
        """
        self.cleanup()

        self.swift_store_large_object_size = 2  # In MB
        self.swift_store_large_object_chunk_size = 1  # In MB
        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port
        registry_port = self.registry_port

        # GET /images
        # Verify no public images
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(content, '{"images": []}')

        # POST /images with public image named Image1
        # attribute and no custom properties. Verify a 200 OK is returned
        image_data = "*" * FIVE_MB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)
        self.assertEqual(data['image']['checksum'],
                         hashlib.md5(image_data).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_MB)
        self.assertEqual(data['image']['name'], "Image1")
        self.assertEqual(data['image']['is_public'], True)

        image_id = data['image']['id']

        # HEAD image
        # Verify image found now
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['x-image-meta-name'], "Image1")

        # GET image
        # Verify all information on image we just added is correct
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)

        expected_image_headers = {
            'x-image-meta-id': image_id,
            'x-image-meta-name': 'Image1',
            'x-image-meta-is_public': 'True',
            'x-image-meta-status': 'active',
            'x-image-meta-disk_format': 'raw',
            'x-image-meta-container_format': 'ovf',
            'x-image-meta-size': str(FIVE_MB)
        }

        expected_std_headers = {
            'content-length': str(FIVE_MB),
            'content-type': 'application/octet-stream'}

        for expected_key, expected_value in expected_image_headers.items():
            self.assertEqual(response[expected_key], expected_value,
                            "For key '%s' expected header value '%s'. Got '%s'"
                            % (expected_key, expected_value,
                               response[expected_key]))

        for expected_key, expected_value in expected_std_headers.items():
            self.assertEqual(response[expected_key], expected_value,
                            "For key '%s' expected header value '%s'. Got '%s'"
                            % (expected_key,
                               expected_value,
                               response[expected_key]))

        self.assertEqual(content, "*" * FIVE_MB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_MB).hexdigest())

        # We test that the delete of the large object cleans up all the
        # chunks in Swift, in addition to the manifest file (LP Bug# 833285)

        # Grab the actual Swift location and query the object manifest for
        # the chunks/segments. We will check that the segments don't exist
        # after we delete the object through Glance...
        path = "http://%s:%d/images/%s" % ("0.0.0.0", self.registry_port,
                                           image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        data = json.loads(content)
        image_loc = data['image']['location']
        if hasattr(self, 'metadata_encryption_key'):
            key = self.metadata_encryption_key
        else:
            key = self.api_server.metadata_encryption_key
        image_loc = crypt.urlsafe_decrypt(key, image_loc)
        image_loc = get_location_from_uri(image_loc)
        swift_loc = image_loc.store_location

        from swift.common import client as swift_client
        swift_conn = swift_client.Connection(
            authurl=swift_loc.swift_auth_url,
            user=swift_loc.user, key=swift_loc.key)

        # Verify the object manifest exists
        headers = swift_conn.head_object(swift_loc.container, swift_loc.obj)
        manifest = headers.get('x-object-manifest')
        self.assertTrue(manifest is not None, "Manifest could not be found!")

        # Grab the segment identifiers
        obj_container, obj_prefix = manifest.split('/', 1)
        segments = [segment['name'] for segment in
                    swift_conn.get_container(obj_container,
                                             prefix=obj_prefix)[1]]

        # Verify the segments exist
        for segment in segments:
            headers = swift_conn.head_object(obj_container, segment)
            self.assertTrue(headers.get('content-length') is not None,
                            headers)

        # DELETE image
        # Verify image and all chunks are gone...
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        # Verify the segments no longer exist
        for segment in segments:
            self.assertRaises(swift_client.ClientException,
                              swift_conn.head_object,
                              obj_container, segment)

        self.stop_servers()

    @skip_if_disabled
    def test_add_large_object_manifest_uneven_size(self):
        """
        Test when large object manifest in scenario where
        image size % chunk size != 0
        """
        self.cleanup()

        self.swift_store_large_object_size = 3  # In MB
        self.swift_store_large_object_chunk_size = 2  # In MB
        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port
        registry_port = self.registry_port

        # 0. GET /images
        # Verify no public images
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(content, '{"images": []}')

        # 1. POST /images with public image named Image1
        # attribute and no custom properties. Verify a 200 OK is returned
        image_data = "*" * FIVE_MB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)
        self.assertEqual(data['image']['checksum'],
                         hashlib.md5(image_data).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_MB)
        self.assertEqual(data['image']['name'], "Image1")
        self.assertEqual(data['image']['is_public'], True)

        image_id = data['image']['id']

        # 4. HEAD image
        # Verify image found now
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['x-image-meta-name'], "Image1")

        # 5. GET image
        # Verify all information on image we just added is correct
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)

        expected_image_headers = {
            'x-image-meta-id': image_id,
            'x-image-meta-name': 'Image1',
            'x-image-meta-is_public': 'True',
            'x-image-meta-status': 'active',
            'x-image-meta-disk_format': 'raw',
            'x-image-meta-container_format': 'ovf',
            'x-image-meta-size': str(FIVE_MB)
        }

        expected_std_headers = {
            'content-length': str(FIVE_MB),
            'content-type': 'application/octet-stream'}

        for expected_key, expected_value in expected_image_headers.items():
            self.assertEqual(response[expected_key], expected_value,
                            "For key '%s' expected header value '%s'. Got '%s'"
                            % (expected_key, expected_value,
                               response[expected_key]))

        for expected_key, expected_value in expected_std_headers.items():
            self.assertEqual(response[expected_key], expected_value,
                            "For key '%s' expected header value '%s'. Got '%s'"
                            % (expected_key,
                               expected_value,
                               response[expected_key]))

        self.assertEqual(content, "*" * FIVE_MB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_MB).hexdigest())

        # DELETE image
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()

    @skip_if_disabled
    def test_remote_image(self):
        """
        Ensure we can retrieve an image that was not stored by glance itself
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port
        registry_port = self.registry_port

        # POST /images with public image named Image1
        image_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)
        self.assertEqual(data['image']['checksum'],
                         hashlib.md5(image_data).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "Image1")
        self.assertEqual(data['image']['is_public'], True)

        image_id = data['image']['id']

        # GET image and make sure data was uploaded
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())

        # Find the location that was just added and use it as
        # the remote image location for the next image
        path = "http://%s:%d/images/%s" % ("0.0.0.0", self.registry_port,
                                           image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        data = json.loads(content)
        self.assertTrue('location' in data['image'].keys())
        loc = data['image']['location']
        if hasattr(self, 'metadata_encryption_key'):
            key = self.metadata_encryption_key
        else:
            key = self.api_server.metadata_encryption_key
        swift_location = crypt.urlsafe_decrypt(key, loc)

        # POST /images with public image named Image1 without uploading data
        image_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        headers['X-Image-Meta-Location'] = swift_location
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)
        self.assertEqual(data['image']['checksum'], None)
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "Image1")
        self.assertEqual(data['image']['is_public'], True)

        image_id2 = data['image']['id']

        # GET /images/2 ensuring the data already in swift is accessible
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id2)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())

        # DELETE boty images
        # Verify image and all chunks are gone...
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              image_id2)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()

    def _do_test_copy_from(self, from_store, get_uri):
        """
        Ensure we can copy from an external image in from_store.
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port
        registry_port = self.registry_port

        # POST /images with public image to be stored in from_store,
        # to stand in for the 'external' image
        image_data = "*" * FIVE_KB
        headers = minimal_headers('external')
        headers['X-Image-Meta-Store'] = from_store
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)

        original_image_id = data['image']['id']

        copy_from = get_uri(self, original_image_id)

        # POST /images with public image copied from_store (to Swift)
        headers = {'X-Image-Meta-Name': 'copied',
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)

        copy_image_id = data['image']['id']
        self.assertNotEqual(copy_image_id, original_image_id)

        # GET image and make sure image content is as expected
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "copied")

        # DELETE original image
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              original_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        # GET image again to make sure the existence of the original
        # image in from_store is not depended on
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "copied")

        # DELETE copied image
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_swift(self):
        """
        Ensure we can copy from an external image in Swift.
        """
        self._do_test_copy_from('swift', get_swift_uri)

    @requires(setup_s3, teardown_s3)
    @skip_if_disabled
    def test_copy_from_s3(self):
        """
        Ensure we can copy from an external image in S3.
        """
        self._do_test_copy_from('s3', get_s3_uri)

    @requires(setup_http, teardown_http)
    @skip_if_disabled
    def test_copy_from_http(self):
        """
        Ensure we can copy from an external image in HTTP.
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port
        registry_port = self.registry_port

        copy_from = get_http_uri(self, 'foobar')

        # POST /images with public image copied HTTP (to Swift)
        headers = {'X-Image-Meta-Name': 'copied',
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/images" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 201, content)
        data = json.loads(content)

        copy_image_id = data['image']['id']

        # GET image and make sure image content is as expected
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "copied")

        # DELETE copied image
        path = "http://%s:%d/v1/images/%s" % ("0.0.0.0", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()
