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

"""
Views for managing Nova keypairs.
"""
import logging

from django import http
from django.core.urlresolvers import reverse
from django.template.defaultfilters import slugify
from django.views.generic import View, TemplateView
from django.utils.translation import ugettext_lazy as _

from .forms import CreateKeypair, ImportKeypair
from horizon import api
from horizon import forms
from horizon import exceptions


LOG = logging.getLogger(__name__)


class CreateView(forms.ModalFormView):
    form_class = CreateKeypair
    template_name = 'nova/access_and_security/keypairs/create.html'


class ImportView(forms.ModalFormView):
    form_class = ImportKeypair
    template_name = 'nova/access_and_security/keypairs/import.html'


class DownloadView(TemplateView):
    def get_context_data(self, keypair_name=None):
        return {'keypair_name': keypair_name}
    template_name = 'nova/access_and_security/keypairs/download.html'


class GenerateView(View):
    def get(self, request, keypair_name=None):
        try:
            keypair = api.keypair_create(request, keypair_name)
        except:
            redirect = reverse('horizon:nova:access_and_security:index')
            exceptions.handle(self.request,
                              _('Unable to create keypair: %(exc)s'),
                              redirect=redirect)

        response = http.HttpResponse(mimetype='application/binary')
        response['Content-Disposition'] = \
                'attachment; filename=%s.pem' % slugify(keypair.name)
        response.write(keypair.private_key)
        response['Content-Length'] = str(len(response.content))
        return response
