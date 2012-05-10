# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Nebula Inc
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

from django.http import HttpRequest
from django.core.urlresolvers import reverse
from mox import IsA

from horizon import api
from horizon import test
from .forms import DownloadX509Credentials


INDEX_URL = reverse("horizon:settings:ec2:index")


class EC2SettingsTest(test.TestCase):
    def test_ec2_download_view(self):
        creds = self.ec2.first()
        cert = self.certs.first()

        self.mox.StubOutWithMock(api.keystone, "tenant_list")
        self.mox.StubOutWithMock(api.keystone, "token_create_scoped")
        self.mox.StubOutWithMock(api.keystone, "list_ec2_credentials")
        self.mox.StubOutWithMock(api.nova, "get_x509_credentials")
        self.mox.StubOutWithMock(api.nova, "get_x509_root_certificate")
        self.mox.StubOutWithMock(api.keystone, "create_ec2_credentials")

        # GET request
        api.keystone.tenant_list(IsA(HttpRequest)) \
                    .AndReturn(self.tenants.list())

        # POST request
        api.keystone.token_create_scoped(IsA(HttpRequest),
                                         self.tenant.id,
                                         IsA(str)) \
                                         .AndReturn(self.tokens.scoped_token)
        api.keystone.tenant_list(IsA(HttpRequest)) \
                    .AndReturn(self.tenants.list())
        api.keystone.list_ec2_credentials(IsA(HttpRequest), self.user.id) \
                    .AndReturn([])
        api.nova.get_x509_credentials(IsA(HttpRequest)).AndReturn(cert)
        api.nova.get_x509_root_certificate(IsA(HttpRequest)) \
                .AndReturn(cert)
        api.keystone.create_ec2_credentials(IsA(HttpRequest),
                                            self.user.id,
                                            self.tenant.id).AndReturn(creds)
        self.mox.ReplayAll()

        res = self.client.get(INDEX_URL)
        self.assertNoMessages()
        self.assertEqual(res.status_code, 200)

        data = {'method': DownloadX509Credentials.__name__,
                'tenant': self.tenant.id}
        res = self.client.post(INDEX_URL, data)
        self.assertEqual(res['content-type'], 'application/zip')
