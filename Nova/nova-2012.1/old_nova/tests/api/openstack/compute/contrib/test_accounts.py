# Copyright 2010 OpenStack LLC.
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


import json

from lxml import etree
import webob

from nova import test
from nova.api.openstack.compute.contrib import accounts
from nova.auth import manager as auth_manager
from nova.tests.api.openstack import fakes


def fake_init(self):
    self.manager = fakes.FakeAuthManager()


class AccountsTest(test.TestCase):
    def setUp(self):
        super(AccountsTest, self).setUp()
        self.flags(verbose=True)
        self.stubs.Set(accounts.Controller, '__init__',
                       fake_init)
        fakes.FakeAuthManager.clear_fakes()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)

        fakemgr = fakes.FakeAuthManager()
        joeuser = auth_manager.User('id1', 'guy1', 'acc1', 'secret1', False)
        superuser = auth_manager.User('id2', 'guy2', 'acc2', 'secret2', True)
        fakemgr.add_user(joeuser)
        fakemgr.add_user(superuser)
        fakemgr.create_project('test1', joeuser)
        fakemgr.create_project('test2', superuser)

    def test_get_account(self):
        req = webob.Request.blank('/v2/fake/accounts/test1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['account']['id'], 'test1')
        self.assertEqual(res_dict['account']['name'], 'test1')
        self.assertEqual(res_dict['account']['manager'], 'id1')

    def test_get_account_xml(self):
        req = webob.Request.blank('/v2/fake/accounts/test1.xml')
        res = req.get_response(fakes.wsgi_app())
        res_tree = etree.fromstring(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual('account', res_tree.tag)
        self.assertEqual('test1', res_tree.get('id'))
        self.assertEqual('test1', res_tree.get('name'))
        self.assertEqual('id1', res_tree.get('manager'))

    def test_account_delete(self):
        req = webob.Request.blank('/v2/fake/accounts/test1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertTrue('test1' not in fakes.FakeAuthManager.projects)
        self.assertEqual(res.status_int, 200)

    def test_account_create(self):
        body = dict(account=dict(description='test account',
                                 manager='id1'))
        req = webob.Request.blank('/v2/fake/accounts/newacct')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['account']['id'], 'newacct')
        self.assertEqual(res_dict['account']['name'], 'newacct')
        self.assertEqual(res_dict['account']['description'], 'test account')
        self.assertEqual(res_dict['account']['manager'], 'id1')
        self.assertTrue('newacct' in
                        fakes.FakeAuthManager.projects)
        self.assertEqual(len(fakes.FakeAuthManager.projects.values()), 3)

    def test_account_create_xml(self):
        body = dict(account=dict(description='test account',
                                 manager='id1'))
        req = webob.Request.blank('/v2/fake/accounts/newacct.xml')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_tree = etree.fromstring(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_tree.tag, 'account')
        self.assertEqual(res_tree.get('id'), 'newacct')
        self.assertEqual(res_tree.get('name'), 'newacct')
        self.assertEqual(res_tree.get('description'), 'test account')
        self.assertEqual(res_tree.get('manager'), 'id1')
        self.assertTrue('newacct' in
                        fakes.FakeAuthManager.projects)
        self.assertEqual(len(fakes.FakeAuthManager.projects.values()), 3)

    def test_account_update(self):
        body = dict(account=dict(description='test account',
                                 manager='id2'))
        req = webob.Request.blank('/v2/fake/accounts/test1')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['account']['id'], 'test1')
        self.assertEqual(res_dict['account']['name'], 'test1')
        self.assertEqual(res_dict['account']['description'], 'test account')
        self.assertEqual(res_dict['account']['manager'], 'id2')
        self.assertEqual(len(fakes.FakeAuthManager.projects.values()), 2)

    def test_account_update_xml(self):
        body = dict(account=dict(description='test account',
                                 manager='id2'))
        req = webob.Request.blank('/v2/fake/accounts/test1.xml')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_tree = etree.fromstring(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_tree.tag, 'account')
        self.assertEqual(res_tree.get('id'), 'test1')
        self.assertEqual(res_tree.get('name'), 'test1')
        self.assertEqual(res_tree.get('description'), 'test account')
        self.assertEqual(res_tree.get('manager'), 'id2')
        self.assertEqual(len(fakes.FakeAuthManager.projects.values()), 2)
