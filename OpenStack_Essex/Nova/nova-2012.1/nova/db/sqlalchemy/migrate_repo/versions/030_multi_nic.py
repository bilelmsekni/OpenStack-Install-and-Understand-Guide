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

from sqlalchemy import select, Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String
from sqlalchemy import Table

from nova import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # grab tables and (column for dropping later)
    instances = Table('instances', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    c = instances.columns['mac_address']

    interface = Column('bridge_interface',
                       String(length=255, convert_unicode=False,
                              assert_unicode=None, unicode_error=None,
                              _warn_on_bytestring=False))

    virtual_interface_id = Column('virtual_interface_id',
                           Integer())
    # add interface column to networks table
    # values will have to be set manually before running nova
    try:
        networks.create_column(interface)
    except Exception:
        LOG.error(_("interface column not added to networks table"))
        raise

    #
    # New Tables
    #
    virtual_interfaces = Table('virtual_interfaces', meta,
            Column('created_at', DateTime(timezone=False),
                   default=utils.utcnow()),
            Column('updated_at', DateTime(timezone=False),
                   onupdate=utils.utcnow()),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('address',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False),
                   unique=True),
            Column('network_id',
                   Integer(),
                   ForeignKey('networks.id')),
            Column('instance_id',
                   Integer(),
                   ForeignKey('instances.id'),
                   nullable=False),
            mysql_engine='InnoDB')

    # create virtual_interfaces table
    try:
        virtual_interfaces.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(virtual_interfaces))
        raise

    # add virtual_interface_id column to fixed_ips table
    try:
        fixed_ips.create_column(virtual_interface_id)
    except Exception:
        LOG.error(_("VIF column not added to fixed_ips table"))
        raise

    # populate the virtual_interfaces table
    # extract data from existing instance and fixed_ip tables
    s = select([instances.c.id, instances.c.mac_address,
                fixed_ips.c.network_id],
               fixed_ips.c.instance_id == instances.c.id)
    keys = ('instance_id', 'address', 'network_id')
    join_list = [dict(zip(keys, row)) for row in s.execute()]
    LOG.debug(_("join list for moving mac_addresses |%s|"), join_list)

    # insert data into the table
    if join_list:
        i = virtual_interfaces.insert()
        i.execute(join_list)

    # populate the fixed_ips virtual_interface_id column
    s = select([fixed_ips.c.id, fixed_ips.c.instance_id],
               fixed_ips.c.instance_id != None)

    for row in s.execute():
        m = select([virtual_interfaces.c.id]).\
            where(virtual_interfaces.c.instance_id == row['instance_id']).\
            as_scalar()
        u = fixed_ips.update().values(virtual_interface_id=m).\
            where(fixed_ips.c.id == row['id'])
        u.execute()

    # drop the mac_address column from instances
    c.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # grab tables and (column for dropping later)
    instances = Table('instances', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    virtual_interfaces = Table('virtual_interfaces', meta, autoload=True)

    mac_address = Column('mac_address',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False))

    instances.create_column(mac_address)

    s = select([instances.c.id, virtual_interfaces.c.address],
               virtual_interfaces.c.instance_id == instances.c.id)

    for row in s.execute():
        u = instances.update().values(mac_address=row['address']).\
                where(instances.c.id == row['id'])

    networks.drop_column('bridge_interface')
    virtual_interfaces.drop()
    fixed_ips.drop_column('virtual_interface_id')
