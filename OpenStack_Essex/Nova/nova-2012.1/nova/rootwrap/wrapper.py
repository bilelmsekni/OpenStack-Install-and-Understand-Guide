# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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


import os
import sys


FILTERS_MODULES = ['nova.rootwrap.compute',
                   'nova.rootwrap.network',
                   'nova.rootwrap.volume',
                  ]


def load_filters():
    """Load filters from modules present in nova.rootwrap."""
    filters = []
    for modulename in FILTERS_MODULES:
        try:
            __import__(modulename)
            module = sys.modules[modulename]
            filters = filters + module.filterlist
        except ImportError:
            # It's OK to have missing filters, since filter modules are
            # shipped with specific nodes rather than with python-nova
            pass
    return filters


def match_filter(filters, userargs):
    """
    Checks user command and arguments through command filters and
    returns the first matching filter, or None is none matched.
    """

    found_filter = None

    for f in filters:
        if f.match(userargs):
            # Try other filters if executable is absent
            if not os.access(f.exec_path, os.X_OK):
                if not found_filter:
                    found_filter = f
                continue
            # Otherwise return matching filter for execution
            return f

    # No filter matched or first missing executable
    return found_filter
