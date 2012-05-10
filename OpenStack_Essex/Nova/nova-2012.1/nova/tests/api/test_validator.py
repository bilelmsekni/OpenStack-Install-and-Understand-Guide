# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Cloudscaling, Inc.
# Author: Matthew Hooker <matt@cloudscaling.com>
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

import base64

from nova import test
from nova.api import validator


class ValidatorTestCase(test.TestCase):

    def test_validate(self):
        fixture = {
            'foo': lambda val: val == True
        }

        self.assertTrue(
            validator.validate({'foo': True}, fixture))
        self.assertFalse(
            validator.validate({'foo': False}, fixture))

    def test_only_tests_intersect(self):
        """Test that validator.validate only tests the intersect of keys
        from args and validator.
        """

        fixture = {
            'foo': lambda val: True,
            'bar': lambda val: True
        }

        self.assertTrue(
            validator.validate({'foo': True}, fixture))
        self.assertTrue(
            validator.validate({'foo': True, 'bar': True}, fixture))
        self.assertTrue(
            validator.validate({'foo': True, 'bar': True, 'baz': True},
                               fixture))

    def test_validate_str(self):
        self.assertTrue(validator.validate_str()('foo'))
        self.assertFalse(validator.validate_str()(1))
        self.assertTrue(validator.validate_str(4)('foo'))
        self.assertFalse(validator.validate_str(2)('foo'))
        self.assertFalse(validator.validate_str()(None))
        self.assertTrue(validator.validate_str()(u'foo'))

    def test_validate_int(self):
        self.assertTrue(validator.validate_int()(1))
        self.assertFalse(validator.validate_int()('foo'))
        self.assertTrue(validator.validate_int(100)(1))
        self.assertFalse(validator.validate_int(4)(5))
        self.assertFalse(validator.validate_int()(None))

    def test_validate_ec2_id(self):
        self.assertFalse(validator.validate_ec2_id('foobar'))
        self.assertFalse(validator.validate_ec2_id(''))
        self.assertFalse(validator.validate_ec2_id(1234))
        self.assertTrue(validator.validate_ec2_id('i-284f3a41'))

    def test_validate_ipv4(self):
        self.assertTrue(validator.validate_ipv4('4.2.2.4'))
        self.assertFalse(validator.validate_ipv4('foobar'))
        self.assertFalse(
            validator.validate_ipv4('2001:5a8:4:68e0:e6ce:8fff:fe27:d116'))
        self.assertFalse(validator.validate_ipv4(123))
        self.assertFalse(validator.validate_ipv4(''))

    def test_validate_url_path(self):
        self.assertTrue(validator.validate_url_path('/path/to/file'))
        self.assertFalse(validator.validate_url_path('path/to/file'))
        self.assertFalse(
            validator.validate_url_path('#this is not a path!@#$%^&*()')
        )
        self.assertFalse(validator.validate_url_path(None))
        self.assertFalse(validator.validate_url_path(123))

    def test_validate_image_path(self):
        self.assertTrue(validator.validate_image_path('path/to/file'))
        self.assertFalse(validator.validate_image_path('/path/to/file'))
        self.assertFalse(validator.validate_image_path('path'))

    def test_validate_user_data(self):
        fixture = base64.b64encode('foo')
        self.assertTrue(validator.validate_user_data(fixture))
        self.assertFalse(validator.validate_user_data(False))
        self.assertFalse(validator.validate_user_data('hello, world!'))

    def test_default_validator(self):
        expect_pass = {
            'attribute': 'foobar'
        }
        self.assertTrue(validator.validate(expect_pass,
                                           validator.DEFAULT_VALIDATOR))
        expect_fail = {
            'attribute': 0
        }
        self.assertFalse(validator.validate(expect_fail,
                                            validator.DEFAULT_VALIDATOR))
