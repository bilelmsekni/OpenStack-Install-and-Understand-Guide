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
Volume manager manages creating, attaching, detaching, and persistent storage.

Persistant storage volumes keep their state independent of instances.  You can
attach to an instance, terminate the instance, spawn a new instance (even
one from a different image) and re-attach the volume with the same data
intact.

**Related Flags**

:volume_topic:  What :mod:`rpc` topic to listen to (default: `volume`).
:volume_manager:  The module name of a class derived from
                  :class:`manager.Manager` (default:
                  :class:`nova.volume.manager.Manager`).
:storage_availability_zone:  Defaults to `nova`.
:volume_driver:  Used by :class:`Manager`.  Defaults to
                 :class:`nova.volume.driver.ISCSIDriver`.
:volume_group:  Name of the group that will contain exported volumes (default:
                `nova-volumes`)
:num_shell_tries:  Number of times to attempt to run commands (default: 3)

"""

from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova.openstack.common import cfg
from nova import rpc
from nova import utils
from nova.volume import volume_types


LOG = logging.getLogger(__name__)

volume_manager_opts = [
    cfg.StrOpt('storage_availability_zone',
               default='nova',
               help='availability zone of this service'),
    cfg.StrOpt('volume_driver',
               default='nova.volume.driver.ISCSIDriver',
               help='Driver to use for volume creation'),
    cfg.BoolOpt('use_local_volumes',
                default=True,
                help='if True, will not discover local volumes'),
    cfg.BoolOpt('volume_force_update_capabilities',
                default=False,
                help='if True will force update capabilities on each check'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_manager_opts)


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""
    def __init__(self, volume_driver=None, *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        if not volume_driver:
            volume_driver = FLAGS.volume_driver
        self.driver = utils.import_object(volume_driver)
        super(VolumeManager, self).__init__(service_name='volume',
                                                    *args, **kwargs)
        # NOTE(vish): Implementation specific db handling is done
        #             by the driver.
        self.driver.db = self.db
        self._last_volume_stats = []

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service."""

        ctxt = context.get_admin_context()
        self.driver.do_setup(ctxt)
        self.driver.check_for_setup_error()

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        LOG.debug(_("Re-exporting %s volumes"), len(volumes))
        for volume in volumes:
            if volume['status'] in ['available', 'in-use']:
                self.driver.ensure_export(ctxt, volume)
            else:
                LOG.info(_("volume %s: skipping export"), volume['name'])

    def create_volume(self, context, volume_id, snapshot_id=None):
        """Creates and exports the volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        LOG.info(_("volume %s: creating"), volume_ref['name'])

        self.db.volume_update(context,
                              volume_id,
                              {'host': self.host})
        # NOTE(vish): so we don't have to get volume from db again
        #             before passing it to the driver.
        volume_ref['host'] = self.host

        try:
            vol_name = volume_ref['name']
            vol_size = volume_ref['size']
            LOG.debug(_("volume %(vol_name)s: creating lv of"
                    " size %(vol_size)sG") % locals())
            if snapshot_id is None:
                model_update = self.driver.create_volume(volume_ref)
            else:
                snapshot_ref = self.db.snapshot_get(context, snapshot_id)
                model_update = self.driver.create_volume_from_snapshot(
                    volume_ref,
                    snapshot_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)

            LOG.debug(_("volume %s: creating export"), volume_ref['name'])
            model_update = self.driver.create_export(context, volume_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'], {'status': 'error'})

        now = utils.utcnow()
        self.db.volume_update(context,
                              volume_ref['id'], {'status': 'available',
                                                 'launched_at': now})
        LOG.debug(_("volume %s: created successfully"), volume_ref['name'])
        self._reset_stats()
        return volume_id

    def delete_volume(self, context, volume_id):
        """Deletes and unexports volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['attach_status'] == "attached":
            raise exception.Error(_("Volume is still attached"))
        if volume_ref['host'] != self.host:
            raise exception.Error(_("Volume is not local to this node"))

        self._reset_stats()
        try:
            LOG.debug(_("volume %s: removing export"), volume_ref['name'])
            self.driver.remove_export(context, volume_ref)
            LOG.debug(_("volume %s: deleting"), volume_ref['name'])
            self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy, e:
            LOG.debug(_("volume %s: volume is busy"), volume_ref['name'])
            self.driver.ensure_export(context, volume_ref)
            self.db.volume_update(context, volume_ref['id'],
                                  {'status': 'available'})
            return True
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'],
                                      {'status': 'error_deleting'})

        self.db.volume_destroy(context, volume_id)
        LOG.debug(_("volume %s: deleted successfully"), volume_ref['name'])
        return True

    def create_snapshot(self, context, volume_id, snapshot_id):
        """Creates and exports the snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        LOG.info(_("snapshot %s: creating"), snapshot_ref['name'])

        try:
            snap_name = snapshot_ref['name']
            LOG.debug(_("snapshot %(snap_name)s: creating") % locals())
            model_update = self.driver.create_snapshot(snapshot_ref)
            if model_update:
                self.db.snapshot_update(context, snapshot_ref['id'],
                                        model_update)

        except Exception:
            with utils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error'})

        self.db.snapshot_update(context,
                                snapshot_ref['id'], {'status': 'available',
                                                     'progress': '100%'})
        LOG.debug(_("snapshot %s: created successfully"), snapshot_ref['name'])
        return snapshot_id

    def delete_snapshot(self, context, snapshot_id):
        """Deletes and unexports snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)

        try:
            LOG.debug(_("snapshot %s: deleting"), snapshot_ref['name'])
            self.driver.delete_snapshot(snapshot_ref)
        except exception.SnapshotIsBusy:
            LOG.debug(_("snapshot %s: snapshot is busy"), snapshot_ref['name'])
            self.db.snapshot_update(context,
                                    snapshot_ref['id'],
                                    {'status': 'available'})
            return True
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error_deleting'})

        self.db.snapshot_destroy(context, snapshot_id)
        LOG.debug(_("snapshot %s: deleted successfully"), snapshot_ref['name'])
        return True

    def attach_volume(self, context, volume_id, instance_id, mountpoint):
        """Updates db to show volume is attached"""
        # TODO(vish): refactor this into a more general "reserve"
        self.db.volume_attached(context,
                                volume_id,
                                instance_id,
                                mountpoint)

    def detach_volume(self, context, volume_id):
        """Updates db to show volume is detached"""
        # TODO(vish): refactor this into a more general "unreserve"
        self.db.volume_detached(context, volume_id)

    def initialize_connection(self, context, volume_id, connector):
        """Prepare volume for connection from host represented by connector.

        This method calls the driver initialize_connection and returns
        it to the caller.  The connector parameter is a dictionary with
        information about the host that will connect to the volume in the
        following format::

            {
                'ip': ip,
                'initiator': initiator,
            }

        ip: the ip address of the connecting machine

        initiator: the iscsi initiator name of the connecting machine.
        This can be None if the connecting machine does not support iscsi
        connections.

        driver is responsible for doing any necessary security setup and
        returning a connection_info dictionary in the following format::

            {
                'driver_volume_type': driver_volume_type,
                'data': data,
            }

        driver_volume_type: a string to identify the type of volume.  This
                           can be used by the calling code to determine the
                           strategy for connecting to the volume. This could
                           be 'iscsi', 'rbd', 'sheepdog', etc.

        data: this is the data that the calling code will use to connect
              to the volume. Keep in mind that this will be serialized to
              json in various places, so it should not contain any non-json
              data types.
        """
        volume_ref = self.db.volume_get(context, volume_id)
        return self.driver.initialize_connection(volume_ref, connector)

    def terminate_connection(self, context, volume_id, connector):
        """Cleanup connection from host represented by connector.

        The format of connector is the same as for initialize_connection.
        """
        volume_ref = self.db.volume_get(context, volume_id)
        self.driver.terminate_connection(volume_ref, connector)

    def check_for_export(self, context, instance_id):
        """Make sure whether volume is exported."""
        instance_ref = self.db.instance_get(context, instance_id)
        for volume in instance_ref['volumes']:
            self.driver.check_for_export(context, volume['id'])

    def _volume_stats_changed(self, stat1, stat2):
        if FLAGS.volume_force_update_capabilities:
            return True
        if len(stat1) != len(stat2):
            return True
        for (k, v) in stat1.iteritems():
            if (k, v) not in stat2.iteritems():
                return True
        return False

    @manager.periodic_task
    def _report_driver_status(self, context):
        volume_stats = self.driver.get_volume_stats(refresh=True)
        if volume_stats:
            LOG.info(_("Checking volume capabilities"))

            if self._volume_stats_changed(self._last_volume_stats,
                                          volume_stats):
                LOG.info(_("New capabilities found: %s"), volume_stats)
                self._last_volume_stats = volume_stats

                # This will grab info about the host and queue it
                # to be sent to the Schedulers.
                self.update_service_capabilities(self._last_volume_stats)
            else:
                # avoid repeating fanouts
                self.update_service_capabilities(None)

    def _reset_stats(self):
        LOG.info(_("Clear capabilities"))
        self._last_volume_stats = []

    def notification(self, context, event):
        LOG.info(_("Notification {%s} received"), event)
        self._reset_stats()
