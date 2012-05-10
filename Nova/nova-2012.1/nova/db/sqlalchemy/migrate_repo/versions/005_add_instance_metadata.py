# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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

    quotas = Table('quotas', meta, autoload=True)

    instance_metadata_table = Table('instance_metadata', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('instance_id',
                   Integer(),
                   ForeignKey('instances.id'),
                   nullable=False),
            Column('key',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('value',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)))

    for table in (instance_metadata_table, ):
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table')
            raise

    quota_metadata_items = Column('metadata_items', Integer())
    quotas.create_column(quota_metadata_items)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    quotas = Table('quotas', meta, autoload=True)

    instance_metadata_table = Table('instance_metadata', meta, autoload=True)

    for table in (instance_metadata_table, ):
            table.drop()

    quotas.drop_column('metadata_items')
