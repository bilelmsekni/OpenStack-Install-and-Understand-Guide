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

"""Rules-based Policy Engine."""

from keystone import config
from keystone import exception
from keystone import policy
from keystone.common import logging
from keystone.common import policy as common_policy
from keystone.common import utils
from keystone.openstack.common import cfg


policy_opts = [
    cfg.StrOpt('policy_file',
               default='policy.json',
               help=_('JSON file representing policy')),
    cfg.StrOpt('policy_default_rule',
               default='default',
               help=_('Rule checked when requested rule is not found')),
    ]


CONF = config.CONF
CONF.register_opts(policy_opts)


LOG = logging.getLogger(__name__)


_POLICY_PATH = None
_POLICY_CACHE = {}


def reset():
    global _POLICY_PATH
    global _POLICY_CACHE
    _POLICY_PATH = None
    _POLICY_CACHE = {}
    common_policy.reset()


def init():
    global _POLICY_PATH
    global _POLICY_CACHE
    if not _POLICY_PATH:
        _POLICY_PATH = utils.find_config(CONF.policy_file)
    utils.read_cached_file(_POLICY_PATH,
                           _POLICY_CACHE,
                           reload_func=_set_brain)


def _set_brain(data):
    default_rule = CONF.policy_default_rule
    common_policy.set_brain(
            common_policy.HttpBrain.load_json(data, default_rule))


def enforce(credentials, action, target):
    """Verifies that the action is valid on the target in this context.

       :param credentials: user credentials
       :param action: string representing the action to be checked

           this should be colon separated for clarity.
           i.e. compute:create_instance
                compute:attach_volume
                volume:attach_volume

       :param object: dictionary representing the object of the action
                      for object creation this should be a dictionary
                      representing the location of the object e.g.
                      {'tenant_id': object.tenant_id}

       :raises: `exception.Forbidden` if verification fails.

    """
    init()

    match_list = ('rule:%s' % action,)

    try:
        common_policy.enforce(match_list, target, credentials)
    except common_policy.NotAuthorized:
        raise exception.ForbiddenAction(action=action)


class Policy(policy.Driver):
    def enforce(self, credentials, action, target):
        LOG.debug('enforce %s: %s', action, credentials)
        enforce(credentials, action, target)
