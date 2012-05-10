# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import MetaData, Table
from migrate import ForeignKeyConstraint

from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name
    if dialect.startswith('sqlite'):
        return

    instances = Table('instances', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    vifs = Table('virtual_interfaces', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    floating_ips = Table('floating_ips', meta, autoload=True)

    try:
        fkeys = list(fixed_ips.c.network_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[fixed_ips.c.network_id],
                                 refcolumns=[networks.c.id],
                                 name=fkey_name).drop()

        fkeys = list(fixed_ips.c.virtual_interface_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[fixed_ips.c.virtual_interface_id],
                                 refcolumns=[vifs.c.id],
                                 name=fkey_name).drop()

        fkeys = list(fixed_ips.c.instance_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[fixed_ips.c.instance_id],
                                 refcolumns=[instances.c.id],
                                 name=fkey_name).drop()

        fkeys = list(floating_ips.c.fixed_ip_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[floating_ips.c.fixed_ip_id],
                                 refcolumns=[fixed_ips.c.id],
                                 name=fkey_name).drop()

    except Exception:
        LOG.error(_("foreign key constraint couldn't be removed"))
        raise


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name
    if dialect.startswith('sqlite'):
        return

    instances = Table('instances', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    vifs = Table('virtual_interfaces', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    floating_ips = Table('floating_ips', meta, autoload=True)

    try:
        ForeignKeyConstraint(columns=[fixed_ips.c.network_id],
                             refcolumns=[networks.c.id]).create()

        ForeignKeyConstraint(columns=[fixed_ips.c.virtual_interface_id],
                             refcolumns=[vifs.c.id]).create()

        ForeignKeyConstraint(columns=[fixed_ips.c.instance_id],
                             refcolumns=[instances.c.id]).create()

        ForeignKeyConstraint(columns=[floating_ips.c.fixed_ip_id],
                             refcolumns=[fixed_ips.c.id]).create()
    except Exception:
        LOG.error(_("foreign key constraint couldn't be added"))
        raise
