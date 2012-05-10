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

import logging

from django.utils.translation import ugettext_lazy as _

from ..images.tables import ImagesTable, LaunchImage, EditImage, DeleteImage


LOG = logging.getLogger(__name__)


class DeleteSnapshot(DeleteImage):
    data_type_singular = _("Snapshot")
    data_type_plural = _("Snapshots")


class SnapshotsTable(ImagesTable):
    class Meta:
        name = "snapshots"
        verbose_name = _("Instance Snapshots")
        table_actions = (DeleteSnapshot,)
        row_actions = (LaunchImage, EditImage, DeleteSnapshot)
