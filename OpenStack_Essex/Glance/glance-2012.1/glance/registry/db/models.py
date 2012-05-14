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

"""
SQLAlchemy models for glance data
"""

import datetime

from sqlalchemy.orm import relationship, backref, object_mapper
from sqlalchemy import Column, Integer, String, BigInteger
from sqlalchemy import ForeignKey, DateTime, Boolean, Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.declarative import declarative_base

import glance.registry.db.api
from glance.common import utils

BASE = declarative_base()


@compiles(BigInteger, 'sqlite')
def compile_big_int_sqlite(type_, compiler, **kw):
    return 'INTEGER'


class ModelBase(object):
    """Base class for Nova and Glance Models"""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    __protected_attributes__ = set([
        "created_at", "updated_at", "deleted_at", "deleted"])

    created_at = Column(DateTime, default=datetime.datetime.utcnow,
                        nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        nullable=False, onupdate=datetime.datetime.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, nullable=False, default=False)

    def save(self, session=None):
        """Save this object"""
        session = session or glance.registry.db.api.get_session()
        session.add(self)
        session.flush()

    def delete(self, session=None):
        """Delete this object"""
        self.deleted = True
        self.deleted_at = datetime.datetime.utcnow()
        self.save(session=session)

    def update(self, values):
        """dict.update() behaviour."""
        for k, v in values.iteritems():
            self[k] = v

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def to_dict(self):
        return self.__dict__.copy()


class Image(BASE, ModelBase):
    """Represents an image in the datastore"""
    __tablename__ = 'images'

    id = Column(String(36), primary_key=True, default=utils.generate_uuid)
    name = Column(String(255))
    disk_format = Column(String(20))
    container_format = Column(String(20))
    size = Column(BigInteger)
    status = Column(String(30), nullable=False)
    is_public = Column(Boolean, nullable=False, default=False)
    location = Column(Text)
    checksum = Column(String(32))
    min_disk = Column(Integer(), nullable=False, default=0)
    min_ram = Column(Integer(), nullable=False, default=0)
    owner = Column(String(255))
    protected = Column(Boolean, nullable=False, default=False)


class ImageProperty(BASE, ModelBase):
    """Represents an image properties in the datastore"""
    __tablename__ = 'image_properties'
    __table_args__ = (UniqueConstraint('image_id', 'name'), {})

    id = Column(Integer, primary_key=True)
    image_id = Column(String(36), ForeignKey('images.id'),
                      nullable=False)
    image = relationship(Image, backref=backref('properties'))

    name = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class ImageMember(BASE, ModelBase):
    """Represents an image members in the datastore"""
    __tablename__ = 'image_members'
    __table_args__ = (UniqueConstraint('image_id', 'member'), {})

    id = Column(Integer, primary_key=True)
    image_id = Column(String(36), ForeignKey('images.id'),
                      nullable=False)
    image = relationship(Image, backref=backref('members'))

    member = Column(String(255), nullable=False)
    can_share = Column(Boolean, nullable=False, default=False)


def register_models(engine):
    """
    Creates database tables for all models with the given engine
    """
    models = (Image, ImageProperty, ImageMember)
    for model in models:
        model.metadata.create_all(engine)


def unregister_models(engine):
    """
    Drops database tables for all models with the given engine
    """
    models = (Image, ImageProperty)
    for model in models:
        model.metadata.drop_all(engine)
