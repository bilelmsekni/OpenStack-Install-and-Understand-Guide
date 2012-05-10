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

import os.path

from nova.api.openstack import common
from nova import flags
from nova import utils


FLAGS = flags.FLAGS


class ViewBuilder(common.ViewBuilder):

    _collection_name = "images"

    def basic(self, request, image):
        """Return a dictionary with basic image attributes."""
        return {
            "image": {
                "id": image.get("id"),
                "name": image.get("name"),
                "links": self._get_links(request, image["id"]),
            },
        }

    def show(self, request, image):
        """Return a dictionary with image details."""
        image_dict = {
            "id": image.get("id"),
            "name": image.get("name"),
            "minRam": int(image.get("min_ram") or 0),
            "minDisk": int(image.get("min_disk") or 0),
            "metadata": image.get("properties", {}),
            "created": self._format_date(image.get("created_at")),
            "updated": self._format_date(image.get("updated_at")),
            "status": self._get_status(image),
            "progress": self._get_progress(image),
            "links": self._get_links(request, image["id"]),
        }

        instance_uuid = image.get("properties", {}).get("instance_uuid")

        if instance_uuid is not None:
            server_ref = os.path.join(request.application_url, 'servers',
                                      instance_uuid)
            server_ref = self._update_link_prefix(server_ref,
                    FLAGS.osapi_compute_link_prefix)
            image_dict["server"] = {
                "id": instance_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_ref,
                },
                {
                    "rel": "bookmark",
                    "href": common.remove_version_from_href(server_ref),
                }],
            }

        return dict(image=image_dict)

    def detail(self, request, images):
        """Show a list of images with details."""
        list_func = self.show
        return self._list_view(list_func, request, images)

    def index(self, request, images):
        """Show a list of images with basic attributes."""
        list_func = self.basic
        return self._list_view(list_func, request, images)

    def _list_view(self, list_func, request, images):
        """Provide a view for a list of images."""
        image_list = [list_func(request, image)["image"] for image in images]
        images_links = self._get_collection_links(request, images)
        images_dict = dict(images=image_list)

        if images_links:
            images_dict["images_links"] = images_links

        return images_dict

    def _get_links(self, request, identifier):
        """Return a list of links for this image."""
        return [{
            "rel": "self",
            "href": self._get_href_link(request, identifier),
        },
        {
            "rel": "bookmark",
            "href": self._get_bookmark_link(request, identifier),
        },
        {
            "rel": "alternate",
            "type": "application/vnd.openstack.image",
            "href": self._get_alternate_link(request, identifier),
        }]

    def _get_alternate_link(self, request, identifier):
        """Create an alternate link for a specific flavor id."""
        glance_url = utils.generate_glance_url()
        glance_url = self._update_link_prefix(glance_url,
                                              FLAGS.osapi_glance_link_prefix)
        return os.path.join(glance_url,
                            request.environ["nova.context"].project_id,
                            self._collection_name,
                            str(identifier))

    @staticmethod
    def _format_date(date_string):
        """Return standard format for given date."""
        if date_string is not None:
            return date_string.strftime('%Y-%m-%dT%H:%M:%SZ')

    @staticmethod
    def _get_status(image):
        """Update the status field to standardize format."""
        return {
            'active': 'ACTIVE',
            'queued': 'SAVING',
            'saving': 'SAVING',
            'deleted': 'DELETED',
            'pending_delete': 'DELETED',
            'killed': 'ERROR',
        }.get(image.get("status"), 'UNKNOWN')

    @staticmethod
    def _get_progress(image):
        return {
            "queued": 25,
            "saving": 50,
            "active": 100,
        }.get(image.get("status"), 0)
