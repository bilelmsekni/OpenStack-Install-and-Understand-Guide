# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2011 OpenStack LLC
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
#

import nova.context
import nova.db
import nova.flags

FLAGS = nova.flags.FLAGS


def get_test_admin_context():
    return nova.context.get_admin_context()


def get_test_image_info(context, instance_ref):
    if not context:
        context = get_test_admin_context()

    image_ref = instance_ref['image_ref']
    image_service, image_id = nova.image.get_image_service(context, image_ref)
    return image_service.show(context, image_id)


def get_test_instance_type(context=None):
    if not context:
        context = get_test_admin_context()

    test_instance_type = {'name': 'kinda.big',
                          'flavorid': 'someid',
                          'memory_mb': 2048,
                          'vcpus': 4,
                          'root_gb': 40,
                          'ephemeral_gb': 80,
                          'swap': 1024}

    instance_type_ref = nova.db.instance_type_create(context,
            test_instance_type)
    return instance_type_ref


def get_test_instance(context=None):
    if not context:
        context = get_test_admin_context()

    test_instance = {'memory_kb': '1024000',
                     'basepath': '/some/path',
                     'bridge_name': 'br100',
                     'vcpus': 2,
                     'root_gb': 10,
                     'project_id': 'fake',
                     'bridge': 'br101',
                     'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                     'instance_type_id': '5'}  # m1.small

    instance_ref = nova.db.instance_create(context, test_instance)
    return instance_ref


def get_test_network_info(count=1):
    ipv6 = FLAGS.use_ipv6
    fake = 'fake'
    fake_ip = '0.0.0.0/0'
    fake_ip_2 = '0.0.0.1/0'
    fake_ip_3 = '0.0.0.1/0'
    fake_vlan = 100
    fake_bridge_interface = 'eth0'
    network = {'bridge': fake,
               'cidr': fake_ip,
               'cidr_v6': fake_ip,
               'vlan': fake_vlan,
               'bridge_interface': fake_bridge_interface,
               'injected': False}
    mapping = {'mac': fake,
               'dhcp_server': fake,
               'gateway': fake,
               'gateway_v6': fake,
               'ips': [{'ip': fake_ip}, {'ip': fake_ip}]}
    if ipv6:
        mapping['ip6s'] = [{'ip': fake_ip},
                           {'ip': fake_ip_2},
                           {'ip': fake_ip_3}]
    return [(network, mapping) for x in xrange(0, count)]
