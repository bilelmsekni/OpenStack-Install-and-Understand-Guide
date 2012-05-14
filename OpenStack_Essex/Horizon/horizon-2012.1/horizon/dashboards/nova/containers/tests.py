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

import tempfile

from cloudfiles.errors import ContainerNotEmpty
from django import http
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.urlresolvers import reverse
from mox import IsA

from horizon import api
from horizon import test
from .tables import ContainersTable, ObjectsTable
from . import forms


CONTAINER_INDEX_URL = reverse('horizon:nova:containers:index')


class ContainerViewTests(test.TestCase):
    def test_index(self):
        containers = self.containers.list()
        self.mox.StubOutWithMock(api, 'swift_get_containers')
        api.swift_get_containers(IsA(http.HttpRequest), marker=None) \
                                .AndReturn((containers, False))
        self.mox.ReplayAll()

        res = self.client.get(CONTAINER_INDEX_URL)

        self.assertTemplateUsed(res, 'nova/containers/index.html')
        self.assertIn('table', res.context)
        resp_containers = res.context['table'].data
        self.assertEqual(len(resp_containers), len(containers))

    def test_delete_container(self):
        container = self.containers.get(name=u"container_two\u6346")
        self.mox.StubOutWithMock(api, 'swift_delete_container')
        api.swift_delete_container(IsA(http.HttpRequest), container.name)
        self.mox.ReplayAll()

        action_string = u"containers__delete__%s" % container.name
        form_data = {"action": action_string}
        req = self.factory.post(CONTAINER_INDEX_URL, form_data)
        table = ContainersTable(req, self.containers.list())
        handled = table.maybe_handle()
        self.assertEqual(handled['location'], CONTAINER_INDEX_URL)

    def test_delete_container_nonempty(self):
        container = self.containers.first()
        self.mox.StubOutWithMock(api, 'swift_delete_container')
        exc = ContainerNotEmpty('containerNotEmpty')
        api.swift_delete_container(IsA(http.HttpRequest),
                                   container.name).AndRaise(exc)
        self.mox.ReplayAll()

        action_string = u"containers__delete__%s" % container.name
        form_data = {"action": action_string}
        req = self.factory.post(CONTAINER_INDEX_URL, form_data)
        table = ContainersTable(req, self.containers.list())
        handled = table.maybe_handle()
        self.assertEqual(handled['location'], CONTAINER_INDEX_URL)

    def test_create_container_get(self):
        res = self.client.get(reverse('horizon:nova:containers:create'))
        self.assertTemplateUsed(res, 'nova/containers/create.html')

    def test_create_container_post(self):
        self.mox.StubOutWithMock(api, 'swift_create_container')
        api.swift_create_container(IsA(http.HttpRequest),
                                   self.containers.first().name)
        self.mox.ReplayAll()

        formData = {'name': self.containers.first().name,
                    'method': forms.CreateContainer.__name__}
        res = self.client.post(reverse('horizon:nova:containers:create'),
                               formData)
        self.assertRedirectsNoFollow(res, CONTAINER_INDEX_URL)


