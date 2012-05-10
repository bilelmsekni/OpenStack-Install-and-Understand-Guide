# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table
from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    #
    # New Tables
    #
    migrations = Table('migrations', meta,
                Column('created_at', DateTime(timezone=False)),
                Column('updated_at', DateTime(timezone=False)),
                Column('deleted_at', DateTime(timezone=False)),
                Column('deleted', Boolean(create_constraint=True, name=None)),
                Column('id', Integer(), primary_key=True, nullable=False),
                Column('source_compute', String(255)),
                Column('dest_compute', String(255)),
                Column('dest_host', String(255)),
                Column('instance_id', Integer, ForeignKey('instances.id'),
                    nullable=True),
                Column('status', String(255)),
          )

    for table in (migrations, ):
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table')
            raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    migrations = Table('migrations', meta, autoload=True)

    for table in (migrations, ):
            table.drop()
