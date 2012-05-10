# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from nova import crypto
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.auth import manager
from nova.api.ec2 import cloud
from nova.auth import fakeldap

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class user_generator(object):
    def __init__(self, manager, **user_state):
        if 'name' not in user_state:
            user_state['name'] = 'test1'
        self.manager = manager
        self.user = manager.create_user(**user_state)

    def __enter__(self):
        return self.user

    def __exit__(self, value, type, trace):
        self.manager.delete_user(self.user)


class project_generator(object):
    def __init__(self, manager, **project_state):
        if 'name' not in project_state:
            project_state['name'] = 'testproj'
        if 'manager_user' not in project_state:
            project_state['manager_user'] = 'test1'
        self.manager = manager
        self.project = manager.create_project(**project_state)

    def __enter__(self):
        return self.project

    def __exit__(self, value, type, trace):
        self.manager.delete_project(self.project)


class user_and_project_generator(object):
    def __init__(self, manager, user_state=None, project_state=None):
        if not user_state:
            user_state = {}
        if not project_state:
            project_state = {}

        self.manager = manager
        if 'name' not in user_state:
            user_state['name'] = 'test1'
        if 'name' not in project_state:
            project_state['name'] = 'testproj'
        if 'manager_user' not in project_state:
            project_state['manager_user'] = 'test1'
        self.user = manager.create_user(**user_state)
        self.project = manager.create_project(**project_state)

    def __enter__(self):
        return (self.user, self.project)

    def __exit__(self, value, type, trace):
        self.manager.delete_user(self.user)
        self.manager.delete_project(self.project)


