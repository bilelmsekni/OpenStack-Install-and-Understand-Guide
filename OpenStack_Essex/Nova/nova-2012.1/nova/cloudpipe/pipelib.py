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

"""
CloudPipe - Build a user-data payload zip file, and launch
an instance with it.

"""

import os
import string
import tempfile
import zipfile

# NOTE(vish): cloud is only for the _gen_key functionality
from nova.api.ec2 import cloud
from nova import compute
from nova.compute import instance_types
from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import utils


cloudpipe_opts = [
    cfg.StrOpt('vpn_instance_type',
               default='m1.tiny',
               help=_('Instance type for vpn instances')),
    cfg.StrOpt('boot_script_template',
               default='$pybasedir/nova/cloudpipe/bootscript.template',
               help=_('Template for cloudpipe instance boot script')),
    cfg.StrOpt('dmz_net',
               default='10.0.0.0',
               help=_('Network to push into openvpn config')),
    cfg.StrOpt('dmz_mask',
               default='255.255.255.0',
               help=_('Netmask to push into openvpn config')),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(cloudpipe_opts)


LOG = logging.getLogger(__name__)


class CloudPipe(object):
    def __init__(self):
        self.compute_api = compute.API()

    def get_encoded_zip(self, project_id):
        # Make a payload.zip
        with utils.tempdir() as tmpdir:
            filename = "payload.zip"
            zippath = os.path.join(tmpdir, filename)
            z = zipfile.ZipFile(zippath, "w", zipfile.ZIP_DEFLATED)
            shellfile = open(FLAGS.boot_script_template, "r")
            s = string.Template(shellfile.read())
            shellfile.close()
            boot_script = s.substitute(cc_dmz=FLAGS.ec2_dmz_host,
                                       cc_port=FLAGS.ec2_port,
                                       dmz_net=FLAGS.dmz_net,
                                       dmz_mask=FLAGS.dmz_mask,
                                       num_vpn=FLAGS.cnt_vpn_clients)
            # genvpn, sign csr
            crypto.generate_vpn_files(project_id)
            z.writestr('autorun.sh', boot_script)
            crl = os.path.join(crypto.ca_folder(project_id), 'crl.pem')
            z.write(crl, 'crl.pem')
            server_key = os.path.join(crypto.ca_folder(project_id),
                                      'server.key')
            z.write(server_key, 'server.key')
            ca_crt = os.path.join(crypto.ca_path(project_id))
            z.write(ca_crt, 'ca.crt')
            server_crt = os.path.join(crypto.ca_folder(project_id),
                                      'server.crt')
            z.write(server_crt, 'server.crt')
            z.close()
            zippy = open(zippath, "r")
            # NOTE(vish): run instances expects encoded userdata, it is decoded
            # in the get_metadata_call. autorun.sh also decodes the zip file,
            # hence the double encoding.
            encoded = zippy.read().encode("base64").encode("base64")
            zippy.close()

        return encoded

    def launch_vpn_instance(self, context):
        LOG.debug(_("Launching VPN for %s") % (context.project_id))
        key_name = self.setup_key_pair(context)
        group_name = self.setup_security_group(context)
        instance_type = instance_types.get_instance_type_by_name(
                FLAGS.vpn_instance_type)
        instance_name = '%s%s' % (context.project_id, FLAGS.vpn_key_suffix)
        user_data = self.get_encoded_zip(context.project_id)
        return self.compute_api.create(context,
                                       instance_type,
                                       FLAGS.vpn_image_id,
                                       display_name=instance_name,
                                       user_data=user_data,
                                       key_name=key_name,
                                       security_group=[group_name])

    def setup_security_group(self, context):
        group_name = '%s%s' % (context.project_id, FLAGS.vpn_key_suffix)
        if db.security_group_exists(context, context.project_id, group_name):
            return group_name
        group = {'user_id': context.user_id,
                 'project_id': context.project_id,
                 'name': group_name,
                 'description': 'Group for vpn'}
        group_ref = db.security_group_create(context, group)
        rule = {'parent_group_id': group_ref['id'],
                'cidr': '0.0.0.0/0',
                'protocol': 'udp',
                'from_port': 1194,
                'to_port': 1194}
        db.security_group_rule_create(context, rule)
        rule = {'parent_group_id': group_ref['id'],
                'cidr': '0.0.0.0/0',
                'protocol': 'icmp',
                'from_port': -1,
                'to_port': -1}
        db.security_group_rule_create(context, rule)
        # NOTE(vish): No need to trigger the group since the instance
        #             has not been run yet.
        return group_name

    def setup_key_pair(self, context):
        key_name = '%s%s' % (context.project_id, FLAGS.vpn_key_suffix)
        try:
            result = cloud._gen_key(context, context.user_id, key_name)
            private_key = result['private_key']
            key_dir = os.path.join(FLAGS.keys_path, context.user_id)
            if not os.path.exists(key_dir):
                os.makedirs(key_dir)
            key_path = os.path.join(key_dir, '%s.pem' % key_name)
            with open(key_path, 'w') as f:
                f.write(private_key)
        except (exception.Duplicate, os.error, IOError):
            pass
        return key_name
