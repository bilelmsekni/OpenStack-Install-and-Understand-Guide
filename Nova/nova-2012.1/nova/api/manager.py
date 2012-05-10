# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from nova import flags
from nova import manager
from nova import utils

FLAGS = flags.FLAGS


class MetadataManager(manager.Manager):
    """Metadata Manager.

    This class manages the Metadata API service initialization. Currently, it
    just adds an iptables filter rule for the metadata service.
    """
    def __init__(self, *args, **kwargs):
        super(MetadataManager, self).__init__(*args, **kwargs)
        self.network_driver = utils.import_object(FLAGS.network_driver)

    def init_host(self):
        """Perform any initialization.

        Currently, we only add an iptables filter rule for the metadata
        service.
        """
        self.network_driver.metadata_accept()
