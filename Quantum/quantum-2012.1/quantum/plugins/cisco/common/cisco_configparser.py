"""
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Cisco Systems, Inc.  All rights reserved.
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
#
# @author: Sumit Naiksatam, Cisco Systems, Inc.
#
"""

from configobj import ConfigObj
from quantum.plugins.cisco.common import cisco_constants as const


class CiscoConfigParser(ConfigObj):
    """Config Parser based on the ConfigObj module"""

    def __init__(self, filename):
        super(CiscoConfigParser, self).__init__(filename, raise_errors=True,
                                                file_error=True)

    def dummy(self, section, key):
        """Dummy function to return the same key, used in walk"""
        return section[key]
