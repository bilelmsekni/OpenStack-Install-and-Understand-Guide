# Copyright 2011 OpenStack, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from setuptools import setup, find_packages

from quantum.openstack.common.setup import parse_requirements
from quantum.openstack.common.setup import parse_dependency_links
from quantum.openstack.common.setup import write_requirements
from quantum.openstack.common.setup import write_git_changelog
from quantum.openstack.common.setup import write_vcsversion

import sys
import os
import subprocess

requires = parse_requirements()
depend_links = parse_dependency_links()
write_requirements()
write_git_changelog()
write_vcsversion('quantum/vcsversion.py')

from quantum import version

Name = 'quantum'
Url = "https://launchpad.net/quantum"
Version = version.canonical_version_string()
License = 'Apache License 2.0'
Author = 'Netstack'
AuthorEmail = 'netstack@lists.launchpad.net'
Maintainer = ''
Summary = 'Quantum (virtual network service)'
ShortDescription = Summary
Description = Summary

EagerResources = [
    'quantum',
]

ProjectScripts = [
]

config_path = 'etc/quantum/'
init_path = 'etc/init.d'
ovs_plugin_config_path = 'etc/quantum/plugins/openvswitch'
cisco_plugin_config_path = 'etc/quantum/plugins/cisco'
linuxbridge_plugin_config_path = 'etc/quantum/plugins/linuxbridge'
nvp_plugin_config_path = 'etc/quantum/plugins/nicira'
ryu_plugin_config_path = 'etc/quantum/plugins/ryu'

DataFiles = [
    (config_path,
        ['etc/quantum.conf', 'etc/quantum.conf.test', 'etc/plugins.ini']),
    (init_path, ['etc/init.d/quantum-server']),
    (ovs_plugin_config_path,
        ['etc/quantum/plugins/openvswitch/ovs_quantum_plugin.ini']),
    (cisco_plugin_config_path,
        ['etc/quantum/plugins/cisco/credentials.ini',
         'etc/quantum/plugins/cisco/l2network_plugin.ini',
         'etc/quantum/plugins/cisco/nexus.ini',
         'etc/quantum/plugins/cisco/ucs.ini',
         'etc/quantum/plugins/cisco/cisco_plugins.ini',
         'etc/quantum/plugins/cisco/db_conn.ini']),
    (linuxbridge_plugin_config_path,
        ['etc/quantum/plugins/linuxbridge/linuxbridge_conf.ini']),
    (nvp_plugin_config_path,
        ['etc/quantum/plugins/nicira/nvp.ini']),
    (ryu_plugin_config_path, ['etc/quantum/plugins/ryu/ryu.ini']),
]

setup(
    name=Name,
    version=Version,
    url=Url,
    author=Author,
    author_email=AuthorEmail,
    description=ShortDescription,
    long_description=Description,
    license=License,
    scripts=ProjectScripts,
    install_requires=requires,
    dependency_links=depend_links,
    include_package_data=False,
    packages=find_packages('.'),
    data_files=DataFiles,
    eager_resources=EagerResources,
    entry_points={
        'console_scripts': [
            'quantum-linuxbridge-agent =' \
            'quantum.plugins.linuxbridge.agent.linuxbridge_quantum_agent:main',
            'quantum-openvswitch-agent =' \
            'quantum.plugins.openvswitch.agent.ovs_quantum_agent:main',
            'quantum-ryu-agent = ' \
            'quantum.plugins.ryu.agent.ryu_quantum_agent:main',
            'quantum-server = quantum.server:main',
        ]
    },
)
