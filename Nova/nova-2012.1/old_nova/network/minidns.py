# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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
import shutil
import tempfile

from nova import exception
from nova import flags


class MiniDNS(object):
    """ Trivial DNS driver. This will read/write to a local, flat file
        and have no effect on your actual DNS system. This class is
        strictly for testing purposes, and should keep you out of dependency
        hell.

        Note that there is almost certainly a race condition here that
        will manifest anytime instances are rapidly created and deleted.
        A proper implementation will need some manner of locking."""

    def __init__(self):
        if flags.FLAGS.logdir:
            self.filename = os.path.join(flags.FLAGS.logdir, "dnstest.txt")
        else:
            self.filename = "dnstest.txt"

        if not os.path.exists(self.filename):
            f = open(self.filename, "w+")
            f.write("#  minidns\n\n\n")
            f.close()

    def get_domains(self):
        entries = []
        infile = open(self.filename, 'r')
        for line in infile:
            entry = self.parse_line(line)
            if entry and entry['address'].lower() == 'domain'.lower():
                entries.append(entry['name'])
        infile.close()
        return entries

    def qualify(self, name, domain):
        if domain:
            qualified = "%s.%s" % (name, domain)
        else:
            qualified = name

        return qualified

    def create_entry(self, name, address, type, domain):

        if type.lower() != 'a':
            raise exception.InvalidInput(_("This driver only supports "
                                           "type 'a'"))

        if self.get_entries_by_name(name, domain):
            raise exception.FloatingIpDNSExists(name=name, domain=domain)

        outfile = open(self.filename, 'a+')
        outfile.write("%s   %s   %s\n" %
            (address, self.qualify(name, domain), type))
        outfile.close()

    def parse_line(self, line):
        vals = line.split()
        if len(vals) < 3:
            return None
        else:
            entry = {}
            entry['address'] = vals[0]
            entry['name'] = vals[1]
            entry['type'] = vals[2]
            if entry['address'] == 'domain':
                entry['domain'] = entry['name']
            else:
                entry['domain'] = entry['name'].partition('.')[2]
            return entry

    def delete_entry(self, name, domain):
        deleted = False
        infile = open(self.filename, 'r')
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        for line in infile:
            entry = self.parse_line(line)
            if ((not entry) or
                entry['name'] != self.qualify(name, domain).lower()):
                outfile.write(line)
            else:
                deleted = True
        infile.close()
        outfile.close()
        shutil.move(outfile.name, self.filename)
        if not deleted:
            raise exception.NotFound

    def modify_address(self, name, address, domain):

        if not self.get_entries_by_name(name, domain):
            raise exception.NotFound

        infile = open(self.filename, 'r')
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        for line in infile:
            entry = self.parse_line(line)
            if (entry and
                entry['name'].lower() == self.qualify(name, domain).lower()):
                outfile.write("%s   %s   %s\n" %
                    (address, self.qualify(name, domain), entry['type']))
            else:
                outfile.write(line)
        infile.close()
        outfile.close()
        shutil.move(outfile.name, self.filename)

    def get_entries_by_address(self, address, domain):
        entries = []
        infile = open(self.filename, 'r')
        for line in infile:
            entry = self.parse_line(line)
            if entry and entry['address'].lower() == address.lower():
                if entry['name'].lower().endswith(domain.lower()):
                    domain_index = entry['name'].lower().find(domain.lower())
                    entries.append(entry['name'][0:domain_index - 1])
        infile.close()
        return entries

    def get_entries_by_name(self, name, domain):
        entries = []
        infile = open(self.filename, 'r')
        for line in infile:
            entry = self.parse_line(line)
            if (entry and
                entry['name'].lower() == self.qualify(name, domain).lower()):
                entries.append(entry['address'])
        infile.close()
        return entries

    def delete_dns_file(self):
        os.remove(self.filename)

    def create_domain(self, fqdomain):
        if self.get_entries_by_name(fqdomain, ''):
            raise exception.FloatingIpDNSExists(name=fqdomain, domain='')

        outfile = open(self.filename, 'a+')
        outfile.write("%s   %s   %s\n" %
            ('domain', fqdomain, 'domain'))
        outfile.close()

    def delete_domain(self, fqdomain):
        deleted = False
        infile = open(self.filename, 'r')
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        for line in infile:
            entry = self.parse_line(line)
            if ((not entry) or
                entry['domain'] != fqdomain):
                outfile.write(line)
            else:
                print "deleted %s" % entry
                deleted = True
        infile.close()
        outfile.close()
        shutil.move(outfile.name, self.filename)
        if not deleted:
            raise exception.NotFound
