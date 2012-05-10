# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

""" Keypair management extension"""

import string

import webob
import webob.exc

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova import crypto
from nova import db
from nova import exception


authorize = extensions.extension_authorizer('compute', 'keypairs')


class KeypairTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        return xmlutil.MasterTemplate(xmlutil.make_flat_dict('keypair'), 1)


class KeypairsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('keypairs')
        elem = xmlutil.make_flat_dict('keypair', selector='keypairs',
                                      subselector='keypair')
        root.append(elem)

        return xmlutil.MasterTemplate(root, 1)


class KeypairController(object):
    """ Keypair API controller for the OpenStack API """

    # TODO(ja): both this file and nova.api.ec2.cloud.py have similar logic.
    # move the common keypair logic to nova.compute.API?

    def _gen_key(self):
        """
        Generate a key
        """
        private_key, public_key, fingerprint = crypto.generate_key_pair()
        return {'private_key': private_key,
                'public_key': public_key,
                'fingerprint': fingerprint}

    def _validate_keypair_name(self, value):
        safechars = "_-" + string.digits + string.ascii_letters
        clean_value = "".join(x for x in value if x in safechars)
        if clean_value != value:
            msg = _("Keypair name contains unsafe characters")
            raise webob.exc.HTTPBadRequest(explanation=msg)

    @wsgi.serializers(xml=KeypairTemplate)
    def create(self, req, body):
        """
        Create or import keypair.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: keypair object with:
            name (required) - string
            public_key (optional) - string
        """

        context = req.environ['nova.context']
        authorize(context)
        params = body['keypair']
        name = params['name']
        self._validate_keypair_name(name)

        if not 0 < len(name) < 256:
            msg = _('Keypair name must be between 1 and 255 characters long')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        # NOTE(ja): generation is slow, so shortcut invalid name exception
        try:
            db.key_pair_get(context, context.user_id, name)
            msg = _("Key pair '%s' already exists.") % name
            raise webob.exc.HTTPConflict(explanation=msg)
        except exception.NotFound:
            pass

        keypair = {'user_id': context.user_id,
                   'name': name}

        # import if public_key is sent
        if 'public_key' in params:
            try:
                fingerprint = crypto.generate_fingerprint(params['public_key'])
            except exception.InvalidKeypair:
                msg = _("Keypair data is invalid")
                raise webob.exc.HTTPBadRequest(explanation=msg)

            keypair['public_key'] = params['public_key']
            keypair['fingerprint'] = fingerprint
        else:
            generated_key = self._gen_key()
            keypair['private_key'] = generated_key['private_key']
            keypair['public_key'] = generated_key['public_key']
            keypair['fingerprint'] = generated_key['fingerprint']

        db.key_pair_create(context, keypair)
        return {'keypair': keypair}

    def delete(self, req, id):
        """
        Delete a keypair with a given name
        """
        context = req.environ['nova.context']
        authorize(context)
        try:
            db.key_pair_destroy(context, context.user_id, id)
        except exception.KeypairNotFound:
            raise webob.exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=KeypairsTemplate)
    def index(self, req):
        """
        List of keypairs for a user
        """
        context = req.environ['nova.context']
        authorize(context)
        key_pairs = db.key_pair_get_all_by_user(context, context.user_id)
        rval = []
        for key_pair in key_pairs:
            rval.append({'keypair': {
                'name': key_pair['name'],
                'public_key': key_pair['public_key'],
                'fingerprint': key_pair['fingerprint'],
            }})

        return {'keypairs': rval}


class Keypairs(extensions.ExtensionDescriptor):
    """Keypair Support"""

    name = "Keypairs"
    alias = "os-keypairs"
    namespace = "http://docs.openstack.org/compute/ext/keypairs/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
                'os-keypairs',
                KeypairController())

        resources.append(res)
        return resources
