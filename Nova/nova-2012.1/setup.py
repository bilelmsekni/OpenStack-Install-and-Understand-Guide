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

import glob
import os

import setuptools

from nova import version

nova_cmdclass = {}

try:
    from sphinx import setup_command

    class local_BuildDoc(setup_command.BuildDoc):
        def run(self):
            for builder in ['html', 'man']:
                self.builder = builder
                self.finalize_options()
                setup_command.BuildDoc.run(self)
    nova_cmdclass['build_sphinx'] = local_BuildDoc

except Exception:
    pass


def find_data_files(destdir, srcdir):
    package_data = []
    files = []
    for d in glob.glob('%s/*' % (srcdir, )):
        if os.path.isdir(d):
            package_data += find_data_files(
                                 os.path.join(destdir, os.path.basename(d)), d)
        else:
            files += [d]
    package_data += [(destdir, files)]
    return package_data


setuptools.setup(name='nova',
      version=version.canonical_version_string(),
      description='cloud computing fabric controller',
      author='OpenStack',
      author_email='nova@lists.launchpad.net',
      url='http://www.openstack.org/',
      cmdclass=nova_cmdclass,
      packages=setuptools.find_packages(exclude=['bin', 'smoketests']),
      include_package_data=True,
      test_suite='nose.collector',
      scripts=['bin/clear_rabbit_queues',
               'bin/instance-usage-audit',
               'bin/nova-all',
               'bin/nova-api',
               'bin/nova-api-ec2',
               'bin/nova-api-metadata',
               'bin/nova-api-os-compute',
               'bin/nova-api-os-volume',
               'bin/nova-cert',
               'bin/nova-compute',
               'bin/nova-console',
               'bin/nova-consoleauth',
               'bin/nova-dhcpbridge',
               'bin/nova-direct-api',
               'bin/nova-manage',
               'bin/nova-network',
               'bin/nova-objectstore',
               'bin/nova-rootwrap',
               'bin/nova-scheduler',
               'bin/nova-volume',
               'bin/nova-xvpvncproxy',
               'bin/stack',
               'tools/nova-debug'],
        py_modules=[])