class ObjectViewTests(test.TestCase):
    def test_index(self):
        self.mox.StubOutWithMock(api, 'swift_get_objects')
        ret = (self.objects.list(), False)
        api.swift_get_objects(IsA(http.HttpRequest),
                              self.containers.first().name,
                              marker=None).AndReturn(ret)
        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:nova:containers:object_index',
                                      args=[self.containers.first().name]))
        self.assertTemplateUsed(res, 'nova/objects/index.html')
        expected = [obj.name for obj in self.objects.list()]
        self.assertQuerysetEqual(res.context['table'].data,
                                 expected,
                                 lambda obj: obj.name)

    def test_upload_index(self):
        res = self.client.get(reverse('horizon:nova:containers:object_upload',
                                      args=[self.containers.first().name]))
        self.assertTemplateUsed(res, 'nova/objects/upload.html')

    def test_upload(self):
        container = self.containers.first()
        obj = self.objects.first()
        OBJECT_DATA = 'objectData'

        temp_file = tempfile.TemporaryFile()
        temp_file.write(OBJECT_DATA)
        temp_file.flush()
        temp_file.seek(0)

        self.mox.StubOutWithMock(api, 'swift_upload_object')
        api.swift_upload_object(IsA(http.HttpRequest),
                                container.name,
                                obj.name,
                                IsA(InMemoryUploadedFile)).AndReturn(obj)
        self.mox.StubOutWithMock(obj, 'sync_metadata')
        obj.sync_metadata()
        self.mox.ReplayAll()
        upload_url = reverse('horizon:nova:containers:object_upload',
                             args=[container.name])
        res = self.client.get(upload_url)
        self.assertContains(res, 'enctype="multipart/form-data"')

        formData = {'method': forms.UploadObject.__name__,
                    'container_name': container.name,
                    'name': obj.name,
                    'object_file': temp_file}
        res = self.client.post(upload_url, formData)

        index_url = reverse('horizon:nova:containers:object_index',
                            args=[container.name])
        self.assertRedirectsNoFollow(res, index_url)

        # Test invalid filename
        formData['name'] = "contains/a/slash"
        res = self.client.post(upload_url, formData)
        self.assertNoMessages()
        self.assertContains(res, "Slash is not an allowed character.")

        # Test invalid container name
        #formData['container_name'] = "contains/a/slash"
        #formData['name'] = "no_slash"
        #res = self.client.post(upload_url, formData)
        #self.assertNoMessages()
        #self.assertContains(res, "Slash is not an allowed character.")

    def test_delete(self):
        container = self.containers.first()
        obj = self.objects.first()
        index_url = reverse('horizon:nova:containers:object_index',
                            args=[container.name])
        self.mox.StubOutWithMock(api, 'swift_delete_object')
        api.swift_delete_object(IsA(http.HttpRequest),
                                container.name,
                                obj.name)
        self.mox.ReplayAll()

        action_string = "objects__delete__%s" % obj.name
        form_data = {"action": action_string}
        req = self.factory.post(index_url, form_data)
        kwargs = {"container_name": container.name}
        table = ObjectsTable(req, self.objects.list(), **kwargs)
        handled = table.maybe_handle()
        self.assertEqual(handled['location'], index_url)

    def test_download(self):
        container = self.containers.first()
        obj = self.objects.first()
        OBJECT_DATA = 'objectData'

        self.mox.StubOutWithMock(api, 'swift_get_object_data')
        self.mox.StubOutWithMock(api.swift, 'swift_get_object')
        api.swift.swift_get_object(IsA(http.HttpRequest),
                                   container.name,
                                   obj.name).AndReturn(obj)
        api.swift_get_object_data(IsA(http.HttpRequest),
                                  container.name,
                                  obj.name).AndReturn(OBJECT_DATA)
        self.mox.ReplayAll()

        download_url = reverse('horizon:nova:containers:object_download',
                               args=[container.name, obj.name])
        res = self.client.get(download_url)
        self.assertEqual(res.content, OBJECT_DATA)
        self.assertTrue(res.has_header('Content-Disposition'))

    def test_copy_index(self):
        self.mox.StubOutWithMock(api, 'swift_get_containers')
        ret = (self.containers.list(), False)
        api.swift_get_containers(IsA(http.HttpRequest)).AndReturn(ret)
        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:nova:containers:object_copy',
                                      args=[self.containers.first().name,
                                            self.objects.first().name]))
        self.assertTemplateUsed(res, 'nova/objects/copy.html')

    def test_copy(self):
        container_1 = self.containers.get(name=u"container_one\u6346")
        container_2 = self.containers.get(name=u"container_two\u6346")
        obj = self.objects.first()

        self.mox.StubOutWithMock(api, 'swift_get_containers')
        self.mox.StubOutWithMock(api, 'swift_copy_object')
        ret = (self.containers.list(), False)
        api.swift_get_containers(IsA(http.HttpRequest)).AndReturn(ret)
        api.swift_copy_object(IsA(http.HttpRequest),
                              container_1.name,
                              obj.name,
                              container_2.name,
                              obj.name)
        self.mox.ReplayAll()

        formData = {'method': forms.CopyObject.__name__,
                    'new_container_name': container_2.name,
                    'new_object_name': obj.name,
                    'orig_container_name': container_1.name,
                    'orig_object_name': obj.name}
        copy_url = reverse('horizon:nova:containers:object_copy',
                           args=[container_1.name, obj.name])
        res = self.client.post(copy_url, formData)
        index_url = reverse('horizon:nova:containers:object_index',
                            args=[container_2.name])
        self.assertRedirectsNoFollow(res, index_url)
