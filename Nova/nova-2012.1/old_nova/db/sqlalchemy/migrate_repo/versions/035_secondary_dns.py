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

from sqlalchemy import Column, Table, MetaData, String


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    networks = Table('networks', meta, autoload=True)

    networks.c.dns.alter(name='dns1')
    dns2 = Column('dns2', String(255))
    networks.create_column(dns2)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    networks = Table('networks', meta, autoload=True)

    networks.c.dns1.alter(name='dns')
    networks.drop_column('dns2')
