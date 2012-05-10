# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks

import __builtin__
import unittest
setattr(__builtin__, '_', lambda x: x)

import os
from quantum.common import flags

FLAGS = flags.FLAGS
reldir = os.path.join(os.path.dirname(__file__), '..', '..', '..')
absdir = os.path.abspath(reldir)
FLAGS.state_path = absdir


class BaseTest(unittest.TestCase):

    def setUp(self):
        pass


def setUp():
    pass