class _AuthManagerBaseTestCase(test.TestCase):

    user_not_found_type = exception.UserNotFound

    def setUp(self):
        super(_AuthManagerBaseTestCase, self).setUp()
        self.flags(auth_driver=self.auth_driver,
                connection_type='fake')
        self.manager = manager.AuthManager(new=True)
        self.manager.mc.cache = {}

    def test_create_and_find_user(self):
        with user_generator(self.manager):
            self.assert_(self.manager.get_user('test1'))

    def test_create_and_find_with_properties(self):
        with user_generator(self.manager, name="herbert", secret="classified",
                        access="private-party"):
            u = self.manager.get_user('herbert')
            self.assertEqual('herbert', u.id)
            self.assertEqual('herbert', u.name)
            self.assertEqual('classified', u.secret)
            self.assertEqual('private-party', u.access)

    def test_create_user_twice(self):
        self.manager.create_user('test-1')
        self.assertRaises(exception.UserExists, self.manager.create_user,
                          'test-1')

    def test_signature_is_valid(self):
        with user_generator(self.manager, name='admin', secret='admin',
                            access='admin'):
            with project_generator(self.manager, name="admin",
                                   manager_user='admin'):
                accesskey = 'admin:admin'
                expected_result = (self.manager.get_user('admin'),
                                   self.manager.get_project('admin'))
                # captured sig and query string using boto 1.9b/euca2ools 1.2
                sig = 'd67Wzd9Bwz8xid9QU+lzWXcF2Y3tRicYABPJgrqfrwM='
                auth_params = {'AWSAccessKeyId': 'admin:admin',
                               'Action': 'DescribeAvailabilityZones',
                               'SignatureMethod': 'HmacSHA256',
                               'SignatureVersion': '2',
                               'Timestamp': '2011-04-22T11:29:29',
                               'Version': '2009-11-30'}
                self.assertTrue(expected_result, self.manager.authenticate(
                        accesskey,
                        sig,
                        auth_params,
                        'GET',
                        '127.0.0.1:8773',
                        '/services/Cloud/'))
                # captured sig and query string using RightAWS 1.10.0
                sig = 'ECYLU6xdFG0ZqRVhQybPJQNJ5W4B9n8fGs6+/fuGD2c='
                auth_params = {'AWSAccessKeyId': 'admin:admin',
                               'Action': 'DescribeAvailabilityZones',
                               'SignatureMethod': 'HmacSHA256',
                               'SignatureVersion': '2',
                               'Timestamp': '2011-04-22T11:29:49.000Z',
                               'Version': '2008-12-01'}
                self.assertTrue(expected_result, self.manager.authenticate(
                        accesskey,
                        sig,
                        auth_params,
                        'GET',
                        '127.0.0.1',
                        '/services/Cloud'))

    def test_can_get_credentials(self):
        self.flags(auth_strategy='deprecated')
        st = {'access': 'access', 'secret': 'secret'}
        with user_and_project_generator(self.manager, user_state=st) as (u, p):
            credentials = self.manager.get_environment_rc(u, p)
            LOG.debug(credentials)
            self.assertTrue('export EC2_ACCESS_KEY="access:testproj"\n'
                            in credentials)
            self.assertTrue('export EC2_SECRET_KEY="secret"\n' in credentials)

    def test_can_list_users(self):
        with user_generator(self.manager):
            with user_generator(self.manager, name="test2"):
                users = self.manager.get_users()
                self.assert_(filter(lambda u: u.id == 'test1', users))
                self.assert_(filter(lambda u: u.id == 'test2', users))
                self.assert_(not filter(lambda u: u.id == 'test3', users))

    def test_can_add_and_remove_user_role(self):
        with user_generator(self.manager):
            self.assertFalse(self.manager.has_role('test1', 'itsec'))
            self.manager.add_role('test1', 'itsec')
            self.assertTrue(self.manager.has_role('test1', 'itsec'))
            self.manager.remove_role('test1', 'itsec')
            self.assertFalse(self.manager.has_role('test1', 'itsec'))

    def test_can_create_and_get_project(self):
        with user_and_project_generator(self.manager) as (u, p):
            self.assert_(self.manager.get_user('test1'))
            self.assert_(self.manager.get_user('test1'))
            self.assert_(self.manager.get_project('testproj'))

    def test_can_list_projects(self):
        with user_and_project_generator(self.manager):
            with project_generator(self.manager, name="testproj2"):
                projects = self.manager.get_projects()
                self.assert_(filter(lambda p: p.name == 'testproj', projects))
                self.assert_(filter(lambda p: p.name == 'testproj2', projects))
                self.assert_(not filter(lambda p: p.name == 'testproj3',
                                        projects))

    def test_can_create_and_get_project_with_attributes(self):
        with user_generator(self.manager):
            with project_generator(self.manager, description='A test project'):
                project = self.manager.get_project('testproj')
                self.assertEqual('A test project', project.description)

    def test_can_create_project_with_manager(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.assertEqual('test1', project.project_manager_id)
            self.assertTrue(self.manager.is_project_manager(user, project))

    def test_can_create_project_twice(self):
        with user_and_project_generator(self.manager) as (user1, project):
            self.assertRaises(exception.ProjectExists,
                              self.manager.create_project, "testproj", "test1")

    def test_create_project_assigns_manager_to_members(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.assertTrue(self.manager.is_project_member(user, project))

    def test_create_project_with_manager_and_members(self):
        with user_generator(self.manager, name='test2') as user2:
            with user_and_project_generator(self.manager,
                project_state={'member_users': ['test2']}) as (user1, project):
                    self.assertTrue(self.manager.is_project_member(
                        user1, project))
                    self.assertTrue(self.manager.is_project_member(
                        user2, project))

    def test_create_project_with_manager_and_missing_members(self):
        self.assertRaises(self.user_not_found_type,
                          self.manager.create_project, "testproj", "test1",
                          member_users="test2")

    def test_no_extra_project_members(self):
        with user_generator(self.manager, name='test2') as baduser:
            with user_and_project_generator(self.manager) as (user, project):
                self.assertFalse(self.manager.is_project_member(baduser,
                                                                 project))

    def test_no_extra_project_managers(self):
        with user_generator(self.manager, name='test2') as baduser:
            with user_and_project_generator(self.manager) as (user, project):
                self.assertFalse(self.manager.is_project_manager(baduser,
                                                                 project))

    def test_can_add_user_to_project(self):
        with user_generator(self.manager, name='test2') as user:
            with user_and_project_generator(self.manager) as (_user, project):
                self.manager.add_to_project(user, project)
                project = self.manager.get_project('testproj')
                self.assertTrue(self.manager.is_project_member(user, project))

    def test_can_remove_user_from_project(self):
        with user_generator(self.manager, name='test2') as user:
            with user_and_project_generator(self.manager) as (_user, project):
                self.manager.add_to_project(user, project)
                project = self.manager.get_project('testproj')
                self.assertTrue(self.manager.is_project_member(user, project))
                self.manager.remove_from_project(user, project)
                project = self.manager.get_project('testproj')
                self.assertFalse(self.manager.is_project_member(user, project))

    def test_can_add_remove_user_with_role(self):
        with user_generator(self.manager, name='test2') as user:
            with user_and_project_generator(self.manager) as (_user, project):
                # NOTE(todd): after modifying users you must reload project
                self.manager.add_to_project(user, project)
                project = self.manager.get_project('testproj')
                self.manager.add_role(user, 'developer', project)
                self.assertTrue(self.manager.is_project_member(user, project))
                self.manager.remove_from_project(user, project)
                project = self.manager.get_project('testproj')
                self.assertFalse(self.manager.has_role(user, 'developer',
                                                       project))
                self.assertFalse(self.manager.is_project_member(user, project))

    def test_adding_role_to_project_is_ignored_unless_added_to_user(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))
            self.manager.add_role(user, 'sysadmin', project)
            # NOTE(todd): it will still show up in get_user_roles(u, project)
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))
            self.manager.add_role(user, 'sysadmin')
            self.assertTrue(self.manager.has_role(user, 'sysadmin', project))

    def test_add_user_role_doesnt_infect_project_roles(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))
            self.manager.add_role(user, 'sysadmin')
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))

    def test_can_list_user_roles(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.manager.add_role(user, 'sysadmin')
            roles = self.manager.get_user_roles(user)
            self.assertTrue('sysadmin' in roles)
            self.assertFalse('netadmin' in roles)

    def test_can_list_project_roles(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.manager.add_role(user, 'sysadmin')
            self.manager.add_role(user, 'sysadmin', project)
            self.manager.add_role(user, 'netadmin', project)
            project_roles = self.manager.get_user_roles(user, project)
            self.assertTrue('sysadmin' in project_roles)
            self.assertTrue('netadmin' in project_roles)
            # has role should be false user-level role is missing
            self.assertFalse(self.manager.has_role(user, 'netadmin', project))

    def test_can_remove_user_roles(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.manager.add_role(user, 'sysadmin')
            self.assertTrue(self.manager.has_role(user, 'sysadmin'))
            self.manager.remove_role(user, 'sysadmin')
            self.assertFalse(self.manager.has_role(user, 'sysadmin'))

    def test_removing_user_role_hides_it_from_project(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.manager.add_role(user, 'sysadmin')
            self.manager.add_role(user, 'sysadmin', project)
            self.assertTrue(self.manager.has_role(user, 'sysadmin', project))
            self.manager.remove_role(user, 'sysadmin')
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))

    def test_can_remove_project_role_but_keep_user_role(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.manager.add_role(user, 'sysadmin')
            self.manager.add_role(user, 'sysadmin', project)
            self.assertTrue(self.manager.has_role(user, 'sysadmin'))
            self.manager.remove_role(user, 'sysadmin', project)
            self.assertFalse(self.manager.has_role(user, 'sysadmin', project))
            self.assertTrue(self.manager.has_role(user, 'sysadmin'))

    def test_can_retrieve_project_by_user(self):
        with user_and_project_generator(self.manager) as (user, project):
            self.assertEqual(1, len(self.manager.get_projects('test1')))

    def test_can_modify_project(self):
        with user_and_project_generator(self.manager):
            with user_generator(self.manager, name='test2'):
                self.manager.modify_project('testproj', 'test2', 'new desc')
                project = self.manager.get_project('testproj')
                self.assertEqual('test2', project.project_manager_id)
                self.assertEqual('new desc', project.description)

    def test_can_call_modify_project_but_do_nothing(self):
        with user_and_project_generator(self.manager):
            self.manager.modify_project('testproj')
            project = self.manager.get_project('testproj')
            self.assertEqual('test1', project.project_manager_id)
            self.assertEqual('testproj', project.description)

    def test_modify_project_adds_new_manager(self):
        with user_and_project_generator(self.manager):
            with user_generator(self.manager, name='test2'):
                self.manager.modify_project('testproj', 'test2', 'new desc')
                project = self.manager.get_project('testproj')
                self.assertTrue('test2' in project.member_ids)

    def test_create_project_with_missing_user(self):
        with user_generator(self.manager):
            self.assertRaises(self.user_not_found_type,
                              self.manager.create_project, 'testproj',
                              'not_real')

    def test_can_delete_project(self):
        with user_generator(self.manager):
            self.manager.create_project('testproj', 'test1')
            self.assert_(self.manager.get_project('testproj'))
            self.manager.delete_project('testproj')
            projectlist = self.manager.get_projects()
            self.assert_(not filter(lambda p: p.name == 'testproj',
                         projectlist))

    def test_can_delete_user(self):
        self.manager.create_user('test1')
        self.assert_(self.manager.get_user('test1'))
        self.manager.delete_user('test1')
        userlist = self.manager.get_users()
        self.assert_(not filter(lambda u: u.id == 'test1', userlist))

    def test_can_modify_users(self):
        with user_generator(self.manager):
            self.manager.modify_user('test1', 'access', 'secret', True)
            user = self.manager.get_user('test1')
            self.assertEqual('access', user.access)
            self.assertEqual('secret', user.secret)
            self.assertTrue(user.is_admin())

    def test_can_call_modify_user_but_do_nothing(self):
        with user_generator(self.manager):
            old_user = self.manager.get_user('test1')
            self.manager.modify_user('test1')
            user = self.manager.get_user('test1')
            self.assertEqual(old_user.access, user.access)
            self.assertEqual(old_user.secret, user.secret)
            self.assertEqual(old_user.is_admin(), user.is_admin())

    def test_get_nonexistent_user_raises_notfound_exception(self):
        self.assertRaises(exception.NotFound,
                          self.manager.get_user,
                          'joeblow')


class AuthManagerLdapTestCase(_AuthManagerBaseTestCase):
    auth_driver = 'nova.auth.ldapdriver.FakeLdapDriver'
    user_not_found_type = exception.LDAPUserNotFound

    def test_reconnect_on_server_failure(self):
        self.manager.get_users()
        fakeldap.server_fail = True
        try:
            self.assertRaises(fakeldap.SERVER_DOWN, self.manager.get_users)
        finally:
            fakeldap.server_fail = False
        self.manager.get_users()


class AuthManagerDbTestCase(_AuthManagerBaseTestCase):
    auth_driver = 'nova.auth.dbdriver.DbDriver'
    user_not_found_type = exception.UserNotFound


if __name__ == "__main__":
    # TODO(anotherjesse): Implement use_fake as an option
    unittest.main()
