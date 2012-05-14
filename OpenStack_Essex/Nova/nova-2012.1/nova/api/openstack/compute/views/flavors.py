# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

from nova.api.openstack import common


class ViewBuilder(common.ViewBuilder):

    _collection_name = "flavors"

    def basic(self, request, flavor):
        return {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "links": self._get_links(request, flavor["flavorid"]),
            },
        }

    def show(self, request, flavor):
        return {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "ram": flavor["memory_mb"],
                "disk": flavor["root_gb"],
                "vcpus": flavor.get("vcpus") or "",
                "swap": flavor.get("swap") or "",
                "rxtx_factor": flavor.get("rxtx_factor") or "",
                "links": self._get_links(request, flavor["flavorid"]),
            },
        }

    def index(self, request, flavors):
        """Return the 'index' view of flavors."""
        return self._list_view(self.basic, request, flavors)

    def detail(self, request, flavors):
        """Return the 'detail' view of flavors."""
        return self._list_view(self.show, request, flavors)

    def _list_view(self, func, request, flavors):
        """Provide a view for a list of flavors."""
        flavor_list = [func(request, flavor)["flavor"] for flavor in flavors]
        flavors_links = self._get_collection_links(request,
                                                   flavors,
                                                   "flavorid")
        flavors_dict = dict(flavors=flavor_list)

        if flavors_links:
            flavors_dict["flavors_links"] = flavors_links

        return flavors_dict
