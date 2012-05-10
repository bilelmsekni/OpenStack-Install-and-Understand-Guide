# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

"""Implementation of SQLAlchemy backend."""

import datetime
import functools
import re
import warnings

from nova import block_device
from nova import db
from nova import exception
from nova import flags
from nova import utils
from nova import log as logging
from nova.compute import aggregate_states
from nova.compute import vm_states
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy.session import get_session
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import joinedload_all
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import asc
from sqlalchemy.sql.expression import desc
from sqlalchemy.sql.expression import literal_column

FLAGS = flags.FLAGS
flags.DECLARE('reserved_host_disk_mb', 'nova.scheduler.host_manager')
flags.DECLARE('reserved_host_memory_mb', 'nova.scheduler.host_manager')

LOG = logging.getLogger(__name__)


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        warnings.warn(_('Use of empty request context is deprecated'),
                      DeprecationWarning)
        raise Exception('die')
    return context.is_admin


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if is_user_context(context):
        if not context.project_id:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if is_user_context(context):
        if not context.user_id:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]):
            raise exception.AdminRequired()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]) and not is_user_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def require_instance_exists(f):
    """Decorator to require the specified instance to exist.

    Requires the wrapped function to use context and instance_id as
    their first two arguments.
    """

    def wrapper(context, instance_id, *args, **kwargs):
        db.instance_get(context, instance_id)
        return f(context, instance_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_volume_exists(f):
    """Decorator to require the specified volume to exist.

    Requires the wrapped function to use context and volume_id as
    their first two arguments.
    """

    def wrapper(context, volume_id, *args, **kwargs):
        db.volume_get(context, volume_id)
        return f(context, volume_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_aggregate_exists(f):
    """Decorator to require the specified aggregate to exist.

    Requires the wrapped function to use context and aggregate_id as
    their first two arguments.
    """

    @functools.wraps(f)
    def wrapper(context, aggregate_id, *args, **kwargs):
        db.aggregate_get(context, aggregate_id)
        return f(context, aggregate_id, *args, **kwargs)
    return wrapper


def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(
                _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query


def exact_filter(query, model, filters, legal_keys):
    """Applies exact match filtering to a query.

    Returns the updated query.  Modifies filters argument to remove
    filters consumed.

    :param query: query to apply filters to
    :param model: model object the query applies to, for IN-style
                  filtering
    :param filters: dictionary of filters; values that are lists,
                    tuples, sets, or frozensets cause an 'IN' test to
                    be performed, while exact matching ('==' operator)
                    is used for other values
    :param legal_keys: list of keys to apply exact filtering to
    """

    filter_dict = {}

    # Walk through all the keys
    for key in legal_keys:
        # Skip ones we're not filtering on
        if key not in filters:
            continue

        # OK, filtering on this key; what value do we search for?
        value = filters.pop(key)

        if isinstance(value, (list, tuple, set, frozenset)):
            # Looking for values in a list; apply to query directly
            column_attr = getattr(model, key)
            query = query.filter(column_attr.in_(value))
        else:
            # OK, simple exact match; save for later
            filter_dict[key] = value

    # Apply simple exact matches
    if filter_dict:
        query = query.filter_by(**filter_dict)

    return query


###################


@require_admin_context
def service_destroy(context, service_id):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.delete(session=session)

        if service_ref.topic == 'compute' and service_ref.compute_node:
            for c in service_ref.compute_node:
                c.delete(session=session)


@require_admin_context
def service_get(context, service_id, session=None):
    result = model_query(context, models.Service, session=session).\
                     options(joinedload('compute_node')).\
                     filter_by(id=service_id).\
                     first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@require_admin_context
def service_get_all(context, disabled=None):
    query = model_query(context, models.Service)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(topic=topic).\
                all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(disabled=False).\
                filter_by(host=host).\
                filter_by(topic=topic).\
                first()


@require_admin_context
def service_get_all_by_host(context, host):
    return model_query(context, models.Service, read_deleted="no").\
                filter_by(host=host).\
                all()


@require_admin_context
def service_get_all_compute_by_host(context, host):
    result = model_query(context, models.Service, read_deleted="no").\
                options(joinedload('compute_node')).\
                filter_by(host=host).\
                filter_by(topic="compute").\
                all()

    if not result:
        raise exception.ComputeHostNotFound(host=host)

    return result


@require_admin_context
def _service_get_all_topic_subquery(context, session, topic, subq, label):
    sort_value = getattr(subq.c, label)
    return model_query(context, models.Service,
                       func.coalesce(sort_value, 0),
                       session=session, read_deleted="no").\
                filter_by(topic=topic).\
                filter_by(disabled=False).\
                outerjoin((subq, models.Service.host == subq.c.host)).\
                order_by(sort_value).\
                all()


@require_admin_context
def service_get_all_compute_sorted(context):
    session = get_session()
    with session.begin():
        # NOTE(vish): The intended query is below
        #             SELECT services.*, COALESCE(inst_cores.instance_cores,
        #                                         0)
        #             FROM services LEFT OUTER JOIN
        #             (SELECT host, SUM(instances.vcpus) AS instance_cores
        #              FROM instances GROUP BY host) AS inst_cores
        #             ON services.host = inst_cores.host
        topic = 'compute'
        label = 'instance_cores'
        subq = model_query(context, models.Instance.host,
                           func.sum(models.Instance.vcpus).label(label),
                           session=session, read_deleted="no").\
                       group_by(models.Instance.host).\
                       subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_all_volume_sorted(context):
    session = get_session()
    with session.begin():
        topic = 'volume'
        label = 'volume_gigabytes'
        subq = model_query(context, models.Volume.host,
                           func.sum(models.Volume.size).label(label),
                           session=session, read_deleted="no").\
                       group_by(models.Volume.host).\
                       subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_by_args(context, host, binary):
    result = model_query(context, models.Service).\
                     filter_by(host=host).\
                     filter_by(binary=binary).\
                     first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not FLAGS.enable_new_services:
        service_ref.disabled = True
    service_ref.save()
    return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = service_get(context, service_id, session=session)
        service_ref.update(values)
        service_ref.save(session=session)


###################


@require_admin_context
def compute_node_get(context, compute_id, session=None):
    result = model_query(context, models.ComputeNode, session=session).\
                     filter_by(id=compute_id).\
                     first()

    if not result:
        raise exception.ComputeHostNotFound(host=compute_id)

    return result


@require_admin_context
def compute_node_get_all(context, session=None):
    return model_query(context, models.ComputeNode, session=session).\
                    options(joinedload('service')).\
                    all()


def _get_host_utilization(context, host, ram_mb, disk_gb):
    """Compute the current utilization of a given host."""
    instances = instance_get_all_by_host(context, host)
    vms = len(instances)
    free_ram_mb = ram_mb - FLAGS.reserved_host_memory_mb
    free_disk_gb = disk_gb - (FLAGS.reserved_host_disk_mb * 1024)

    work = 0
    for instance in instances:
        free_ram_mb -= instance.memory_mb
        free_disk_gb -= instance.root_gb
        free_disk_gb -= instance.ephemeral_gb
        if instance.vm_state in [vm_states.BUILDING, vm_states.REBUILDING,
                                 vm_states.MIGRATING, vm_states.RESIZING]:
            work += 1
    return dict(free_ram_mb=free_ram_mb,
                free_disk_gb=free_disk_gb,
                current_workload=work,
                running_vms=vms)


def _adjust_compute_node_values_for_utilization(context, values, session):
    service_ref = service_get(context, values['service_id'], session=session)
    host = service_ref['host']
    ram_mb = values['memory_mb']
    disk_gb = values['local_gb']
    values.update(_get_host_utilization(context, host, ram_mb, disk_gb))


@require_admin_context
def compute_node_create(context, values, session=None):
    """Creates a new ComputeNode and populates the capacity fields
    with the most recent data."""
    if not session:
        session = get_session()

    _adjust_compute_node_values_for_utilization(context, values, session)
    with session.begin(subtransactions=True):
        compute_node_ref = models.ComputeNode()
        session.add(compute_node_ref)
        compute_node_ref.update(values)
    return compute_node_ref


@require_admin_context
def compute_node_update(context, compute_id, values, auto_adjust):
    """Creates a new ComputeNode and populates the capacity fields
    with the most recent data."""
    session = get_session()
    if auto_adjust:
        _adjust_compute_node_values_for_utilization(context, values, session)
    with session.begin(subtransactions=True):
        compute_ref = compute_node_get(context, compute_id, session=session)
        compute_ref.update(values)
        compute_ref.save(session=session)


def compute_node_get_by_host(context, host):
    """Get all capacity entries for the given host."""
    session = get_session()
    with session.begin():
        node = session.query(models.ComputeNode).\
                             options(joinedload('service')).\
                             filter(models.Service.host == host).\
                             filter_by(deleted=False)
        return node.first()


def compute_node_utilization_update(context, host, free_ram_mb_delta=0,
                          free_disk_gb_delta=0, work_delta=0, vm_delta=0):
    """Update a specific ComputeNode entry by a series of deltas.
    Do this as a single atomic action and lock the row for the
    duration of the operation. Requires that ComputeNode record exist."""
    session = get_session()
    compute_node = None
    with session.begin(subtransactions=True):
        compute_node = session.query(models.ComputeNode).\
                              options(joinedload('service')).\
                              filter(models.Service.host == host).\
                              filter_by(deleted=False).\
                              with_lockmode('update').\
                              first()
        if compute_node is None:
            raise exception.NotFound(_("No ComputeNode for %(host)s") %
                                     locals())

        # This table thingy is how we get atomic UPDATE x = x + 1
        # semantics.
        table = models.ComputeNode.__table__
        if free_ram_mb_delta != 0:
            compute_node.free_ram_mb = table.c.free_ram_mb + free_ram_mb_delta
        if free_disk_gb_delta != 0:
            compute_node.free_disk_gb = (table.c.free_disk_gb +
                                         free_disk_gb_delta)
        if work_delta != 0:
            compute_node.current_workload = (table.c.current_workload +
                                             work_delta)
        if vm_delta != 0:
            compute_node.running_vms = table.c.running_vms + vm_delta
    return compute_node


def compute_node_utilization_set(context, host, free_ram_mb=None,
                                 free_disk_gb=None, work=None, vms=None):
    """Like compute_node_utilization_update() modify a specific host
    entry. But this function will set the metrics absolutely
    (vs. a delta update).
    """
    session = get_session()
    compute_node = None
    with session.begin(subtransactions=True):
        compute_node = session.query(models.ComputeNode).\
                              options(joinedload('service')).\
                              filter(models.Service.host == host).\
                              filter_by(deleted=False).\
                              with_lockmode('update').\
                              first()
        if compute_node is None:
            raise exception.NotFound(_("No ComputeNode for %(host)s") %
                                     locals())

        if free_ram_mb != None:
            compute_node.free_ram_mb = free_ram_mb
        if free_disk_gb != None:
            compute_node.free_disk_gb = free_disk_gb
        if work != None:
            compute_node.current_workload = work
        if vms != None:
            compute_node.running_vms = vms

    return compute_node


###################


@require_admin_context
def certificate_get(context, certificate_id, session=None):
    result = model_query(context, models.Certificate, session=session).\
                     filter_by(id=certificate_id).\
                     first()

    if not result:
        raise exception.CertificateNotFound(certificate_id=certificate_id)

    return result


@require_admin_context
def certificate_create(context, values):
    certificate_ref = models.Certificate()
    for (key, value) in values.iteritems():
        certificate_ref[key] = value
    certificate_ref.save()
    return certificate_ref


@require_admin_context
def certificate_get_all_by_project(context, project_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()


@require_admin_context
def certificate_get_all_by_user(context, user_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   all()


@require_admin_context
def certificate_get_all_by_user_and_project(context, user_id, project_id):
    return model_query(context, models.Certificate, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   all()


###################


@require_context
def floating_ip_get(context, id):
    result = model_query(context, models.FloatingIp, project_only=True).\
                 filter_by(id=id).\
                 first()

    if not result:
        raise exception.FloatingIpNotFound(id=id)

    return result


@require_context
def floating_ip_get_pools(context):
    session = get_session()
    pools = []
    for result in session.query(models.FloatingIp.pool).distinct():
        pools.append({'name': result[0]})
    return pools


@require_context
def floating_ip_allocate_address(context, project_id, pool):
    authorize_project_context(context, project_id)
    session = get_session()
    with session.begin():
        floating_ip_ref = model_query(context, models.FloatingIp,
                                      session=session, read_deleted="no").\
                                  filter_by(fixed_ip_id=None).\
                                  filter_by(project_id=None).\
                                  filter_by(pool=pool).\
                                  with_lockmode('update').\
                                  first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not floating_ip_ref:
            raise exception.NoMoreFloatingIps()
        floating_ip_ref['project_id'] = project_id
        session.add(floating_ip_ref)
    return floating_ip_ref['address']


@require_context
def floating_ip_create(context, values):
    floating_ip_ref = models.FloatingIp()
    floating_ip_ref.update(values)
    floating_ip_ref.save()
    return floating_ip_ref['address']


@require_context
def floating_ip_count_by_project(context, project_id):
    authorize_project_context(context, project_id)
    # TODO(tr3buchet): why leave auto_assigned floating IPs out?
    return model_query(context, models.FloatingIp, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   filter_by(auto_assigned=False).\
                   count()


@require_context
def floating_ip_fixed_ip_associate(context, floating_address,
                                   fixed_address, host):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     floating_address,
                                                     session=session)
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               fixed_address,
                                               session=session)
        floating_ip_ref.fixed_ip_id = fixed_ip_ref["id"]
        floating_ip_ref.host = host
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_deallocate(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref['project_id'] = None
        floating_ip_ref['host'] = None
        floating_ip_ref['auto_assigned'] = False
        floating_ip_ref.save(session=session)


@require_context
def floating_ip_destroy(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref.delete(session=session)


@require_context
def floating_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        fixed_ip_ref = fixed_ip_get(context,
                                    floating_ip_ref['fixed_ip_id'])
        if fixed_ip_ref:
            fixed_ip_address = fixed_ip_ref['address']
        else:
            fixed_ip_address = None
        floating_ip_ref.fixed_ip_id = None
        floating_ip_ref.host = None
        floating_ip_ref.save(session=session)
    return fixed_ip_address


@require_context
def floating_ip_set_auto_assigned(context, address):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context,
                                                     address,
                                                     session=session)
        floating_ip_ref.auto_assigned = True
        floating_ip_ref.save(session=session)


def _floating_ip_get_all(context):
    return model_query(context, models.FloatingIp, read_deleted="no")


@require_admin_context
def floating_ip_get_all(context):
    floating_ip_refs = _floating_ip_get_all(context).all()
    if not floating_ip_refs:
        raise exception.NoFloatingIpsDefined()
    return floating_ip_refs


@require_admin_context
def floating_ip_get_all_by_host(context, host):
    floating_ip_refs = _floating_ip_get_all(context).\
                            filter_by(host=host).\
                            all()
    if not floating_ip_refs:
        raise exception.FloatingIpNotFoundForHost(host=host)
    return floating_ip_refs


@require_context
def floating_ip_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    # TODO(tr3buchet): why do we not want auto_assigned floating IPs here?
    return _floating_ip_get_all(context).\
                         filter_by(project_id=project_id).\
                         filter_by(auto_assigned=False).\
                         all()


@require_context
def floating_ip_get_by_address(context, address, session=None):
    result = model_query(context, models.FloatingIp, session=session).\
                filter_by(address=address).\
                first()

    if not result:
        raise exception.FloatingIpNotFoundForAddress(address=address)

    # If the floating IP has a project ID set, check to make sure
    # the non-admin user has access.
    if result.project_id and is_user_context(context):
        authorize_project_context(context, result.project_id)

    return result


@require_context
def floating_ip_get_by_fixed_address(context, fixed_address, session=None):
    if not session:
        session = get_session()

    fixed_ip = fixed_ip_get_by_address(context, fixed_address, session)
    fixed_ip_id = fixed_ip['id']

    return model_query(context, models.FloatingIp, session=session).\
                   filter_by(fixed_ip_id=fixed_ip_id).\
                   all()

    # NOTE(tr3buchet) please don't invent an exception here, empty list is fine


@require_context
def floating_ip_get_by_fixed_ip_id(context, fixed_ip_id, session=None):
    if not session:
        session = get_session()

    return model_query(context, models.FloatingIp, session=session).\
                   filter_by(fixed_ip_id=fixed_ip_id).\
                   all()


@require_context
def floating_ip_update(context, address, values):
    session = get_session()
    with session.begin():
        floating_ip_ref = floating_ip_get_by_address(context, address, session)
        for (key, value) in values.iteritems():
            floating_ip_ref[key] = value
        floating_ip_ref.save(session=session)


@require_context
def _dnsdomain_get(context, session, fqdomain):
    return model_query(context, models.DNSDomain,
                       session=session, read_deleted="no").\
               filter_by(domain=fqdomain).\
               with_lockmode('update').\
               first()


@require_context
def dnsdomain_get(context, fqdomain):
    session = get_session()
    with session.begin():
        return _dnsdomain_get(context, session, fqdomain)


@require_admin_context
def _dnsdomain_get_or_create(context, session, fqdomain):
    domain_ref = _dnsdomain_get(context, session, fqdomain)
    if not domain_ref:
        dns_ref = models.DNSDomain()
        dns_ref.update({'domain': fqdomain,
                        'availability_zone': None,
                        'project_id': None})
        return dns_ref

    return domain_ref


@require_admin_context
def dnsdomain_register_for_zone(context, fqdomain, zone):
    session = get_session()
    with session.begin():
        domain_ref = _dnsdomain_get_or_create(context, session, fqdomain)
        domain_ref.scope = 'private'
        domain_ref.availability_zone = zone
        domain_ref.save(session=session)


@require_admin_context
def dnsdomain_register_for_project(context, fqdomain, project):
    session = get_session()
    with session.begin():
        domain_ref = _dnsdomain_get_or_create(context, session, fqdomain)
        domain_ref.scope = 'public'
        domain_ref.project_id = project
        domain_ref.save(session=session)


@require_admin_context
def dnsdomain_unregister(context, fqdomain):
    session = get_session()
    with session.begin():
        session.query(models.DNSDomain).\
                     filter_by(domain=fqdomain).\
                     delete()


@require_context
def dnsdomain_list(context):
    session = get_session()
    records = model_query(context, models.DNSDomain,
                  session=session, read_deleted="no").\
                  with_lockmode('update').all()
    domains = []
    for record in records:
        domains.append(record.domain)

    return domains


###################


@require_admin_context
def fixed_ip_associate(context, address, instance_id, network_id=None,
                       reserved=False):
    """Keyword arguments:
    reserved -- should be a boolean value(True or False), exact value will be
    used to filter on the fixed ip address
    """
    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = model_query(context, models.FixedIp, session=session,
                                   read_deleted="no").\
                               filter(network_or_none).\
                               filter_by(reserved=reserved).\
                               filter_by(address=address).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if fixed_ip_ref is None:
            raise exception.FixedIpNotFoundForNetwork(address=address,
                                            network_id=network_id)
        if fixed_ip_ref.instance_id:
            raise exception.FixedIpAlreadyInUse(address=address)

        if not fixed_ip_ref.network_id:
            fixed_ip_ref.network_id = network_id
        fixed_ip_ref.instance_id = instance_id
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_admin_context
def fixed_ip_associate_pool(context, network_id, instance_id=None, host=None):
    session = get_session()
    with session.begin():
        network_or_none = or_(models.FixedIp.network_id == network_id,
                              models.FixedIp.network_id == None)
        fixed_ip_ref = model_query(context, models.FixedIp, session=session,
                                   read_deleted="no").\
                               filter(network_or_none).\
                               filter_by(reserved=False).\
                               filter_by(instance_id=None).\
                               filter_by(host=None).\
                               with_lockmode('update').\
                               first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not fixed_ip_ref:
            raise exception.NoMoreFixedIps()

        if fixed_ip_ref['network_id'] is None:
            fixed_ip_ref['network'] = network_id

        if instance_id:
            fixed_ip_ref['instance_id'] = instance_id

        if host:
            fixed_ip_ref['host'] = host
        session.add(fixed_ip_ref)
    return fixed_ip_ref['address']


@require_context
def fixed_ip_create(context, values):
    fixed_ip_ref = models.FixedIp()
    fixed_ip_ref.update(values)
    fixed_ip_ref.save()
    return fixed_ip_ref['address']


@require_context
def fixed_ip_bulk_create(context, ips):
    session = get_session()
    with session.begin():
        for ip in ips:
            model = models.FixedIp()
            model.update(ip)
            session.add(model)


@require_context
def fixed_ip_disassociate(context, address):
    session = get_session()
    with session.begin():
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               address,
                                               session=session)
        fixed_ip_ref['instance_id'] = None
        fixed_ip_ref.save(session=session)


@require_admin_context
def fixed_ip_disassociate_all_by_timeout(context, host, time):
    session = get_session()
    # NOTE(vish): only update fixed ips that "belong" to this
    #             host; i.e. the network host or the instance
    #             host matches. Two queries necessary because
    #             join with update doesn't work.
    host_filter = or_(and_(models.Instance.host == host,
                           models.Network.multi_host == True),
                      models.Network.host == host)
    result = session.query(models.FixedIp.id).\
                     filter(models.FixedIp.deleted == False).\
                     filter(models.FixedIp.allocated == False).\
                     filter(models.FixedIp.updated_at < time).\
                     join((models.Network,
                           models.Network.id == models.FixedIp.network_id)).\
                     join((models.Instance,
                           models.Instance.id == models.FixedIp.instance_id)).\
                     filter(host_filter).\
                     all()
    fixed_ip_ids = [fip[0] for fip in result]
    if not fixed_ip_ids:
        return 0
    result = model_query(context, models.FixedIp, session=session).\
                     filter(models.FixedIp.id.in_(fixed_ip_ids)).\
                     update({'instance_id': None,
                             'leased': False,
                             'updated_at': utils.utcnow()},
                             synchronize_session='fetch')
    return result


@require_context
def fixed_ip_get(context, id, session=None):
    result = model_query(context, models.FixedIp, session=session).\
                     filter_by(id=id).\
                     first()
    if not result:
        raise exception.FixedIpNotFound(id=id)

    # FIXME(sirp): shouldn't we just use project_only here to restrict the
    # results?
    if is_user_context(context) and result['instance_id'] is not None:
        instance = instance_get(context, result['instance_id'], session)
        authorize_project_context(context, instance.project_id)

    return result


@require_admin_context
def fixed_ip_get_all(context, session=None):
    result = model_query(context, models.FixedIp, session=session,
                         read_deleted="yes").\
                     all()
    if not result:
        raise exception.NoFixedIpsDefined()

    return result


@require_context
def fixed_ip_get_by_address(context, address, session=None):
    result = model_query(context, models.FixedIp, session=session,
                         read_deleted="yes").\
                     filter_by(address=address).\
                     first()
    if not result:
        raise exception.FixedIpNotFoundForAddress(address=address)

    # NOTE(sirp): shouldn't we just use project_only here to restrict the
    # results?
    if is_user_context(context) and result['instance_id'] is not None:
        instance = instance_get(context, result['instance_id'], session)
        authorize_project_context(context, instance.project_id)

    return result


@require_context
def fixed_ip_get_by_instance(context, instance_id):
    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(instance_id=instance_id).\
                 all()

    if not result:
        raise exception.FixedIpNotFoundForInstance(instance_id=instance_id)

    return result


@require_context
def fixed_ip_get_by_network_host(context, network_id, host):
    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(network_id=network_id).\
                 filter_by(host=host).\
                 first()

    if not result:
        raise exception.FixedIpNotFoundForNetworkHost(network_id=network_id,
                                                      host=host)
    return result


@require_context
def fixed_ips_by_virtual_interface(context, vif_id):
    result = model_query(context, models.FixedIp, read_deleted="no").\
                 filter_by(virtual_interface_id=vif_id).\
                 all()

    return result


@require_admin_context
def fixed_ip_get_network(context, address):
    fixed_ip_ref = fixed_ip_get_by_address(context, address)
    return fixed_ip_ref.network


@require_context
def fixed_ip_update(context, address, values):
    session = get_session()
    with session.begin():
        fixed_ip_ref = fixed_ip_get_by_address(context,
                                               address,
                                               session=session)
        fixed_ip_ref.update(values)
        fixed_ip_ref.save(session=session)


###################


@require_context
def virtual_interface_create(context, values):
    """Create a new virtual interface record in the database.

    :param values: = dict containing column values
    """
    try:
        vif_ref = models.VirtualInterface()
        vif_ref.update(values)
        vif_ref.save()
    except IntegrityError:
        raise exception.VirtualInterfaceCreateException()

    return vif_ref


@require_context
def _virtual_interface_query(context, session=None):
    return model_query(context, models.VirtualInterface, session=session,
                       read_deleted="yes")


@require_context
def virtual_interface_get(context, vif_id, session=None):
    """Gets a virtual interface from the table.

    :param vif_id: = id of the virtual interface
    """
    vif_ref = _virtual_interface_query(context, session=session).\
                      filter_by(id=vif_id).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_address(context, address):
    """Gets a virtual interface from the table.

    :param address: = the address of the interface you're looking to get
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(address=address).\
                      first()
    return vif_ref


@require_context
def virtual_interface_get_by_uuid(context, vif_uuid):
    """Gets a virtual interface from the table.

    :param vif_uuid: the uuid of the interface you're looking to get
    """
    vif_ref = _virtual_interface_query(context).\
                      filter_by(uuid=vif_uuid).\
                      first()
    return vif_ref


@require_context
@require_instance_exists
def virtual_interface_get_by_instance(context, instance_id):
    """Gets all virtual interfaces for instance.

    :param instance_id: = id of the instance to retrieve vifs for
    """
    vif_refs = _virtual_interface_query(context).\
                       filter_by(instance_id=instance_id).\
                       all()
    return vif_refs


@require_context
def virtual_interface_get_by_instance_and_network(context, instance_id,
                                                           network_id):
    """Gets virtual interface for instance that's associated with network."""
    vif_ref = _virtual_interface_query(context).\
                      filter_by(instance_id=instance_id).\
                      filter_by(network_id=network_id).\
                      first()
    return vif_ref


@require_context
def virtual_interface_delete(context, vif_id):
    """Delete virtual interface record from the database.

    :param vif_id: = id of vif to delete
    """
    session = get_session()
    vif_ref = virtual_interface_get(context, vif_id, session)
    with session.begin():
        session.delete(vif_ref)


@require_context
def virtual_interface_delete_by_instance(context, instance_id):
    """Delete virtual interface records that are associated
    with the instance given by instance_id.

    :param instance_id: = id of instance
    """
    vif_refs = virtual_interface_get_by_instance(context, instance_id)
    for vif_ref in vif_refs:
        virtual_interface_delete(context, vif_ref['id'])


@require_context
def virtual_interface_get_all(context):
    """Get all vifs"""
    vif_refs = _virtual_interface_query(context).all()
    return vif_refs


###################


def _metadata_refs(metadata_dict, meta_class):
    metadata_refs = []
    if metadata_dict:
        for k, v in metadata_dict.iteritems():
            metadata_ref = meta_class()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    return metadata_refs


@require_context
def instance_create(context, values):
    """Create a new Instance record in the database.

    context - request context object
    values - dict containing column values.
    """
    values = values.copy()
    values['metadata'] = _metadata_refs(values.get('metadata'),
                                        models.InstanceMetadata)
    instance_ref = models.Instance()
    if not values.get('uuid'):
        values['uuid'] = str(utils.gen_uuid())
    instance_ref.update(values)

    session = get_session()
    with session.begin():
        instance_ref.save(session=session)

    # and creat the info_cache table entry for instance
    instance_info_cache_create(context, {'instance_id': instance_ref['uuid']})

    return instance_ref


@require_admin_context
def instance_data_get_for_project(context, project_id):
    result = model_query(context,
                         func.count(models.Instance.id),
                         func.sum(models.Instance.vcpus),
                         func.sum(models.Instance.memory_mb),
                         read_deleted="no").\
                     filter_by(project_id=project_id).\
                     first()
    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0, result[2] or 0)


@require_context
def instance_destroy(context, instance_id):
    session = get_session()
    with session.begin():
        if utils.is_uuid_like(instance_id):
            instance_ref = instance_get_by_uuid(context, instance_id,
                    session=session)
            instance_id = instance_ref['id']
        else:
            instance_ref = instance_get(context, instance_id,
                    session=session)
        session.query(models.Instance).\
                filter_by(id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.InstanceMetadata).\
                filter_by(instance_id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.BlockDeviceMapping).\
                filter_by(instance_id=instance_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})

        instance_info_cache_delete(context, instance_ref['uuid'],
                                   session=session)
    return instance_ref


@require_context
def instance_get_by_uuid(context, uuid, session=None):
    result = _build_instance_get(context, session=session).\
                filter_by(uuid=uuid).\
                first()

    if not result:
        raise exception.InstanceNotFound(instance_id=uuid)

    return result


@require_context
def instance_get(context, instance_id, session=None):
    result = _build_instance_get(context, session=session).\
                filter_by(id=instance_id).\
                first()

    if not result:
        raise exception.InstanceNotFound(instance_id=instance_id)

    return result


@require_context
def _build_instance_get(context, session=None):
    return model_query(context, models.Instance, session=session,
                        project_only=True).\
            options(joinedload_all('security_groups.rules')).\
            options(joinedload('info_cache')).\
            options(joinedload('volumes')).\
            options(joinedload('metadata')).\
            options(joinedload('instance_type'))


@require_admin_context
def instance_get_all(context):
    return model_query(context, models.Instance).\
                   options(joinedload('info_cache')).\
                   options(joinedload('security_groups')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type')).\
                   all()


@require_context
def instance_get_all_by_filters(context, filters, sort_key, sort_dir):
    """Return instances that match all filters.  Deleted instances
    will be returned by default, unless there's a filter that says
    otherwise"""

    def _regexp_filter_by_metadata(instance, meta):
        inst_metadata = [{node['key']: node['value']}
                         for node in instance['metadata']]
        if isinstance(meta, list):
            for node in meta:
                if node not in inst_metadata:
                    return False
        elif isinstance(meta, dict):
            for k, v in meta.iteritems():
                if {k: v} not in inst_metadata:
                    return False
        return True

    def _regexp_filter_by_column(instance, filter_name, filter_re):
        try:
            v = getattr(instance, filter_name)
        except AttributeError:
            return True
        if v and filter_re.match(str(v)):
            return True
        return False

    sort_fn = {'desc': desc, 'asc': asc}

    session = get_session()
    query_prefix = session.query(models.Instance).\
            options(joinedload('info_cache')).\
            options(joinedload('security_groups')).\
            options(joinedload('metadata')).\
            options(joinedload('instance_type')).\
            order_by(sort_fn[sort_dir](getattr(models.Instance, sort_key)))

    # Make a copy of the filters dictionary to use going forward, as we'll
    # be modifying it and we shouldn't affect the caller's use of it.
    filters = filters.copy()

    if 'changes-since' in filters:
        changes_since = utils.normalize_time(filters['changes-since'])
        query_prefix = query_prefix.\
                            filter(models.Instance.updated_at > changes_since)

    if 'deleted' in filters:
        # Instances can be soft or hard deleted and the query needs to
        # include or exclude both
        if filters.pop('deleted'):
            deleted = or_(models.Instance.deleted == True,
                          models.Instance.vm_state == vm_states.SOFT_DELETE)
            query_prefix = query_prefix.filter(deleted)
        else:
            query_prefix = query_prefix.\
                    filter_by(deleted=False).\
                    filter(models.Instance.vm_state != vm_states.SOFT_DELETE)

    if not context.is_admin:
        # If we're not admin context, add appropriate filter..
        if context.project_id:
            filters['project_id'] = context.project_id
        else:
            filters['user_id'] = context.user_id

    # Filters for exact matches that we can do along with the SQL query...
    # For other filters that don't match this, we will do regexp matching
    exact_match_filter_names = ['project_id', 'user_id', 'image_ref',
            'vm_state', 'instance_type_id', 'uuid']

    # Filter the query
    query_prefix = exact_filter(query_prefix, models.Instance,
                                filters, exact_match_filter_names)

    instances = query_prefix.all()
    if not instances:
        return []

    # Now filter on everything else for regexp matching..
    # For filters not in the list, we'll attempt to use the filter_name
    # as a column name in Instance..
    regexp_filter_funcs = {}

    for filter_name in filters.iterkeys():
        filter_func = regexp_filter_funcs.get(filter_name, None)
        filter_re = re.compile(str(filters[filter_name]))
        if filter_func:
            filter_l = lambda instance: filter_func(instance, filter_re)
        elif filter_name == 'metadata':
            filter_l = lambda instance: _regexp_filter_by_metadata(instance,
                    filters[filter_name])
        else:
            filter_l = lambda instance: _regexp_filter_by_column(instance,
                    filter_name, filter_re)
        instances = filter(filter_l, instances)
        if not instances:
            break

    return instances


@require_context
def instance_get_active_by_window(context, begin, end=None, project_id=None):
    """Return instances that were active during window."""
    session = get_session()
    query = session.query(models.Instance)

    query = query.filter(or_(models.Instance.terminated_at == None,
                             models.Instance.terminated_at > begin))
    if end:
        query = query.filter(models.Instance.launched_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)

    return query.all()


@require_admin_context
def instance_get_active_by_window_joined(context, begin, end=None,
                                         project_id=None):
    """Return instances and joins that were active during window."""
    session = get_session()
    query = session.query(models.Instance)

    query = query.options(joinedload('info_cache')).\
                  options(joinedload('security_groups')).\
                  options(joinedload('metadata')).\
                  options(joinedload('instance_type')).\
                  filter(or_(models.Instance.terminated_at == None,
                             models.Instance.terminated_at > begin))
    if end:
        query = query.filter(models.Instance.launched_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)

    return query.all()


@require_admin_context
def _instance_get_all_query(context, project_only=False):
    return model_query(context, models.Instance, project_only=project_only).\
                   options(joinedload('info_cache')).\
                   options(joinedload('security_groups')).\
                   options(joinedload('metadata')).\
                   options(joinedload('instance_type'))


@require_admin_context
def instance_get_all_by_host(context, host):
    return _instance_get_all_query(context).filter_by(host=host).all()


@require_context
def instance_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return _instance_get_all_query(context).\
                    filter_by(project_id=project_id).\
                    all()


@require_context
def instance_get_all_by_reservation(context, reservation_id):
    return _instance_get_all_query(context, project_only=True).\
                    filter_by(reservation_id=reservation_id).\
                    all()


# NOTE(jkoelker) This is only being left here for compat with floating
#                ips. Currently the network_api doesn't return floaters
#                in network_info. Once it starts return the model. This
#                function and it's call in compute/manager.py on 1829 can
#                go away
@require_context
def instance_get_floating_address(context, instance_id):
    fixed_ips = fixed_ip_get_by_instance(context, instance_id)
    if not fixed_ips:
        return None
    # NOTE(tr3buchet): this only gets the first fixed_ip
    # won't find floating ips associated with other fixed_ips
    floating_ips = floating_ip_get_by_fixed_address(context,
                                                    fixed_ips[0]['address'])
    if not floating_ips:
        return None
    # NOTE(vish): this just returns the first floating ip
    return floating_ips[0]['address']


@require_admin_context
def instance_get_all_hung_in_rebooting(context, reboot_window, session=None):
    reboot_window = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=reboot_window)

    if not session:
        session = get_session()

    results = session.query(models.Instance).\
            filter(models.Instance.updated_at <= reboot_window).\
            filter_by(task_state="rebooting").all()

    return results


@require_context
def instance_test_and_set(context, instance_id, attr, ok_states,
                          new_state, session=None):
    """Atomically check if an instance is in a valid state, and if it is, set
    the instance into a new state.
    """
    if not session:
        session = get_session()

    with session.begin():
        query = model_query(context, models.Instance, session=session,
                            project_only=True)

        if utils.is_uuid_like(instance_id):
            query = query.filter_by(uuid=instance_id)
        else:
            query = query.filter_by(id=instance_id)

        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        instance = query.with_lockmode('update').first()

        state = instance[attr]
        if state not in ok_states:
            raise exception.InstanceInvalidState(
                attr=attr,
                instance_uuid=instance['uuid'],
                state=state,
                method='instance_test_and_set')

        instance[attr] = new_state
        instance.save(session=session)


@require_context
def instance_update(context, instance_id, values):
    session = get_session()

    if utils.is_uuid_like(instance_id):
        instance_ref = instance_get_by_uuid(context, instance_id,
                                            session=session)
    else:
        instance_ref = instance_get(context, instance_id, session=session)

    metadata = values.get('metadata')
    if metadata is not None:
        instance_metadata_update(context,
                                 instance_ref['id'],
                                 values.pop('metadata'),
                                 delete=True)
    with session.begin():
        instance_ref.update(values)
        instance_ref.save(session=session)

    return instance_ref


def instance_add_security_group(context, instance_uuid, security_group_id):
    """Associate the given security group with the given instance"""
    session = get_session()
    with session.begin():
        instance_ref = instance_get_by_uuid(context, instance_uuid,
                                            session=session)
        security_group_ref = security_group_get(context,
                                                security_group_id,
                                                session=session)
        instance_ref.security_groups += [security_group_ref]
        instance_ref.save(session=session)


@require_context
def instance_remove_security_group(context, instance_uuid, security_group_id):
    """Disassociate the given security group from the given instance"""
    session = get_session()
    instance_ref = instance_get_by_uuid(context, instance_uuid,
                                        session=session)
    session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(instance_id=instance_ref['id']).\
                filter_by(security_group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def instance_action_create(context, values):
    """Create an instance action from the values dictionary."""
    action_ref = models.InstanceActions()
    action_ref.update(values)

    session = get_session()
    with session.begin():
        action_ref.save(session=session)
    return action_ref


@require_admin_context
def instance_get_actions(context, instance_uuid):
    """Return the actions associated to the given instance id"""
    session = get_session()
    return session.query(models.InstanceActions).\
                   filter_by(instance_uuid=instance_uuid).\
                   all()


@require_context
def instance_get_id_to_uuid_mapping(context, ids):
    session = get_session()
    instances = session.query(models.Instance).\
                        filter(models.Instance.id.in_(ids)).\
                        all()
    mapping = {}
    for instance in instances:
        mapping[instance['id']] = instance['uuid']
    return mapping


###################


@require_context
def instance_info_cache_create(context, values):
    """Create a new instance cache record in the table.

    :param context: = request context object
    :param values: = dict containing column values
    """
    info_cache = models.InstanceInfoCache()
    info_cache.update(values)

    session = get_session()
    with session.begin():
        info_cache.save(session=session)
    return info_cache


@require_context
def instance_info_cache_get(context, instance_uuid, session=None):
    """Gets an instance info cache from the table.

    :param instance_uuid: = uuid of the info cache's instance
    :param session: = optional session object
    """
    session = session or get_session()

    info_cache = session.query(models.InstanceInfoCache).\
                         filter_by(instance_id=instance_uuid).\
                         first()
    return info_cache


@require_context
def instance_info_cache_update(context, instance_uuid, values,
                               session=None):
    """Update an instance info cache record in the table.

    :param instance_uuid: = uuid of info cache's instance
    :param values: = dict containing column values to update
    :param session: = optional session object
    """
    session = session or get_session()
    info_cache = instance_info_cache_get(context, instance_uuid,
                                         session=session)

    if info_cache:
        info_cache.update(values)
        info_cache.save(session=session)
    else:
        # NOTE(tr3buchet): just in case someone blows away an instance's
        #                  cache entry
        values['instance_id'] = instance_uuid
        info_cache = instance_info_cache_create(context, values)

    return info_cache


@require_context
def instance_info_cache_delete(context, instance_uuid, session=None):
    """Deletes an existing instance_info_cache record

    :param instance_uuid: = uuid of the instance tied to the cache record
    :param session: = optional session object
    """
    values = {'deleted': True,
              'deleted_at': utils.utcnow()}
    instance_info_cache_update(context, instance_uuid, values, session)


###################


@require_context
def key_pair_create(context, values):
    key_pair_ref = models.KeyPair()
    key_pair_ref.update(values)
    key_pair_ref.save()
    return key_pair_ref


@require_context
def key_pair_destroy(context, user_id, name):
    authorize_user_context(context, user_id)
    session = get_session()
    with session.begin():
        key_pair_ref = key_pair_get(context, user_id, name, session=session)
        key_pair_ref.delete(session=session)


@require_context
def key_pair_destroy_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    session = get_session()
    with session.begin():
        session.query(models.KeyPair).\
                filter_by(user_id=user_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def key_pair_get(context, user_id, name, session=None):
    authorize_user_context(context, user_id)
    result = model_query(context, models.KeyPair, session=session).\
                     filter_by(user_id=user_id).\
                     filter_by(name=name).\
                     first()

    if not result:
        raise exception.KeypairNotFound(user_id=user_id, name=name)

    return result


@require_context
def key_pair_get_all_by_user(context, user_id):
    authorize_user_context(context, user_id)
    return model_query(context, models.KeyPair, read_deleted="no").\
                   filter_by(user_id=user_id).\
                   all()


###################


@require_admin_context
def network_associate(context, project_id, force=False):
    """Associate a project with a network.

    called by project_get_networks under certain conditions
    and network manager add_network_to_project()

    only associate if the project doesn't already have a network
    or if force is True

    force solves race condition where a fresh project has multiple instance
    builds simultaneously picked up by multiple network hosts which attempt
    to associate the project with multiple networks
    force should only be used as a direct consequence of user request
    all automated requests should not use force
    """
    session = get_session()
    with session.begin():

        def network_query(project_filter):
            return model_query(context, models.Network, session=session,
                              read_deleted="no").\
                           filter_by(project_id=project_filter).\
                           with_lockmode('update').\
                           first()

        if not force:
            # find out if project has a network
            network_ref = network_query(project_id)

        if force or not network_ref:
            # in force mode or project doesn't have a network so associate
            # with a new network

            # get new network
            network_ref = network_query(None)
            if not network_ref:
                raise db.NoMoreNetworks()

            # associate with network
            # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
            #             then this has concurrency issues
            network_ref['project_id'] = project_id
            session.add(network_ref)
    return network_ref


@require_admin_context
def network_count(context):
    return model_query(context, models.Network).count()


@require_admin_context
def _network_ips_query(context, network_id):
    return model_query(context, models.FixedIp, read_deleted="no").\
                   filter_by(network_id=network_id)


@require_admin_context
def network_count_reserved_ips(context, network_id):
    return _network_ips_query(context, network_id).\
                    filter_by(reserved=True).\
                    count()


@require_admin_context
def network_create_safe(context, values):
    if values.get('vlan'):
        if model_query(context, models.Network, read_deleted="no")\
                      .filter_by(vlan=values['vlan'])\
                      .first():
            raise exception.DuplicateVlan(vlan=values['vlan'])

    network_ref = models.Network()
    network_ref['uuid'] = str(utils.gen_uuid())
    network_ref.update(values)

    try:
        network_ref.save()
        return network_ref
    except IntegrityError:
        return None


@require_admin_context
def network_delete_safe(context, network_id):
    session = get_session()
    with session.begin():
        network_ref = network_get(context, network_id=network_id,
                                  session=session)
        session.delete(network_ref)


@require_admin_context
def network_disassociate(context, network_id):
    network_update(context, network_id, {'project_id': None,
                                         'host': None})


@require_context
def network_get(context, network_id, session=None):
    result = model_query(context, models.Network, session=session,
                         project_only=True).\
                    filter_by(id=network_id).\
                    first()

    if not result:
        raise exception.NetworkNotFound(network_id=network_id)

    return result


@require_admin_context
def network_get_all(context):
    result = model_query(context, models.Network, read_deleted="no").all()

    if not result:
        raise exception.NoNetworksFound()

    return result


@require_admin_context
def network_get_all_by_uuids(context, network_uuids, project_id=None):
    project_or_none = or_(models.Network.project_id == project_id,
                          models.Network.project_id == None)
    result = model_query(context, models.Network, read_deleted="no").\
                filter(models.Network.uuid.in_(network_uuids)).\
                filter(project_or_none).\
                all()

    if not result:
        raise exception.NoNetworksFound()

    #check if host is set to all of the networks
    # returned in the result
    for network in result:
        if network['host'] is None:
            raise exception.NetworkHostNotSet(network_id=network['id'])

    #check if the result contains all the networks
    #we are looking for
    for network_uuid in network_uuids:
        found = False
        for network in result:
            if network['uuid'] == network_uuid:
                found = True
                break
        if not found:
            if project_id:
                raise exception.NetworkNotFoundForProject(
                      network_uuid=network_uuid, project_id=context.project_id)
            raise exception.NetworkNotFound(network_id=network_uuid)

    return result

# NOTE(vish): pylint complains because of the long method name, but
#             it fits with the names of the rest of the methods
# pylint: disable=C0103


@require_admin_context
def network_get_associated_fixed_ips(context, network_id, host=None):
    # FIXME(sirp): since this returns fixed_ips, this would be better named
    # fixed_ip_get_all_by_network.
    # NOTE(vish): The ugly joins here are to solve a performance issue and
    #             should be removed once we can add and remove leases
    #             without regenerating the whole list
    vif_and = and_(models.VirtualInterface.id ==
                   models.FixedIp.virtual_interface_id,
                   models.VirtualInterface.deleted == False)
    inst_and = and_(models.Instance.id == models.FixedIp.instance_id,
                    models.Instance.deleted == False)
    session = get_session()
    query = session.query(models.FixedIp.address,
                          models.FixedIp.instance_id,
                          models.FixedIp.network_id,
                          models.FixedIp.virtual_interface_id,
                          models.VirtualInterface.address,
                          models.Instance.hostname,
                          models.Instance.updated_at,
                          models.Instance.created_at).\
                          filter(models.FixedIp.deleted == False).\
                          filter(models.FixedIp.network_id == network_id).\
                          filter(models.FixedIp.allocated == True).\
                          join((models.VirtualInterface, vif_and)).\
                          join((models.Instance, inst_and)).\
                          filter(models.FixedIp.instance_id != None).\
                          filter(models.FixedIp.virtual_interface_id != None)
    if host:
        query = query.filter(models.Instance.host == host)
    result = query.all()
    data = []
    for datum in result:
        cleaned = {}
        cleaned['address'] = datum[0]
        cleaned['instance_id'] = datum[1]
        cleaned['network_id'] = datum[2]
        cleaned['vif_id'] = datum[3]
        cleaned['vif_address'] = datum[4]
        cleaned['instance_hostname'] = datum[5]
        cleaned['instance_updated'] = datum[6]
        cleaned['instance_created'] = datum[7]
        data.append(cleaned)
    return data


@require_admin_context
def _network_get_query(context, session=None):
    return model_query(context, models.Network, session=session,
                       read_deleted="no")


@require_admin_context
def network_get_by_bridge(context, bridge):
    result = _network_get_query(context).filter_by(bridge=bridge).first()

    if not result:
        raise exception.NetworkNotFoundForBridge(bridge=bridge)

    return result


@require_admin_context
def network_get_by_uuid(context, uuid):
    result = _network_get_query(context).filter_by(uuid=uuid).first()

    if not result:
        raise exception.NetworkNotFoundForUUID(uuid=uuid)

    return result


@require_admin_context
def network_get_by_cidr(context, cidr):
    result = _network_get_query(context).\
                filter(or_(models.Network.cidr == cidr,
                           models.Network.cidr_v6 == cidr)).\
                first()

    if not result:
        raise exception.NetworkNotFoundForCidr(cidr=cidr)

    return result


@require_admin_context
def network_get_by_instance(context, instance_id):
    # note this uses fixed IP to get to instance
    # only works for networks the instance has an IP from
    result = _network_get_query(context).\
                 filter_by(instance_id=instance_id).\
                 first()

    if not result:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)

    return result


@require_admin_context
def network_get_all_by_instance(context, instance_id):
    result = _network_get_query(context).\
                 filter_by(instance_id=instance_id).\
                 all()

    if not result:
        raise exception.NetworkNotFoundForInstance(instance_id=instance_id)

    return result


@require_admin_context
def network_get_all_by_host(context, host):
    session = get_session()
    fixed_ip_query = model_query(context, models.FixedIp.network_id,
                                 session=session).\
                        filter(models.FixedIp.host == host)
    # NOTE(vish): return networks that have host set
    #             or that have a fixed ip with host set
    host_filter = or_(models.Network.host == host,
                      models.Network.id.in_(fixed_ip_query.subquery()))
    return _network_get_query(context, session=session).\
                       filter(host_filter).\
                       all()


@require_admin_context
def network_set_host(context, network_id, host_id):
    session = get_session()
    with session.begin():
        network_ref = _network_get_query(context, session=session).\
                              filter_by(id=network_id).\
                              with_lockmode('update').\
                              first()

        if not network_ref:
            raise exception.NetworkNotFound(network_id=network_id)

        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not network_ref['host']:
            network_ref['host'] = host_id
            session.add(network_ref)

    return network_ref['host']


@require_context
def network_update(context, network_id, values):
    session = get_session()
    with session.begin():
        network_ref = network_get(context, network_id, session=session)
        network_ref.update(values)
        network_ref.save(session=session)
        return network_ref


###################


def queue_get_for(context, topic, physical_node_id):
    # FIXME(ja): this should be servername?
    return "%s.%s" % (topic, physical_node_id)


###################


@require_admin_context
def iscsi_target_count_by_host(context, host):
    return model_query(context, models.IscsiTarget).\
                   filter_by(host=host).\
                   count()


@require_admin_context
def iscsi_target_create_safe(context, values):
    iscsi_target_ref = models.IscsiTarget()
    for (key, value) in values.iteritems():
        iscsi_target_ref[key] = value
    try:
        iscsi_target_ref.save()
        return iscsi_target_ref
    except IntegrityError:
        return None


###################


@require_admin_context
def auth_token_destroy(context, token_id):
    session = get_session()
    with session.begin():
        token_ref = auth_token_get(context, token_id, session=session)
        token_ref.delete(session=session)


@require_admin_context
def auth_token_get(context, token_hash, session=None):
    result = model_query(context, models.AuthToken, session=session).\
                  filter_by(token_hash=token_hash).\
                  first()

    if not result:
        raise exception.AuthTokenNotFound(token=token_hash)

    return result


@require_admin_context
def auth_token_update(context, token_hash, values):
    session = get_session()
    with session.begin():
        token_ref = auth_token_get(context, token_hash, session=session)
        token_ref.update(values)
        token_ref.save(session=session)


@require_admin_context
def auth_token_create(context, token):
    tk = models.AuthToken()
    tk.update(token)
    tk.save()
    return tk


###################


@require_context
def quota_get(context, project_id, resource, session=None):
    result = model_query(context, models.Quota, session=session,
                         read_deleted="no").\
                     filter_by(project_id=project_id).\
                     filter_by(resource=resource).\
                     first()

    if not result:
        raise exception.ProjectQuotaNotFound(project_id=project_id)

    return result


@require_context
def quota_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.Quota, read_deleted="no").\
                   filter_by(project_id=project_id).\
                   all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_create(context, project_id, resource, limit):
    # NOTE: Treat -1 as unlimited for consistency w/ flags
    if limit == -1:
        limit = None
    quota_ref = models.Quota()
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    quota_ref.save()
    return quota_ref


@require_admin_context
def quota_update(context, project_id, resource, limit):
    # NOTE: Treat -1 as unlimited for consistency w/ flags
    if limit == -1:
        limit = None
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, resource, session=session)
        quota_ref.hard_limit = limit
        quota_ref.save(session=session)


@require_admin_context
def quota_destroy(context, project_id, resource):
    session = get_session()
    with session.begin():
        quota_ref = quota_get(context, project_id, resource, session=session)
        quota_ref.delete(session=session)


@require_admin_context
def quota_destroy_all_by_project(context, project_id):
    session = get_session()
    with session.begin():
        quotas = model_query(context, models.Quota, session=session,
                             read_deleted="no").\
                         filter_by(project_id=project_id).\
                         all()

        for quota_ref in quotas:
            quota_ref.delete(session=session)


###################


@require_admin_context
def volume_allocate_iscsi_target(context, volume_id, host):
    session = get_session()
    with session.begin():
        iscsi_target_ref = model_query(context, models.IscsiTarget,
                                       session=session, read_deleted="no").\
                                filter_by(volume=None).\
                                filter_by(host=host).\
                                with_lockmode('update').\
                                first()

        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not iscsi_target_ref:
            raise db.NoMoreTargets()

        iscsi_target_ref.volume_id = volume_id
        session.add(iscsi_target_ref)

    return iscsi_target_ref.target_num


@require_admin_context
def volume_attached(context, volume_id, instance_id, mountpoint):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'in-use'
        volume_ref['mountpoint'] = mountpoint
        volume_ref['attach_status'] = 'attached'
        volume_ref.instance = instance_get(context, instance_id,
                                           session=session)
        volume_ref.save(session=session)


@require_context
def volume_create(context, values):
    values['volume_metadata'] = _metadata_refs(values.get('metadata'),
                                               models.VolumeMetadata)
    volume_ref = models.Volume()
    volume_ref.update(values)

    session = get_session()
    with session.begin():
        volume_ref.save(session=session)
    return volume_ref


@require_admin_context
def volume_data_get_for_project(context, project_id):
    result = model_query(context,
                         func.count(models.Volume.id),
                         func.sum(models.Volume.size),
                         read_deleted="no").\
                     filter_by(project_id=project_id).\
                     first()

    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_admin_context
def volume_destroy(context, volume_id):
    session = get_session()
    with session.begin():
        session.query(models.Volume).\
                filter_by(id=volume_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.IscsiTarget).\
                filter_by(volume_id=volume_id).\
                update({'volume_id': None})
        session.query(models.VolumeMetadata).\
                filter_by(volume_id=volume_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_admin_context
def volume_detached(context, volume_id):
    session = get_session()
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'available'
        volume_ref['mountpoint'] = None
        volume_ref['attach_status'] = 'detached'
        volume_ref.instance = None
        volume_ref.save(session=session)


@require_context
def _volume_get_query(context, session=None, project_only=False):
    return model_query(context, models.Volume, session=session,
                       project_only=project_only).\
                     options(joinedload('instance')).\
                     options(joinedload('volume_metadata')).\
                     options(joinedload('volume_type'))


@require_context
def volume_get(context, volume_id, session=None):
    result = _volume_get_query(context, session=session, project_only=True).\
                    filter_by(id=volume_id).\
                    first()

    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result


@require_admin_context
def volume_get_all(context):
    return _volume_get_query(context).all()


@require_admin_context
def volume_get_all_by_host(context, host):
    return _volume_get_query(context).filter_by(host=host).all()


@require_admin_context
def volume_get_all_by_instance(context, instance_id):
    result = model_query(context, models.Volume, read_deleted="no").\
                     options(joinedload('volume_metadata')).\
                     options(joinedload('volume_type')).\
                     filter_by(instance_id=instance_id).\
                     all()

    if not result:
        raise exception.VolumeNotFoundForInstance(instance_id=instance_id)

    return result


@require_context
def volume_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return _volume_get_query(context).filter_by(project_id=project_id).all()


@require_admin_context
def volume_get_instance(context, volume_id):
    result = _volume_get_query(context).filter_by(id=volume_id).first()

    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result.instance


@require_admin_context
def volume_get_iscsi_target_num(context, volume_id):
    result = model_query(context, models.IscsiTarget, read_deleted="yes").\
                     filter_by(volume_id=volume_id).\
                     first()

    if not result:
        raise exception.ISCSITargetNotFoundForVolume(volume_id=volume_id)

    return result.target_num


@require_context
def volume_update(context, volume_id, values):
    session = get_session()
    metadata = values.get('metadata')
    if metadata is not None:
        volume_metadata_update(context,
                                volume_id,
                                values.pop('metadata'),
                                delete=True)
    with session.begin():
        volume_ref = volume_get(context, volume_id, session=session)
        volume_ref.update(values)
        volume_ref.save(session=session)


####################

def _volume_metadata_get_query(context, volume_id, session=None):
    return model_query(context, models.VolumeMetadata,
                       session=session, read_deleted="no").\
                    filter_by(volume_id=volume_id)


@require_context
@require_volume_exists
def volume_metadata_get(context, volume_id):
    rows = _volume_metadata_get_query(context, volume_id).all()
    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
@require_volume_exists
def volume_metadata_delete(context, volume_id, key):
    _volume_metadata_get_query(context, volume_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_volume_exists
def volume_metadata_get_item(context, volume_id, key, session=None):
    result = _volume_metadata_get_query(context, volume_id, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.VolumeMetadataNotFound(metadata_key=key,
                                               volume_id=volume_id)
    return result


@require_context
@require_volume_exists
def volume_metadata_update(context, volume_id, metadata, delete):
    session = get_session()

    # Set existing metadata to deleted if delete argument is True
    if delete:
        original_metadata = volume_metadata_get(context, volume_id)
        for meta_key, meta_value in original_metadata.iteritems():
            if meta_key not in metadata:
                meta_ref = volume_metadata_get_item(context, volume_id,
                                                    meta_key, session)
                meta_ref.update({'deleted': True})
                meta_ref.save(session=session)

    meta_ref = None

    # Now update all existing items with new values, or create new meta objects
    for meta_key, meta_value in metadata.iteritems():

        # update the value whether it exists or not
        item = {"value": meta_value}

        try:
            meta_ref = volume_metadata_get_item(context, volume_id,
                                                  meta_key, session)
        except exception.VolumeMetadataNotFound, e:
            meta_ref = models.VolumeMetadata()
            item.update({"key": meta_key, "volume_id": volume_id})

        meta_ref.update(item)
        meta_ref.save(session=session)

    return metadata


###################


@require_context
def snapshot_create(context, values):
    snapshot_ref = models.Snapshot()
    snapshot_ref.update(values)

    session = get_session()
    with session.begin():
        snapshot_ref.save(session=session)
    return snapshot_ref


@require_admin_context
def snapshot_destroy(context, snapshot_id):
    session = get_session()
    with session.begin():
        session.query(models.Snapshot).\
                filter_by(id=snapshot_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def snapshot_get(context, snapshot_id, session=None):
    result = model_query(context, models.Snapshot, session=session,
                         project_only=True).\
                filter_by(id=snapshot_id).\
                first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result


@require_admin_context
def snapshot_get_all(context):
    return model_query(context, models.Snapshot).all()


@require_context
def snapshot_get_all_for_volume(context, volume_id):
    return model_query(context, models.Snapshot, read_deleted='no',
                       project_only=True).\
              filter_by(volume_id=volume_id).all()


@require_context
def snapshot_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return model_query(context, models.Snapshot).\
                   filter_by(project_id=project_id).\
                   all()


@require_context
def snapshot_update(context, snapshot_id, values):
    session = get_session()
    with session.begin():
        snapshot_ref = snapshot_get(context, snapshot_id, session=session)
        snapshot_ref.update(values)
        snapshot_ref.save(session=session)


###################


def _block_device_mapping_get_query(context, session=None):
    return model_query(context, models.BlockDeviceMapping, session=session,
                       read_deleted="no")


@require_context
def block_device_mapping_create(context, values):
    bdm_ref = models.BlockDeviceMapping()
    bdm_ref.update(values)

    session = get_session()
    with session.begin():
        bdm_ref.save(session=session)


@require_context
def block_device_mapping_update(context, bdm_id, values):
    session = get_session()
    with session.begin():
        _block_device_mapping_get_query(context, session=session).\
                filter_by(id=bdm_id).\
                update(values)


@require_context
def block_device_mapping_update_or_create(context, values):
    session = get_session()
    with session.begin():
        result = _block_device_mapping_get_query(context, session=session).\
                 filter_by(instance_id=values['instance_id']).\
                 filter_by(device_name=values['device_name']).\
                 first()
        if not result:
            bdm_ref = models.BlockDeviceMapping()
            bdm_ref.update(values)
            bdm_ref.save(session=session)
        else:
            result.update(values)

        # NOTE(yamahata): same virtual device name can be specified multiple
        #                 times. So delete the existing ones.
        virtual_name = values['virtual_name']
        if (virtual_name is not None and
            block_device.is_swap_or_ephemeral(virtual_name)):
            session.query(models.BlockDeviceMapping).\
                filter_by(instance_id=values['instance_id']).\
                filter_by(virtual_name=virtual_name).\
                filter(models.BlockDeviceMapping.device_name !=
                       values['device_name']).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def block_device_mapping_get_all_by_instance(context, instance_id):
    return _block_device_mapping_get_query(context).\
                 filter_by(instance_id=instance_id).\
                 all()


@require_context
def block_device_mapping_destroy(context, bdm_id):
    session = get_session()
    with session.begin():
        session.query(models.BlockDeviceMapping).\
                filter_by(id=bdm_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_context
def block_device_mapping_destroy_by_instance_and_volume(context, instance_id,
                                                        volume_id):
    session = get_session()
    with session.begin():
        _block_device_mapping_get_query(context, session=session).\
            filter_by(instance_id=instance_id).\
            filter_by(volume_id=volume_id).\
            update({'deleted': True,
                    'deleted_at': utils.utcnow(),
                    'updated_at': literal_column('updated_at')})


###################

def _security_group_get_query(context, session=None, read_deleted=None,
                              project_only=False):
    return model_query(context, models.SecurityGroup, session=session,
                       read_deleted=read_deleted, project_only=project_only).\
                   options(joinedload_all('rules'))


@require_context
def security_group_get_all(context):
    return _security_group_get_query(context).all()


@require_context
def security_group_get(context, security_group_id, session=None):
    result = _security_group_get_query(context, session=session,
                                       project_only=True).\
                    filter_by(id=security_group_id).\
                    options(joinedload_all('instances')).\
                    first()

    if not result:
        raise exception.SecurityGroupNotFound(
                security_group_id=security_group_id)

    return result


@require_context
def security_group_get_by_name(context, project_id, group_name):
    result = _security_group_get_query(context, read_deleted="no").\
                        filter_by(project_id=project_id).\
                        filter_by(name=group_name).\
                        options(joinedload_all('instances')).\
                        first()

    if not result:
        raise exception.SecurityGroupNotFoundForProject(
                project_id=project_id, security_group_id=group_name)

    return result


@require_context
def security_group_get_by_project(context, project_id):
    return _security_group_get_query(context, read_deleted="no").\
                        filter_by(project_id=project_id).\
                        all()


@require_context
def security_group_get_by_instance(context, instance_id):
    return _security_group_get_query(context, read_deleted="no").\
                   join(models.SecurityGroup.instances).\
                   filter_by(id=instance_id).\
                   all()


@require_context
def security_group_exists(context, project_id, group_name):
    try:
        group = security_group_get_by_name(context, project_id, group_name)
        return group is not None
    except exception.NotFound:
        return False


@require_context
def security_group_in_use(context, group_id):
    session = get_session()
    with session.begin():
        # Are there any instances that haven't been deleted
        # that include this group?
        inst_assoc = session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(security_group_id=group_id).\
                filter_by(deleted=False).\
                all()
        for ia in inst_assoc:
            num_instances = session.query(models.Instance).\
                        filter_by(deleted=False).\
                        filter_by(id=ia.instance_id).\
                        count()
            if num_instances:
                return True

    return False


@require_context
def security_group_create(context, values):
    security_group_ref = models.SecurityGroup()
    # FIXME(devcamcar): Unless I do this, rules fails with lazy load exception
    # once save() is called.  This will get cleaned up in next orm pass.
    security_group_ref.rules
    security_group_ref.update(values)
    security_group_ref.save()
    return security_group_ref


@require_context
def security_group_destroy(context, security_group_id):
    session = get_session()
    with session.begin():
        session.query(models.SecurityGroup).\
                filter_by(id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupInstanceAssociation).\
                filter_by(security_group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.SecurityGroupIngressRule).\
                filter_by(group_id=security_group_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


###################


def _security_group_rule_get_query(context, session=None):
    return model_query(context, models.SecurityGroupIngressRule,
                       session=session)


@require_context
def security_group_rule_get(context, security_group_rule_id, session=None):
    result = _security_group_rule_get_query(context, session=session).\
                         filter_by(id=security_group_rule_id).\
                         first()

    if not result:
        raise exception.SecurityGroupNotFoundForRule(
                                               rule_id=security_group_rule_id)

    return result


@require_context
def security_group_rule_get_by_security_group(context, security_group_id,
                                              session=None):
    return _security_group_rule_get_query(context, session=session).\
                         filter_by(parent_group_id=security_group_id).\
                         options(joinedload_all('grantee_group.instances')).\
                         all()


@require_context
def security_group_rule_get_by_security_group_grantee(context,
                                                      security_group_id,
                                                      session=None):

    return _security_group_rule_get_query(context, session=session).\
                         filter_by(group_id=security_group_id).\
                         all()


@require_context
def security_group_rule_create(context, values):
    security_group_rule_ref = models.SecurityGroupIngressRule()
    security_group_rule_ref.update(values)
    security_group_rule_ref.save()
    return security_group_rule_ref


@require_context
def security_group_rule_destroy(context, security_group_rule_id):
    session = get_session()
    with session.begin():
        security_group_rule = security_group_rule_get(context,
                                                      security_group_rule_id,
                                                      session=session)
        security_group_rule.delete(session=session)


###################


@require_admin_context
def provider_fw_rule_create(context, rule):
    fw_rule_ref = models.ProviderFirewallRule()
    fw_rule_ref.update(rule)
    fw_rule_ref.save()
    return fw_rule_ref


@require_admin_context
def provider_fw_rule_get_all(context):
    return model_query(context, models.ProviderFirewallRule).all()


@require_admin_context
def provider_fw_rule_destroy(context, rule_id):
    session = get_session()
    with session.begin():
        session.query(models.ProviderFirewallRule).\
                filter_by(id=rule_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


###################


@require_admin_context
def user_get(context, id, session=None):
    result = model_query(context, models.User, session=session).\
                     filter_by(id=id).\
                     first()

    if not result:
        raise exception.UserNotFound(user_id=id)

    return result


@require_admin_context
def user_get_by_access_key(context, access_key, session=None):
    result = model_query(context, models.User, session=session).\
                   filter_by(access_key=access_key).\
                   first()

    if not result:
        raise exception.AccessKeyNotFound(access_key=access_key)

    return result


@require_admin_context
def user_create(context, values):
    user_ref = models.User()
    user_ref.update(values)
    user_ref.save()
    return user_ref


@require_admin_context
def user_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectAssociation).\
                filter_by(user_id=id).\
                delete()
        session.query(models.UserRoleAssociation).\
                filter_by(user_id=id).\
                delete()
        session.query(models.UserProjectRoleAssociation).\
                filter_by(user_id=id).\
                delete()
        user_ref = user_get(context, id, session=session)
        session.delete(user_ref)


def user_get_all(context):
    return model_query(context, models.User).all()


def user_get_roles(context, user_id):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        return [role.role for role in user_ref['roles']]


def user_get_roles_for_project(context, user_id, project_id):
    session = get_session()
    with session.begin():
        res = session.query(models.UserProjectRoleAssociation).\
                   filter_by(user_id=user_id).\
                   filter_by(project_id=project_id).\
                   all()
        return [association.role for association in res]


def user_remove_project_role(context, user_id, project_id, role):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectRoleAssociation).\
                filter_by(user_id=user_id).\
                filter_by(project_id=project_id).\
                filter_by(role=role).\
                delete()


def user_remove_role(context, user_id, role):
    session = get_session()
    with session.begin():
        res = session.query(models.UserRoleAssociation).\
                    filter_by(user_id=user_id).\
                    filter_by(role=role).\
                    all()
        for role in res:
            session.delete(role)


def user_add_role(context, user_id, role):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        models.UserRoleAssociation(user=user_ref, role=role).\
               save(session=session)


def user_add_project_role(context, user_id, project_id, role):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        project_ref = project_get(context, project_id, session=session)
        models.UserProjectRoleAssociation(user_id=user_ref['id'],
                                          project_id=project_ref['id'],
                                          role=role).save(session=session)


def user_update(context, user_id, values):
    session = get_session()
    with session.begin():
        user_ref = user_get(context, user_id, session=session)
        user_ref.update(values)
        user_ref.save(session=session)


###################


def project_create(context, values):
    project_ref = models.Project()
    project_ref.update(values)
    project_ref.save()
    return project_ref


def project_add_member(context, project_id, user_id):
    session = get_session()
    with session.begin():
        project_ref = project_get(context, project_id, session=session)
        user_ref = user_get(context, user_id, session=session)

        project_ref.members += [user_ref]
        project_ref.save(session=session)


def project_get(context, id, session=None):
    result = model_query(context, models.Project, session=session,
                         read_deleted="no").\
                     filter_by(id=id).\
                     options(joinedload_all('members')).\
                     first()

    if not result:
        raise exception.ProjectNotFound(project_id=id)

    return result


def project_get_all(context):
    return model_query(context, models.Project).\
                   options(joinedload_all('members')).\
                   all()


def project_get_by_user(context, user_id):
    user = model_query(context, models.User).\
                   filter_by(id=user_id).\
                   options(joinedload_all('projects')).\
                   first()

    if not user:
        raise exception.UserNotFound(user_id=user_id)

    return user.projects


def project_remove_member(context, project_id, user_id):
    session = get_session()
    project = project_get(context, project_id, session=session)
    user = user_get(context, user_id, session=session)

    if user in project.members:
        project.members.remove(user)
        project.save(session=session)


def project_update(context, project_id, values):
    session = get_session()
    with session.begin():
        project_ref = project_get(context, project_id, session=session)
        project_ref.update(values)
        project_ref.save(session=session)


def project_delete(context, id):
    session = get_session()
    with session.begin():
        session.query(models.UserProjectAssociation).\
                filter_by(project_id=id).\
                delete()
        session.query(models.UserProjectRoleAssociation).\
                filter_by(project_id=id).\
                delete()
        project_ref = project_get(context, id, session=session)
        session.delete(project_ref)


@require_context
def project_get_networks(context, project_id, associate=True):
    # NOTE(tr3buchet): as before this function will associate
    # a project with a network if it doesn't have one and
    # associate is true
    result = model_query(context, models.Network, read_deleted="no").\
                     filter_by(project_id=project_id).\
                     all()

    if not result:
        if not associate:
            return []

        return [network_associate(context, project_id)]

    return result


###################


@require_admin_context
def migration_create(context, values):
    migration = models.Migration()
    migration.update(values)
    migration.save()
    return migration


@require_admin_context
def migration_update(context, id, values):
    session = get_session()
    with session.begin():
        migration = migration_get(context, id, session=session)
        migration.update(values)
        migration.save(session=session)
        return migration


@require_admin_context
def migration_get(context, id, session=None):
    result = model_query(context, models.Migration, session=session,
                         read_deleted="yes").\
                     filter_by(id=id).\
                     first()

    if not result:
        raise exception.MigrationNotFound(migration_id=id)

    return result


@require_admin_context
def migration_get_by_instance_and_status(context, instance_uuid, status):
    result = model_query(context, models.Migration, read_deleted="yes").\
                     filter_by(instance_uuid=instance_uuid).\
                     filter_by(status=status).\
                     first()

    if not result:
        raise exception.MigrationNotFoundByStatus(instance_id=instance_uuid,
                                                  status=status)

    return result


@require_admin_context
def migration_get_all_unconfirmed(context, confirm_window, session=None):
    confirm_window = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=confirm_window)

    return model_query(context, models.Migration, session=session,
                       read_deleted="yes").\
            filter(models.Migration.updated_at <= confirm_window).\
            filter_by(status="FINISHED").\
            all()


##################


def console_pool_create(context, values):
    pool = models.ConsolePool()
    pool.update(values)
    pool.save()
    return pool


def console_pool_get(context, pool_id):
    result = model_query(context, models.ConsolePool, read_deleted="no").\
                     filter_by(id=pool_id).\
                     first()

    if not result:
        raise exception.ConsolePoolNotFound(pool_id=pool_id)

    return result


def console_pool_get_by_host_type(context, compute_host, host,
                                  console_type):

    result = model_query(context, models.ConsolePool, read_deleted="no").\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   filter_by(compute_host=compute_host).\
                   options(joinedload('consoles')).\
                   first()

    if not result:
        raise exception.ConsolePoolNotFoundForHostType(
                host=host, console_type=console_type,
                compute_host=compute_host)

    return result


def console_pool_get_all_by_host_type(context, host, console_type):
    return model_query(context, models.ConsolePool, read_deleted="no").\
                   filter_by(host=host).\
                   filter_by(console_type=console_type).\
                   options(joinedload('consoles')).\
                   all()


def console_create(context, values):
    console = models.Console()
    console.update(values)
    console.save()
    return console


def console_delete(context, console_id):
    session = get_session()
    with session.begin():
        # NOTE(mdragon): consoles are meant to be transient.
        session.query(models.Console).\
                filter_by(id=console_id).\
                delete()


def console_get_by_pool_instance(context, pool_id, instance_id):
    result = model_query(context, models.Console, read_deleted="yes").\
                   filter_by(pool_id=pool_id).\
                   filter_by(instance_id=instance_id).\
                   options(joinedload('pool')).\
                   first()

    if not result:
        raise exception.ConsoleNotFoundInPoolForInstance(
                pool_id=pool_id, instance_id=instance_id)

    return result


def console_get_all_by_instance(context, instance_id):
    return model_query(context, models.Console, read_deleted="yes").\
                   filter_by(instance_id=instance_id).\
                   all()


def console_get(context, console_id, instance_id=None):
    query = model_query(context, models.Console, read_deleted="yes").\
                    filter_by(id=console_id).\
                    options(joinedload('pool'))

    if instance_id is not None:
        query = query.filter_by(instance_id=instance_id)

    result = query.first()

    if not result:
        if instance_id:
            raise exception.ConsoleNotFoundForInstance(
                    console_id=console_id, instance_id=instance_id)
        else:
            raise exception.ConsoleNotFound(console_id=console_id)

    return result


##################


@require_admin_context
def instance_type_create(context, values):
    """Create a new instance type. In order to pass in extra specs,
    the values dict should contain a 'extra_specs' key/value pair:

    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}

    """
    session = get_session()
    with session.begin():
        try:
            instance_type_get_by_name(context, values['name'], session)
            raise exception.InstanceTypeExists(name=values['name'])
        except exception.InstanceTypeNotFoundByName:
            pass
        try:
            instance_type_get_by_flavor_id(context, values['flavorid'],
                                           session)
            raise exception.InstanceTypeExists(name=values['name'])
        except exception.FlavorNotFound:
            pass
        try:
            specs = values.get('extra_specs')
            specs_refs = []
            if specs:
                for k, v in specs.iteritems():
                    specs_ref = models.InstanceTypeExtraSpecs()
                    specs_ref['key'] = k
                    specs_ref['value'] = v
                    specs_refs.append(specs_ref)
            values['extra_specs'] = specs_refs
            instance_type_ref = models.InstanceTypes()
            instance_type_ref.update(values)
            instance_type_ref.save(session=session)
        except Exception, e:
            raise exception.DBError(e)
        return _dict_with_extra_specs(instance_type_ref)


def _dict_with_extra_specs(inst_type_query):
    """Takes an instance, volume, or instance type query returned
    by sqlalchemy and returns it as a dictionary, converting the
    extra_specs entry from a list of dicts:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]

    to a single dict:

    'extra_specs' : {'k1': 'v1'}

    """
    inst_type_dict = dict(inst_type_query)
    extra_specs = dict([(x['key'], x['value'])
                        for x in inst_type_query['extra_specs']])
    inst_type_dict['extra_specs'] = extra_specs
    return inst_type_dict


def _instance_type_get_query(context, session=None, read_deleted=None):
    return model_query(context, models.InstanceTypes, session=session,
                       read_deleted=read_deleted).\
                     options(joinedload('extra_specs'))


@require_context
def instance_type_get_all(context, inactive=False, filters=None):
    """
    Returns all instance types.
    """
    filters = filters or {}
    read_deleted = "yes" if inactive else "no"
    query = _instance_type_get_query(context, read_deleted=read_deleted)

    if 'min_memory_mb' in filters:
        query = query.filter(
                models.InstanceTypes.memory_mb >= filters['min_memory_mb'])
    if 'min_root_gb' in filters:
        query = query.filter(
                models.InstanceTypes.root_gb >= filters['min_root_gb'])

    inst_types = query.order_by("name").all()

    return [_dict_with_extra_specs(i) for i in inst_types]


@require_context
def instance_type_get(context, id, session=None):
    """Returns a dict describing specific instance_type"""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(id=id).\
                    first()

    if not result:
        raise exception.InstanceTypeNotFound(instance_type_id=id)

    return _dict_with_extra_specs(result)


@require_context
def instance_type_get_by_name(context, name, session=None):
    """Returns a dict describing specific instance_type"""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(name=name).\
                    first()

    if not result:
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)

    return _dict_with_extra_specs(result)


@require_context
def instance_type_get_by_flavor_id(context, flavor_id, session=None):
    """Returns a dict describing specific flavor_id"""
    result = _instance_type_get_query(context, session=session).\
                    filter_by(flavorid=flavor_id).\
                    first()

    if not result:
        raise exception.FlavorNotFound(flavor_id=flavor_id)

    return _dict_with_extra_specs(result)


@require_admin_context
def instance_type_destroy(context, name):
    """Marks specific instance_type as deleted"""
    session = get_session()
    with session.begin():
        instance_type_ref = instance_type_get_by_name(context, name,
                                                      session=session)
        instance_type_id = instance_type_ref['id']
        session.query(models.InstanceTypes).\
                filter_by(id=instance_type_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.InstanceTypeExtraSpecs).\
                filter_by(instance_type_id=instance_type_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


####################


@require_admin_context
def cell_create(context, values):
    cell = models.Cell()
    cell.update(values)
    cell.save()
    return cell


def _cell_get_by_id_query(context, cell_id, session=None):
    return model_query(context, models.Cell, session=session).\
                       filter_by(id=cell_id)


@require_admin_context
def cell_update(context, cell_id, values):
    cell = cell_get(context, cell_id)
    cell.update(values)
    cell.save()
    return cell


@require_admin_context
def cell_delete(context, cell_id):
    session = get_session()
    with session.begin():
        _cell_get_by_id_query(context, cell_id, session=session).\
                delete()


@require_admin_context
def cell_get(context, cell_id):
    result = _cell_get_by_id_query(context, cell_id).first()

    if not result:
        raise exception.CellNotFound(cell_id=cell_id)

    return result


@require_admin_context
def cell_get_all(context):
    return model_query(context, models.Cell, read_deleted="no").all()


####################


def _instance_metadata_get_query(context, instance_id, session=None):
    return model_query(context, models.InstanceMetadata, session=session,
                       read_deleted="no").\
                    filter_by(instance_id=instance_id)


@require_context
@require_instance_exists
def instance_metadata_get(context, instance_id):
    rows = _instance_metadata_get_query(context, instance_id).all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
@require_instance_exists
def instance_metadata_delete(context, instance_id, key):
    _instance_metadata_get_query(context, instance_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_instance_exists
def instance_metadata_get_item(context, instance_id, key, session=None):
    result = _instance_metadata_get_query(
                            context, instance_id, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.InstanceMetadataNotFound(metadata_key=key,
                                                 instance_id=instance_id)

    return result


@require_context
@require_instance_exists
def instance_metadata_update(context, instance_id, metadata, delete):
    session = get_session()

    # Set existing metadata to deleted if delete argument is True
    if delete:
        original_metadata = instance_metadata_get(context, instance_id)
        for meta_key, meta_value in original_metadata.iteritems():
            if meta_key not in metadata:
                meta_ref = instance_metadata_get_item(context, instance_id,
                                                      meta_key, session)
                meta_ref.update({'deleted': True})
                meta_ref.save(session=session)

    meta_ref = None

    # Now update all existing items with new values, or create new meta objects
    for meta_key, meta_value in metadata.iteritems():

        # update the value whether it exists or not
        item = {"value": meta_value}

        try:
            meta_ref = instance_metadata_get_item(context, instance_id,
                                                  meta_key, session)
        except exception.InstanceMetadataNotFound, e:
            meta_ref = models.InstanceMetadata()
            item.update({"key": meta_key, "instance_id": instance_id})

        meta_ref.update(item)
        meta_ref.save(session=session)

    return metadata


####################


@require_admin_context
def agent_build_create(context, values):
    agent_build_ref = models.AgentBuild()
    agent_build_ref.update(values)
    agent_build_ref.save()
    return agent_build_ref


@require_admin_context
def agent_build_get_by_triple(context, hypervisor, os, architecture,
                              session=None):
    return model_query(context, models.AgentBuild, session=session,
                       read_deleted="no").\
                   filter_by(hypervisor=hypervisor).\
                   filter_by(os=os).\
                   filter_by(architecture=architecture).\
                   first()


@require_admin_context
def agent_build_get_all(context):
    return model_query(context, models.AgentBuild, read_deleted="no").\
                   all()


@require_admin_context
def agent_build_destroy(context, agent_build_id):
    session = get_session()
    with session.begin():
        model_query(context, models.AgentBuild, session=session,
                    read_deleted="yes").\
                filter_by(id=agent_build_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


@require_admin_context
def agent_build_update(context, agent_build_id, values):
    session = get_session()
    with session.begin():
        agent_build_ref = model_query(context, models.AgentBuild,
                                      session=session, read_deleted="yes").\
                   filter_by(id=agent_build_id).\
                   first()

        agent_build_ref.update(values)
        agent_build_ref.save(session=session)


####################

@require_context
def bw_usage_get_by_macs(context, macs, start_period):
    return model_query(context, models.BandwidthUsage, read_deleted="yes").\
                   filter(models.BandwidthUsage.mac.in_(macs)).\
                   filter_by(start_period=start_period).\
                   all()


@require_context
def bw_usage_update(context,
                    mac,
                    start_period,
                    bw_in, bw_out,
                    session=None):
    if not session:
        session = get_session()

    with session.begin():
        bwusage = model_query(context, models.BandwidthUsage,
                              session=session, read_deleted="yes").\
                      filter_by(start_period=start_period).\
                      filter_by(mac=mac).\
                      first()

        if not bwusage:
            bwusage = models.BandwidthUsage()
            bwusage.start_period = start_period
            bwusage.mac = mac

        bwusage.last_refreshed = utils.utcnow()
        bwusage.bw_in = bw_in
        bwusage.bw_out = bw_out
        bwusage.save(session=session)


####################


def _instance_type_extra_specs_get_query(context, instance_type_id,
                                         session=None):
    return model_query(context, models.InstanceTypeExtraSpecs,
                       session=session, read_deleted="no").\
                    filter_by(instance_type_id=instance_type_id)


@require_context
def instance_type_extra_specs_get(context, instance_type_id):
    rows = _instance_type_extra_specs_get_query(
                            context, instance_type_id).\
                    all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
def instance_type_extra_specs_delete(context, instance_type_id, key):
    _instance_type_extra_specs_get_query(
                            context, instance_type_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def instance_type_extra_specs_get_item(context, instance_type_id, key,
                                       session=None):
    result = _instance_type_extra_specs_get_query(
                            context, instance_type_id, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.InstanceTypeExtraSpecsNotFound(
                extra_specs_key=key, instance_type_id=instance_type_id)

    return result


@require_context
def instance_type_extra_specs_update_or_create(context, instance_type_id,
                                               specs):
    session = get_session()
    spec_ref = None
    for key, value in specs.iteritems():
        try:
            spec_ref = instance_type_extra_specs_get_item(
                context, instance_type_id, key, session)
        except exception.InstanceTypeExtraSpecsNotFound, e:
            spec_ref = models.InstanceTypeExtraSpecs()
        spec_ref.update({"key": key, "value": value,
                         "instance_type_id": instance_type_id,
                         "deleted": 0})
        spec_ref.save(session=session)
    return specs


##################


@require_admin_context
def volume_type_create(context, values):
    """Create a new instance type. In order to pass in extra specs,
    the values dict should contain a 'extra_specs' key/value pair:

    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}

    """
    session = get_session()
    with session.begin():
        try:
            volume_type_get_by_name(context, values['name'], session)
            raise exception.VolumeTypeExists(name=values['name'])
        except exception.VolumeTypeNotFoundByName:
            pass
        try:
            specs = values.get('extra_specs')

            values['extra_specs'] = _metadata_refs(values.get('extra_specs'),
                                                   models.VolumeTypeExtraSpecs)
            volume_type_ref = models.VolumeTypes()
            volume_type_ref.update(values)
            volume_type_ref.save()
        except Exception, e:
            raise exception.DBError(e)
        return volume_type_ref


@require_context
def volume_type_get_all(context, inactive=False, filters=None):
    """
    Returns a dict describing all volume_types with name as key.
    """
    filters = filters or {}

    read_deleted = "yes" if inactive else "no"
    rows = model_query(context, models.VolumeTypes,
                       read_deleted=read_deleted).\
                        options(joinedload('extra_specs')).\
                        order_by("name").\
                        all()

    # TODO(sirp): this patern of converting rows to a result with extra_specs
    # is repeated quite a bit, might be worth creating a method for it
    result = {}
    for row in rows:
        result[row['name']] = _dict_with_extra_specs(row)

    return result


@require_context
def volume_type_get(context, id, session=None):
    """Returns a dict describing specific volume_type"""
    result = model_query(context, models.VolumeTypes, session=session).\
                    options(joinedload('extra_specs')).\
                    filter_by(id=id).\
                    first()

    if not result:
        raise exception.VolumeTypeNotFound(volume_type=id)

    return _dict_with_extra_specs(result)


@require_context
def volume_type_get_by_name(context, name, session=None):
    """Returns a dict describing specific volume_type"""
    result = model_query(context, models.VolumeTypes, session=session).\
                    options(joinedload('extra_specs')).\
                    filter_by(name=name).\
                    first()

    if not result:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    else:
        return _dict_with_extra_specs(result)


@require_admin_context
def volume_type_destroy(context, name):
    session = get_session()
    with session.begin():
        volume_type_ref = volume_type_get_by_name(context, name,
                                                  session=session)
        volume_type_id = volume_type_ref['id']
        session.query(models.VolumeTypes).\
                filter_by(id=volume_type_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})
        session.query(models.VolumeTypeExtraSpecs).\
                filter_by(volume_type_id=volume_type_id).\
                update({'deleted': True,
                        'deleted_at': utils.utcnow(),
                        'updated_at': literal_column('updated_at')})


####################


def _volume_type_extra_specs_query(context, volume_type_id, session=None):
    return model_query(context, models.VolumeTypeExtraSpecs, session=session,
                       read_deleted="no").\
                    filter_by(volume_type_id=volume_type_id)


@require_context
def volume_type_extra_specs_get(context, volume_type_id):
    rows = _volume_type_extra_specs_query(context, volume_type_id).\
                    all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
def volume_type_extra_specs_delete(context, volume_type_id, key):
    _volume_type_extra_specs_query(context, volume_type_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': utils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def volume_type_extra_specs_get_item(context, volume_type_id, key,
                                     session=None):
    result = _volume_type_extra_specs_query(
                                    context, volume_type_id, session=session).\
                    filter_by(key=key).\
                    first()

    if not result:
        raise exception.VolumeTypeExtraSpecsNotFound(
                   extra_specs_key=key, volume_type_id=volume_type_id)

    return result


@require_context
def volume_type_extra_specs_update_or_create(context, volume_type_id,
                                             specs):
    session = get_session()
    spec_ref = None
    for key, value in specs.iteritems():
        try:
            spec_ref = volume_type_extra_specs_get_item(
                context, volume_type_id, key, session)
        except exception.VolumeTypeExtraSpecsNotFound, e:
            spec_ref = models.VolumeTypeExtraSpecs()
        spec_ref.update({"key": key, "value": value,
                         "volume_type_id": volume_type_id,
                         "deleted": 0})
        spec_ref.save(session=session)
    return specs


####################


def s3_image_get(context, image_id):
    """Find local s3 image represented by the provided id"""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(id=image_id).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_id)

    return result


def s3_image_get_by_uuid(context, image_uuid):
    """Find local s3 image represented by the provided uuid"""
    result = model_query(context, models.S3Image, read_deleted="yes").\
                 filter_by(uuid=image_uuid).\
                 first()

    if not result:
        raise exception.ImageNotFound(image_id=image_uuid)

    return result


def s3_image_create(context, image_uuid):
    """Create local s3 image represented by provided uuid"""
    try:
        s3_image_ref = models.S3Image()
        s3_image_ref.update({'uuid': image_uuid})
        s3_image_ref.save()
    except Exception, e:
        raise exception.DBError(e)

    return s3_image_ref


####################


@require_admin_context
def sm_backend_conf_create(context, values):
    backend_conf = models.SMBackendConf()
    backend_conf.update(values)
    backend_conf.save()
    return backend_conf


@require_admin_context
def sm_backend_conf_update(context, sm_backend_id, values):
    session = get_session()
    with session.begin():
        backend_conf = model_query(context, models.SMBackendConf,
                                   session=session,
                                   read_deleted="yes").\
                           filter_by(id=sm_backend_id).\
                           first()

        if not backend_conf:
            raise exception.NotFound(
                _("No backend config with id %(sm_backend_id)s") % locals())

        backend_conf.update(values)
        backend_conf.save(session=session)
    return backend_conf


@require_admin_context
def sm_backend_conf_delete(context, sm_backend_id):
    # FIXME(sirp): for consistency, shouldn't this just mark as deleted with
    # `purge` actually deleting the record?
    session = get_session()
    with session.begin():
        model_query(context, models.SMBackendConf, session=session,
                    read_deleted="yes").\
                filter_by(id=sm_backend_id).\
                delete()


@require_admin_context
def sm_backend_conf_get(context, sm_backend_id):
    result = model_query(context, models.SMBackendConf, read_deleted="yes").\
                     filter_by(id=sm_backend_id).\
                     first()

    if not result:
        raise exception.NotFound(_("No backend config with id "
                                   "%(sm_backend_id)s") % locals())

    return result


@require_admin_context
def sm_backend_conf_get_by_sr(context, sr_uuid):
    session = get_session()
    return model_query(context, models.SMBackendConf, read_deleted="yes").\
                    filter_by(sr_uuid=sr_uuid).\
                    first()


@require_admin_context
def sm_backend_conf_get_all(context):
    return model_query(context, models.SMBackendConf, read_deleted="yes").\
                    all()


####################


def _sm_flavor_get_query(context, sm_flavor_label, session=None):
    return model_query(context, models.SMFlavors, session=session,
                       read_deleted="yes").\
                        filter_by(label=sm_flavor_label)


@require_admin_context
def sm_flavor_create(context, values):
    sm_flavor = models.SMFlavors()
    sm_flavor.update(values)
    sm_flavor.save()
    return sm_flavor


@require_admin_context
def sm_flavor_update(context, sm_flavor_label, values):
    sm_flavor = sm_flavor_get(context, sm_flavor_label)
    sm_flavor.update(values)
    sm_flavor.save()
    return sm_flavor


@require_admin_context
def sm_flavor_delete(context, sm_flavor_label):
    session = get_session()
    with session.begin():
        _sm_flavor_get_query(context, sm_flavor_label).delete()


@require_admin_context
def sm_flavor_get(context, sm_flavor_label):
    result = _sm_flavor_get_query(context, sm_flavor_label).first()

    if not result:
        raise exception.NotFound(
                _("No sm_flavor called %(sm_flavor)s") % locals())

    return result


@require_admin_context
def sm_flavor_get_all(context):
    return model_query(context, models.SMFlavors, read_deleted="yes").all()


###############################


def _sm_volume_get_query(context, volume_id, session=None):
    return model_query(context, models.SMVolume, session=session,
                       read_deleted="yes").\
                        filter_by(id=volume_id)


def sm_volume_create(context, values):
    sm_volume = models.SMVolume()
    sm_volume.update(values)
    sm_volume.save()
    return sm_volume


def sm_volume_update(context, volume_id, values):
    sm_volume = sm_volume_get(context, volume_id)
    sm_volume.update(values)
    sm_volume.save()
    return sm_volume


def sm_volume_delete(context, volume_id):
    session = get_session()
    with session.begin():
        _sm_volume_get_query(context, volume_id, session=session).delete()


def sm_volume_get(context, volume_id):
    result = _sm_volume_get_query(context, volume_id).first()

    if not result:
        raise exception.NotFound(
                _("No sm_volume with id %(volume_id)s") % locals())

    return result


def sm_volume_get_all(context):
    return model_query(context, models.SMVolume, read_deleted="yes").all()


################


def _aggregate_get_query(context, model_class, id_field, id,
                         session=None, read_deleted='yes'):
    return model_query(context, model_class, session=session,
                       read_deleted=read_deleted).filter(id_field == id)


@require_admin_context
def aggregate_create(context, values, metadata=None):
    session = get_session()
    aggregate = _aggregate_get_query(context,
                                     models.Aggregate,
                                     models.Aggregate.name,
                                     values['name'],
                                     session=session,
                                     read_deleted='yes').first()
    values.setdefault('operational_state', aggregate_states.CREATED)
    if not aggregate:
        aggregate = models.Aggregate()
        aggregate.update(values)
        aggregate.save(session=session)
    elif aggregate.deleted:
        values['deleted'] = False
        values['deleted_at'] = None
        aggregate.update(values)
        aggregate.save(session=session)
    else:
        raise exception.AggregateNameExists(aggregate_name=values['name'])
    if metadata:
        aggregate_metadata_add(context, aggregate.id, metadata)
    return aggregate


@require_admin_context
def aggregate_get(context, aggregate_id, read_deleted='no'):
    aggregate = _aggregate_get_query(context,
                                     models.Aggregate,
                                     models.Aggregate.id, aggregate_id,
                                     read_deleted=read_deleted).first()

    if not aggregate:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)

    return aggregate


@require_admin_context
def aggregate_get_by_host(context, host, read_deleted='no'):
    aggregate_host = _aggregate_get_query(context,
                                          models.AggregateHost,
                                          models.AggregateHost.host,
                                          host,
                                          read_deleted='no').first()

    if not aggregate_host:
        raise exception.AggregateHostNotFound(host=host)

    return aggregate_get(context, aggregate_host.aggregate_id, read_deleted)


@require_admin_context
def aggregate_update(context, aggregate_id, values):
    session = get_session()
    aggregate = _aggregate_get_query(context,
                                     models.Aggregate,
                                     models.Aggregate.id, aggregate_id,
                                     session=session,
                                     read_deleted='no').first()
    if aggregate:
        metadata = values.get('metadata')
        if metadata is not None:
            aggregate_metadata_add(context,
                                   aggregate_id,
                                   values.pop('metadata'),
                                   set_delete=True)
        with session.begin():
            aggregate.update(values)
            aggregate.save(session=session)
        values['metadata'] = metadata
        return aggregate
    else:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)


@require_admin_context
def aggregate_delete(context, aggregate_id):
    query = _aggregate_get_query(context,
                                 models.Aggregate,
                                 models.Aggregate.id, aggregate_id,
                                 read_deleted='no')
    if query.first():
        query.update({'deleted': True,
                      'deleted_at': utils.utcnow(),
                      'operational_state': aggregate_states.DISMISSED,
                      'updated_at': literal_column('updated_at')})
    else:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)


@require_admin_context
def aggregate_get_all(context, read_deleted='yes'):
    return model_query(context,
                       models.Aggregate,
                       read_deleted=read_deleted).all()


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_get(context, aggregate_id, read_deleted='no'):
    rows = model_query(context,
                       models.AggregateMetadata,
                       read_deleted=read_deleted).\
                       filter_by(aggregate_id=aggregate_id).all()

    return dict([(r['key'], r['value']) for r in rows])


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_delete(context, aggregate_id, key):
    query = _aggregate_get_query(context,
                                 models.AggregateMetadata,
                                 models.AggregateMetadata.aggregate_id,
                                 aggregate_id, read_deleted='no').\
                                 filter_by(key=key)
    if query.first():
        query.update({'deleted': True,
                      'deleted_at': utils.utcnow(),
                      'updated_at': literal_column('updated_at')})
    else:
        raise exception.AggregateMetadataNotFound(aggregate_id=aggregate_id,
                                                  metadata_key=key)


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_get_item(context, aggregate_id, key,
                                session=None, read_deleted='yes'):
    result = _aggregate_get_query(context,
                                  models.AggregateMetadata,
                                  models.AggregateMetadata.aggregate_id,
                                  aggregate_id, session=session,
                                  read_deleted=read_deleted).\
                                  filter_by(key=key).first()

    if not result:
        raise exception.AggregateMetadataNotFound(metadata_key=key,
                                                 aggregate_id=aggregate_id)

    return result


@require_admin_context
@require_aggregate_exists
def aggregate_metadata_add(context, aggregate_id, metadata, set_delete=False):
    session = get_session()

    if set_delete:
        original_metadata = aggregate_metadata_get(context, aggregate_id)
        for meta_key, meta_value in original_metadata.iteritems():
            if meta_key not in metadata:
                meta_ref = aggregate_metadata_get_item(context, aggregate_id,
                                                      meta_key, session)
                meta_ref.update({'deleted': True})
                meta_ref.save(session=session)

    meta_ref = None

    for meta_key, meta_value in metadata.iteritems():
        item = {"value": meta_value}
        try:
            meta_ref = aggregate_metadata_get_item(context, aggregate_id,
                                                  meta_key, session)
            if meta_ref.deleted:
                item.update({'deleted': False, 'deleted_at': None})
        except exception.AggregateMetadataNotFound:
            meta_ref = models.AggregateMetadata()
            item.update({"key": meta_key, "aggregate_id": aggregate_id})

        meta_ref.update(item)
        meta_ref.save(session=session)

    return metadata


@require_admin_context
@require_aggregate_exists
def aggregate_host_get_all(context, aggregate_id, read_deleted='yes'):
    rows = model_query(context,
                       models.AggregateHost,
                       read_deleted=read_deleted).\
                       filter_by(aggregate_id=aggregate_id).all()

    return [r.host for r in rows]


@require_admin_context
@require_aggregate_exists
def aggregate_host_delete(context, aggregate_id, host):
    query = _aggregate_get_query(context,
                                 models.AggregateHost,
                                 models.AggregateHost.aggregate_id,
                                 aggregate_id,
                                 read_deleted='no').filter_by(host=host)
    if query.first():
        query.update({'deleted': True,
                      'deleted_at': utils.utcnow(),
                      'updated_at': literal_column('updated_at')})
    else:
        raise exception.AggregateHostNotFound(aggregate_id=aggregate_id,
                                              host=host)


@require_admin_context
@require_aggregate_exists
def aggregate_host_add(context, aggregate_id, host):
    session = get_session()
    host_ref = _aggregate_get_query(context,
                                    models.AggregateHost,
                                    models.AggregateHost.aggregate_id,
                                    aggregate_id,
                                    session=session,
                                    read_deleted='yes').\
                                    filter_by(host=host).first()
    if not host_ref:
        try:
            host_ref = models.AggregateHost()
            values = {"host": host, "aggregate_id": aggregate_id, }
            host_ref.update(values)
            host_ref.save(session=session)
        except exception.DBError:
            raise exception.AggregateHostConflict(host=host)
    elif host_ref.deleted:
        host_ref.update({'deleted': False, 'deleted_at': None})
        host_ref.save(session=session)
    else:
        raise exception.AggregateHostExists(host=host,
                                            aggregate_id=aggregate_id)
    return host_ref


################


def instance_fault_create(context, values):
    """Create a new InstanceFault."""
    fault_ref = models.InstanceFault()
    fault_ref.update(values)
    fault_ref.save()
    return dict(fault_ref.iteritems())


def instance_fault_get_by_instance_uuids(context, instance_uuids):
    """Get all instance faults for the provided instance_uuids."""
    rows = model_query(context, models.InstanceFault, read_deleted='no').\
                       filter(models.InstanceFault.instance_uuid.in_(
                           instance_uuids)).\
                       order_by(desc("created_at")).\
                       all()

    output = {}
    for instance_uuid in instance_uuids:
        output[instance_uuid] = []

    for row in rows:
        data = dict(row.iteritems())
        output[row['instance_uuid']].append(data)

    return output
