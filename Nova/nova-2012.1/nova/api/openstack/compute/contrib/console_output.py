# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2011 Grid Dynamics
# Copyright 2011 Eldar Nugaev, Kirill Shileev, Ilya Alekseyev
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
#    under the License

import re
import webob

from nova import compute
from nova import exception
from nova import log as logging
from nova.api.openstack import extensions
from nova.api.openstack import wsgi


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'console_output')


class ConsoleOutputController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ConsoleOutputController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.action('os-getConsoleOutput')
    def get_console_output(self, req, id, body):
        """Get text console output."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            instance = self.compute_api.get(context, id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound(_('Instance not found'))

        try:
            length = body['os-getConsoleOutput'].get('length')
        except (TypeError, KeyError):
            raise webob.exc.HTTPBadRequest(_('Malformed request body'))

        try:
            output = self.compute_api.get_console_output(context,
                                                         instance,
                                                         length)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound(_('Instance not found'))

        # XML output is not correctly escaped, so remove invalid characters
        remove_re = re.compile('[\x00-\x08\x0B-\x0C\x0E-\x1F]')
        output = remove_re.sub('', output)

        return {'output': output}


class Console_output(extensions.ExtensionDescriptor):
    """Console log output support, with tailing ability."""

    name = "Console_output"
    alias = "os-console-output"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "os-console-output/api/v2")
    updated = "2011-12-08T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ConsoleOutputController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
