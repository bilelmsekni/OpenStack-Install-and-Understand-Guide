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

import unittest

from glance.tests import utils


class TestSkipExamples(unittest.TestCase):
    test_counter = 0

    @utils.skip_test("Example usage of @utils.skip_test()")
    def test_skip_test_example(self):
        self.fail("skip_test failed to work properly.")

    @utils.skip_if(True, "Example usage of @utils.skip_if()")
    def test_skip_if_example(self):
        self.fail("skip_if failed to work properly.")

    @utils.skip_unless(False, "Example usage of @utils.skip_unless()")
    def test_skip_unless_example(self):
        self.fail("skip_unless failed to work properly.")

    @utils.skip_if(False, "This test case should never be skipped.")
    def test_001_increase_test_counter(self):
        TestSkipExamples.test_counter += 1

    @utils.skip_unless(True, "This test case should never be skipped.")
    def test_002_increase_test_counter(self):
        TestSkipExamples.test_counter += 1

    def test_003_verify_test_counter(self):
        self.assertEquals(TestSkipExamples.test_counter, 2,
                          "Tests were not skipped appropriately")
