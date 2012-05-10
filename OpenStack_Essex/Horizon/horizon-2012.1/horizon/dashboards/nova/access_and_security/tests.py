# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Nebula, Inc.
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

from django import http
from django.core.urlresolvers import reverse
from mox import IsA
from copy import deepcopy

from horizon import api
from horizon import test


class AccessAndSecurityTests(test.TestCase):
    def test_index(self):
        keypairs = self.keypairs.list()
        sec_groups = self.security_groups.list()
        floating_ips = self.floating_ips.list()
        self.mox.StubOutWithMock(api, 'tenant_floating_ip_list')
        self.mox.StubOutWithMock(api, 'security_group_list')
        self.mox.StubOutWithMock(api.nova, 'keypair_list')

        api.nova.keypair_list(IsA(http.HttpRequest)).AndReturn(keypairs)
        api.tenant_floating_ip_list(IsA(http.HttpRequest)) \
                                    .AndReturn(floating_ips)
        api.security_group_list(IsA(http.HttpRequest)).AndReturn(sec_groups)

        self.mox.ReplayAll()

        res = self.client.get(
                             reverse('horizon:nova:access_and_security:index'))

        self.assertTemplateUsed(res, 'nova/access_and_security/index.html')
        self.assertItemsEqual(res.context['keypairs_table'].data, keypairs)
        self.assertItemsEqual(res.context['security_groups_table'].data,
                              sec_groups)
        self.assertItemsEqual(res.context['floating_ips_table'].data,
                              floating_ips)

    def test_association(self):
        floating_ip = self.floating_ips.first()
        servers = self.servers.list()

        # Add duplicate instance name to test instance name with [IP]
        # change id and private IP
        server3 = api.nova.Server(self.servers.first(), self.request)
        server3.id = 101
        server3.addresses = deepcopy(server3.addresses)
        server3.addresses['private'][0]['addr'] = "10.0.0.5"
        self.servers.add(server3)

        self.mox.StubOutWithMock(api, 'tenant_floating_ip_get')
        self.mox.StubOutWithMock(api, 'server_list')
        api.tenant_floating_ip_get(IsA(http.HttpRequest),
                                   floating_ip.id).AndReturn(floating_ip)
        api.server_list(IsA(http.HttpRequest)).AndReturn(servers)
        self.mox.ReplayAll()

        res = self.client.get(
                             reverse("horizon:nova:access_and_security:"
                                     "floating_ips:associate",
                                     args=[floating_ip.id]))
        self.assertTemplateUsed(res,
                                'nova/access_and_security/'
                                'floating_ips/associate.html')

        self.assertContains(res, '<option value="1">server_1 [1]'
                            '</option>')
        self.assertContains(res, '<option value="101">server_1 [101]'
                            '</option>')
        self.assertContains(res, '<option value="2">server_2</option>')
