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

from tests import utils
from tests.v1_1 import fakes


cs = fakes.FakeClient()


class QuotaSetsTest(utils.TestCase):

    def test_tenant_quotas_get(self):
        tenant_id = 'test'
        cs.quotas.get(tenant_id)
        cs.assert_called('GET', '/os-quota-sets/%s' % tenant_id)

    def test_tenant_quotas_defaults(self):
        tenant_id = 'test'
        cs.quotas.defaults(tenant_id)
        cs.assert_called('GET', '/os-quota-sets/%s/defaults' % tenant_id)

    def test_update_quota(self):
        q = cs.quotas.get('test')
        q.update(volumes=2)
        cs.assert_called('PUT', '/os-quota-sets/test')

    def test_refresh_quota(self):
        q = cs.quotas.get('test')
        q2 = cs.quotas.get('test')
        self.assertEqual(q.volumes, q2.volumes)
        q2.volumes = 0
        self.assertNotEqual(q.volumes, q2.volumes)
        q2.get()
        self.assertEqual(q.volumes, q2.volumes)
