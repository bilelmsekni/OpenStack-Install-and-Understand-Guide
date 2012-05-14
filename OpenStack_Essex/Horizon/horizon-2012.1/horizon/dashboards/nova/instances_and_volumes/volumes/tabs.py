# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from horizon import api
from horizon import exceptions
from horizon import tabs


class OverviewTab(tabs.Tab):
    name = _("Overview")
    slug = "overview"
    template_name = ("nova/instances_and_volumes/volumes/"
                     "_detail_overview.html")

    def get_context_data(self, request):
        volume_id = self.tab_group.kwargs['volume_id']
        try:
            volume = api.nova.volume_get(request, volume_id)
            for att in volume.attachments:
                att['instance'] = api.nova.server_get(request,
                                                      att['server_id'])
        except:
            redirect = reverse('horizon:nova:instances_and_volumes:index')
            exceptions.handle(self.request,
                              _('Unable to retrieve volume details.'),
                              redirect=redirect)
        return {'volume': volume}


class VolumeDetailTabs(tabs.TabGroup):
    slug = "volume_details"
    tabs = (OverviewTab,)
