# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011, Cisco Systems, Inc.
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
# @author: Rohit Agarwalla, Cisco Systems, Inc.

from sqlalchemy.orm import exc

from quantum.common import exceptions as q_exc
from quantum.plugins.cisco import l2network_plugin_configuration as conf
from quantum.plugins.cisco.common import cisco_exceptions as c_exc
from quantum.plugins.cisco.db import l2network_models

import logging as LOG
import quantum.plugins.cisco.db.api as db
import quantum.plugins.cisco.db.nexus_db as ndb
import quantum.plugins.cisco.db.ucs_db as udb
import quantum.plugins.cisco.db.services_db as sdb


def initialize():
    'Establish database connection and load models'
    options = {"sql_connection": "mysql://%s:%s@%s/%s" % (conf.DB_USER,
    conf.DB_PASS, conf.DB_HOST, conf.DB_NAME)}
    db.configure_db(options)


def create_vlanids():
    """Prepopulates the vlan_bindings table"""
    LOG.debug("create_vlanids() called")
    session = db.get_session()
    try:
        vlanid = session.query(l2network_models.VlanID).\
          one()
    except exc.MultipleResultsFound:
        pass
    except exc.NoResultFound:
        start = int(conf.VLAN_START)
        end = int(conf.VLAN_END)
        while start <= end:
            vlanid = l2network_models.VlanID(start)
            session.add(vlanid)
            start += 1
        session.flush()
    return


def get_all_vlanids():
    """Gets all the vlanids"""
    LOG.debug("get_all_vlanids() called")
    session = db.get_session()
    try:
        vlanids = session.query(l2network_models.VlanID).\
          all()
        return vlanids
    except exc.NoResultFound:
        return []


def is_vlanid_used(vlan_id):
    """Checks if a vlanid is in use"""
    LOG.debug("is_vlanid_used() called")
    session = db.get_session()
    try:
        vlanid = session.query(l2network_models.VlanID).\
          filter_by(vlan_id=vlan_id).\
          one()
        return vlanid["vlan_used"]
    except exc.NoResultFound:
        raise c_exc.VlanIDNotFound(vlan_id=vlan_id)


def release_vlanid(vlan_id):
    """Sets the vlanid state to be unused"""
    LOG.debug("release_vlanid() called")
    session = db.get_session()
    try:
        vlanid = session.query(l2network_models.VlanID).\
         filter_by(vlan_id=vlan_id).\
          one()
        vlanid["vlan_used"] = False
        session.merge(vlanid)
        session.flush()
        return vlanid["vlan_used"]
    except exc.NoResultFound:
        raise c_exc.VlanIDNotFound(vlan_id=vlan_id)
    return


def delete_vlanid(vlan_id):
    """Deletes a vlanid entry from db"""
    LOG.debug("delete_vlanid() called")
    session = db.get_session()
    try:
        vlanid = session.query(l2network_models.VlanID).\
          filter_by(vlan_id=vlan_id).\
          one()
        session.delete(vlanid)
        session.flush()
        return vlanid
    except exc.NoResultFound:
        pass


def reserve_vlanid():
    """Reserves the first unused vlanid"""
    LOG.debug("reserve_vlanid() called")
    session = db.get_session()
    try:
        rvlan = session.query(l2network_models.VlanID).\
         filter_by(vlan_used=False).\
          first()
        if not rvlan:
            raise exc.NoResultFound
        rvlanid = session.query(l2network_models.VlanID).\
         filter_by(vlan_id=rvlan["vlan_id"]).\
          one()
        rvlanid["vlan_used"] = True
        session.merge(rvlanid)
        session.flush()
        return rvlan["vlan_id"]
    except exc.NoResultFound:
        raise c_exc.VlanIDNotAvailable()


def get_all_vlanids_used():
    """Gets all the vlanids used"""
    LOG.debug("get_all_vlanids() called")
    session = db.get_session()
    try:
        vlanids = session.query(l2network_models.VlanID).\
        filter_by(vlan_used=True).\
          all()
        return vlanids
    except exc.NoResultFound:
        return []


def get_all_vlan_bindings():
    """Lists all the vlan to network associations"""
    LOG.debug("get_all_vlan_bindings() called")
    session = db.get_session()
    try:
        bindings = session.query(l2network_models.VlanBinding).\
          all()
        return bindings
    except exc.NoResultFound:
        return []


