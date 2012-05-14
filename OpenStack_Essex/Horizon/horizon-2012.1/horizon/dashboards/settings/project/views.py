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

from django import shortcuts
from .forms import DownloadOpenRCForm


def index(request):
    form, handled = DownloadOpenRCForm.maybe_handle(request,
                        initial={'tenant': request.user.tenant_id})
    if handled:
        return handled

    context = {'form': form}

    return shortcuts.render(request, 'settings/project/settings.html', context)
