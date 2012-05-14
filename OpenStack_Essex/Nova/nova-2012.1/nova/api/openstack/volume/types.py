# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

""" The volume type & volume types extra specs extension"""

from webob import exc

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova.volume import volume_types


def make_voltype(elem):
    elem.set('id')
    elem.set('name')
    extra_specs = xmlutil.make_flat_dict('extra_specs', selector='extra_specs')
    elem.append(extra_specs)


class VolumeTypeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_type', selector='volume_type')
        make_voltype(root)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_types')
        elem = xmlutil.SubTemplateElement(root, 'volume_type',
                                          selector='volume_types')
        make_voltype(elem)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesController(object):
    """ The volume types API controller for the OpenStack API """

    @wsgi.serializers(xml=VolumeTypesTemplate)
    def index(self, req):
        """ Returns the list of volume types """
        context = req.environ['nova.context']
        return {'volume_types': volume_types.get_all_types(context).values()}

    @wsgi.serializers(xml=VolumeTypeTemplate)
    def show(self, req, id):
        """ Return a single volume type item """
        context = req.environ['nova.context']

        try:
            vol_type = volume_types.get_volume_type(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        # TODO(bcwaldon): remove str cast once we use uuids
        vol_type['id'] = str(vol_type['id'])
        return {'volume_type': vol_type}


def create_resource():
    return wsgi.Resource(VolumeTypesController())