def get_vlan_binding(netid):
    """Lists the vlan given a network_id"""
    LOG.debug("get_vlan_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.VlanBinding).\
          filter_by(network_id=netid).\
          one()
        return binding
    except exc.NoResultFound:
        raise q_exc.NetworkNotFound(net_id=netid)


def add_vlan_binding(vlanid, vlanname, netid):
    """Adds a vlan to network association"""
    LOG.debug("add_vlan_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.VlanBinding).\
          filter_by(vlan_id=vlanid).\
          one()
        raise c_exc.NetworkVlanBindingAlreadyExists(vlan_id=vlanid,
                                                    network_id=netid)
    except exc.NoResultFound:
        binding = l2network_models.VlanBinding(vlanid, vlanname, netid)
        session.add(binding)
        session.flush()
        return binding


def remove_vlan_binding(netid):
    """Removes a vlan to network association"""
    LOG.debug("remove_vlan_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.VlanBinding).\
          filter_by(network_id=netid).\
          one()
        session.delete(binding)
        session.flush()
        return binding
    except exc.NoResultFound:
        pass


def update_vlan_binding(netid, newvlanid=None, newvlanname=None):
    """Updates a vlan to network association"""
    LOG.debug("update_vlan_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.VlanBinding).\
          filter_by(network_id=netid).\
          one()
        if newvlanid:
            binding["vlan_id"] = newvlanid
        if newvlanname:
            binding["vlan_name"] = newvlanname
        session.merge(binding)
        session.flush()
        return binding
    except exc.NoResultFound:
        raise q_exc.NetworkNotFound(net_id=netid)


def get_all_portprofiles():
    """Lists all the port profiles"""
    LOG.debug("get_all_portprofiles() called")
    session = db.get_session()
    try:
        pps = session.query(l2network_models.PortProfile).\
          all()
        return pps
    except exc.NoResultFound:
        return []


def get_portprofile(tenantid, ppid):
    """Lists a port profile"""
    LOG.debug("get_portprofile() called")
    session = db.get_session()
    try:
        pp = session.query(l2network_models.PortProfile).\
          filter_by(uuid=ppid).\
          one()
        return pp
    except exc.NoResultFound:
        raise c_exc.PortProfileNotFound(tenant_id=tenantid,
                                portprofile_id=ppid)


def add_portprofile(tenantid, ppname, vlanid, qos):
    """Adds a port profile"""
    LOG.debug("add_portprofile() called")
    session = db.get_session()
    try:
        pp = session.query(l2network_models.PortProfile).\
          filter_by(name=ppname).\
          one()
        raise c_exc.PortProfileAlreadyExists(tenant_id=tenantid,
                                       pp_name=ppname)
    except exc.NoResultFound:
        pp = l2network_models.PortProfile(ppname, vlanid, qos)
        session.add(pp)
        session.flush()
        return pp


def remove_portprofile(tenantid, ppid):
    """Removes a port profile"""
    LOG.debug("remove_portprofile() called")
    session = db.get_session()
    try:
        pp = session.query(l2network_models.PortProfile).\
          filter_by(uuid=ppid).\
          one()
        session.delete(pp)
        session.flush()
        return pp
    except exc.NoResultFound:
        pass


def update_portprofile(tenantid, ppid, newppname=None, newvlanid=None,
                       newqos=None):
    """Updates port profile"""
    LOG.debug("update_portprofile() called")
    session = db.get_session()
    try:
        pp = session.query(l2network_models.PortProfile).\
          filter_by(uuid=ppid).\
          one()
        if newppname:
            pp["name"] = newppname
        if newvlanid:
            pp["vlan_id"] = newvlanid
        if newqos:
            pp["qos"] = newqos
        session.merge(pp)
        session.flush()
        return pp
    except exc.NoResultFound:
        raise c_exc.PortProfileNotFound(tenant_id=tenantid,
                                portprofile_id=ppid)


def get_all_pp_bindings():
    """Lists all the port profiles"""
    LOG.debug("get_all_pp_bindings() called")
    session = db.get_session()
    try:
        bindings = session.query(l2network_models.PortProfileBinding).\
          all()
        return bindings
    except exc.NoResultFound:
        return []


def get_pp_binding(tenantid, ppid):
    """Lists a port profile binding"""
    LOG.debug("get_pp_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.PortProfileBinding).\
          filter_by(portprofile_id=ppid).\
          one()
        return binding
    except exc.NoResultFound:
        return []


def add_pp_binding(tenantid, portid, ppid, default):
    """Adds a port profile binding"""
    LOG.debug("add_pp_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.PortProfileBinding).\
          filter_by(portprofile_id=ppid).\
          one()
        raise c_exc.PortProfileBindingAlreadyExists(pp_id=ppid,
                                                    port_id=portid)
    except exc.NoResultFound:
        binding = l2network_models.PortProfileBinding(tenantid, portid, \
                                                            ppid, default)
        session.add(binding)
        session.flush()
        return binding


def remove_pp_binding(tenantid, portid, ppid):
    """Removes a port profile binding"""
    LOG.debug("remove_pp_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.PortProfileBinding).\
          filter_by(portprofile_id=ppid).\
          filter_by(port_id=portid).\
          one()
        session.delete(binding)
        session.flush()
        return binding
    except exc.NoResultFound:
        pass


def update_pp_binding(tenantid, ppid, newtenantid=None, newportid=None,
                                                    newdefault=None):
    """Updates port profile binding"""
    LOG.debug("update_pp_binding() called")
    session = db.get_session()
    try:
        binding = session.query(l2network_models.PortProfileBinding).\
          filter_by(portprofile_id=ppid).\
          one()
        if newtenantid:
            binding["tenant_id"] = newtenantid
        if newportid:
            binding["port_id"] = newportid
        if newdefault:
            binding["default"] = newdefault
        session.merge(binding)
        session.flush()
        return binding
    except exc.NoResultFound:
        raise c_exc.PortProfileNotFound(tenant_id=tenantid,
                                portprofile_id=ppid)


def get_all_qoss(tenant_id):
    """Lists all the qos to tenant associations"""
    LOG.debug("get_all_qoss() called")
    session = db.get_session()
    try:
        qoss = session.query(l2network_models.QoS).\
          filter_by(tenant_id=tenant_id).\
          all()
        return qoss
    except exc.NoResultFound:
        return []


def get_qos(tenant_id, qos_id):
    """Lists the qos given a tenant_id and qos_id"""
    LOG.debug("get_qos() called")
    session = db.get_session()
    try:
        qos = session.query(l2network_models.QoS).\
          filter_by(tenant_id=tenant_id).\
          filter_by(qos_id=qos_id).\
          one()
        return qos
    except exc.NoResultFound:
        raise c_exc.QosNotFound(qos_id=qos_id,
                                tenant_id=tenant_id)


def add_qos(tenant_id, qos_name, qos_desc):
    """Adds a qos to tenant association"""
    LOG.debug("add_qos() called")
    session = db.get_session()
    try:
        qos = session.query(l2network_models.QoS).\
          filter_by(tenant_id=tenant_id).\
          filter_by(qos_name=qos_name).\
          one()
        raise c_exc.QosNameAlreadyExists(qos_name=qos_name,
                                        tenant_id=tenant_id)
    except exc.NoResultFound:
        qos = l2network_models.QoS(tenant_id, qos_name, qos_desc)
        session.add(qos)
        session.flush()
        return qos


def remove_qos(tenant_id, qos_id):
    """Removes a qos to tenant association"""
    session = db.get_session()
    try:
        qos = session.query(l2network_models.QoS).\
          filter_by(tenant_id=tenant_id).\
          filter_by(qos_id=qos_id).\
          one()
        session.delete(qos)
        session.flush()
        return qos
    except exc.NoResultFound:
        pass


def update_qos(tenant_id, qos_id, new_qos_name=None):
    """Updates a qos to tenant association"""
    session = db.get_session()
    try:
        qos = session.query(l2network_models.QoS).\
          filter_by(tenant_id=tenant_id).\
          filter_by(qos_id=qos_id).\
          one()
        if new_qos_name:
            qos["qos_name"] = new_qos_name
        session.merge(qos)
        session.flush()
        return qos
    except exc.NoResultFound:
        raise c_exc.QosNotFound(qos_id=qos_id,
                                tenant_id=tenant_id)


def get_all_credentials(tenant_id):
    """Lists all the creds for a tenant"""
    session = db.get_session()
    try:
        creds = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          all()
        return creds
    except exc.NoResultFound:
        return []


def get_credential(tenant_id, credential_id):
    """Lists the creds for given a cred_id and tenant_id"""
    session = db.get_session()
    try:
        cred = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          filter_by(credential_id=credential_id).\
          one()
        return cred
    except exc.NoResultFound:
        raise c_exc.CredentialNotFound(credential_id=credential_id,
                                         tenant_id=tenant_id)


def get_credential_name(tenant_id, credential_name):
    """Lists the creds for given a cred_name and tenant_id"""
    session = db.get_session()
    try:
        cred = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          filter_by(credential_name=credential_name).\
          one()
        return cred
    except exc.NoResultFound:
        raise c_exc.CredentialNameNotFound(credential_name=credential_name,
                                         tenant_id=tenant_id)


def add_credential(tenant_id, credential_name, user_name, password):
    """Adds a qos to tenant association"""
    session = db.get_session()
    try:
        cred = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          filter_by(credential_name=credential_name).\
          one()
        raise c_exc.CredentialAlreadyExists(credential_name=credential_name,
                                            tenant_id=tenant_id)
    except exc.NoResultFound:
        cred = l2network_models.Credential(tenant_id,
                                        credential_name, user_name, password)
        session.add(cred)
        session.flush()
        return cred


def remove_credential(tenant_id, credential_id):
    """Removes a credential from a  tenant"""
    session = db.get_session()
    try:
        cred = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          filter_by(credential_id=credential_id).\
          one()
        session.delete(cred)
        session.flush()
        return cred
    except exc.NoResultFound:
        pass


def update_credential(tenant_id, credential_id,
                      new_user_name=None, new_password=None):
    """Updates a credential for a tenant"""
    session = db.get_session()
    try:
        cred = session.query(l2network_models.Credential).\
          filter_by(tenant_id=tenant_id).\
          filter_by(credential_id=credential_id).\
          one()
        if new_user_name:
            cred["user_name"] = new_user_name
        if new_password:
            cred["password"] = new_password
        session.merge(cred)
        session.flush()
        return cred
    except exc.NoResultFound:
        raise c_exc.CredentialNotFound(credential_id=credential_id,
                                         tenant_id=tenant_id)
