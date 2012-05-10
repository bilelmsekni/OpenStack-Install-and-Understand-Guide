# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy.schema import (Column, MetaData, Table)

from glance.registry.db.migrate_repo.schema import (
    Boolean, DateTime, Integer, String, Text, create_tables, drop_tables)


def define_images_table(meta):
    images = Table('images', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('name', String(255)),
        Column('type', String(30)),
        Column('size', Integer()),
        Column('status', String(30), nullable=False),
        Column('is_public', Boolean(), nullable=False, default=False,
               index=True),
        Column('location', Text()),
        Column('created_at', DateTime(), nullable=False),
        Column('updated_at', DateTime()),
        Column('deleted_at', DateTime()),
        Column('deleted', Boolean(), nullable=False, default=False,
               index=True),
        mysql_engine='InnoDB',
        extend_existing=True)

    return images


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = [define_images_table(meta)]
    create_tables(tables)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = [define_images_table(meta)]
    drop_tables(tables)
