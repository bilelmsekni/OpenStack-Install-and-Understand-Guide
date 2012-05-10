# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Openstack, LLC
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

from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext_lazy as _

from horizon import api
from horizon import exceptions
from horizon import tables
from horizon.dashboards.syspanel.instances.tables import SyspanelInstancesTable
from horizon.dashboards.nova.instances_and_volumes .instances.views import (
        console, DetailView, vnc)


LOG = logging.getLogger(__name__)


class AdminIndexView(tables.DataTableView):
    table_class = SyspanelInstancesTable
    template_name = 'syspanel/instances/index.html'

    def get_data(self):
        instances = []
        try:
            instances = api.nova.server_list(self.request, all_tenants=True)
        except:
            exceptions.handle(self.request,
                              _('Unable to retrieve instance list.'))
        if instances:
            # Gather our flavors to correlate against IDs
            try:
                flavors = api.nova.flavor_list(self.request)
            except:
                flavors = []
                msg = _('Unable to retrieve instance size information.')
                exceptions.handle(self.request, msg)
            # Gather our tenants to correlate against IDs
            try:
                tenants = api.keystone.tenant_list(self.request, admin=True)
            except:
                tenants = []
                msg = _('Unable to retrieve instance tenant information.')
                exceptions.handle(self.request, msg)

            full_flavors = SortedDict([(f.id, f) for f in flavors])
            tenant_dict = SortedDict([(t.id, t) for t in tenants])
            for inst in instances:
                inst.full_flavor = full_flavors.get(inst.flavor["id"], None)
                tenant = tenant_dict.get(inst.tenant_id, None)
                inst.tenant_name = getattr(tenant, "name", None)
        return instances
