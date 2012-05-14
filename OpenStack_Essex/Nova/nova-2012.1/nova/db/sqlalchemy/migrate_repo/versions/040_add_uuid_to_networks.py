# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import Column, Integer, MetaData, String, Table

from nova import utils


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    networks = Table('networks', meta, autoload=True)

    uuid_column = Column("uuid", String(36))
    networks.create_column(uuid_column)

    rows = migrate_engine.execute(networks.select())
    for row in rows:
        networks_uuid = str(utils.gen_uuid())
        migrate_engine.execute(networks.update()\
                .where(networks.c.id == row[0])\
                .values(uuid=networks_uuid))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    networks = Table('networks', meta, autoload=True)

    networks.drop_column('uuid')
