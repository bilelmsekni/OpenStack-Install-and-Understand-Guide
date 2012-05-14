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

import logging

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from horizon import api
from horizon import exceptions
from horizon import forms
from horizon import tables
from .forms import CreateUserForm, UpdateUserForm
from .tables import UsersTable


LOG = logging.getLogger(__name__)


class IndexView(tables.DataTableView):
    table_class = UsersTable
    template_name = 'syspanel/users/index.html'

    def get_data(self):
        users = []
        try:
            users = api.keystone.user_list(self.request)
        except:
            exceptions.handle(self.request,
                              _('Unable to retrieve user list.'))
        return users


class UpdateView(forms.ModalFormView):
    form_class = UpdateUserForm
    template_name = 'syspanel/users/update.html'
    context_object_name = 'user'

    def get_object(self, *args, **kwargs):
        user_id = kwargs['user_id']
        try:
            return api.user_get(self.request, user_id, admin=True)
        except:
            redirect = reverse("horizon:syspanel:users:index")
            exceptions.handle(self.request,
                              _('Unable to update user.'),
                              redirect=redirect)

    def get_initial(self):
        return {'id': self.object.id,
                'name': getattr(self.object, 'name', None),
                'tenant_id': getattr(self.object, 'tenantId', None),
                'email': getattr(self.object, 'email', '')}


class CreateView(forms.ModalFormView):
    form_class = CreateUserForm
    template_name = 'syspanel/users/create.html'
