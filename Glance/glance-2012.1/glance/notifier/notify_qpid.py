# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import json
import logging

import qpid.messaging

from glance.common import cfg
from glance.notifier import strategy


logger = logging.getLogger('glance.notifier.notify_qpid')


qpid_opts = [
    cfg.StrOpt('qpid_notification_exchange',
               default='glance',
               help='Qpid exchange for notifications'),
    cfg.StrOpt('qpid_notification_topic',
               default='glance_notifications',
               help='Qpid topic for notifications'),
    cfg.StrOpt('qpid_hostname',
               default='localhost',
               help='Qpid broker hostname'),
    cfg.StrOpt('qpid_port',
               default='5672',
               help='Qpid broker port'),
    cfg.StrOpt('qpid_username',
               default='',
               help='Username for qpid connection'),
    cfg.StrOpt('qpid_password',
               default='',
               help='Password for qpid connection'),
    cfg.StrOpt('qpid_sasl_mechanisms',
               default='',
               help='Space separated list of SASL mechanisms to use for auth'),
    cfg.IntOpt('qpid_reconnect_timeout',
               default=0,
               help='Reconnection timeout in seconds'),
    cfg.IntOpt('qpid_reconnect_limit',
               default=0,
               help='Max reconnections before giving up'),
    cfg.IntOpt('qpid_reconnect_interval_min',
               default=0,
               help='Minimum seconds between reconnection attempts'),
    cfg.IntOpt('qpid_reconnect_interval_max',
               default=0,
               help='Maximum seconds between reconnection attempts'),
    cfg.IntOpt('qpid_reconnect_interval',
               default=0,
               help='Equivalent to setting max and min to the same value'),
    cfg.IntOpt('qpid_heartbeat',
               default=5,
               help='Seconds between connection keepalive heartbeats'),
    cfg.StrOpt('qpid_protocol',
               default='tcp',
               help="Transport to use, either 'tcp' or 'ssl'"),
    cfg.BoolOpt('qpid_tcp_nodelay',
                default=True,
                help='Disable Nagle algorithm'),
    ]


class QpidStrategy(strategy.Strategy):
    """A notifier that puts a message on a queue when called."""

    def __init__(self, conf):
        """Initialize the Qpid notification strategy."""
        self.conf = conf
        self.conf.register_opts(qpid_opts)

        self.broker = self.conf.qpid_hostname + ":" + self.conf.qpid_port
        self.connection = qpid.messaging.Connection(self.broker)
        self.connection.username = self.conf.qpid_username
        self.connection.password = self.conf.qpid_password
        self.connection.sasl_mechanisms = self.conf.qpid_sasl_mechanisms
        # Hard code this option as enabled so that reconnect logic isn't needed
        # in this file at all.
        self.connection.reconnect = True
        if self.conf.qpid_reconnect_timeout:
            self.connection.reconnect_timeout = (
                                            self.conf.qpid_reconnect_timeout)
        if self.conf.qpid_reconnect_limit:
            self.connection.reconnect_limit = self.conf.qpid_reconnect_limit
        if self.conf.qpid_reconnect_interval_max:
            self.connection.reconnect_interval_max = (
                                        self.conf.qpid_reconnect_interval_max)
        if self.conf.qpid_reconnect_interval_min:
            self.connection.reconnect_interval_min = (
                                        self.conf.qpid_reconnect_interval_min)
        if self.conf.qpid_reconnect_interval:
            self.connection.reconnect_interval = (
                                        self.conf.qpid_reconnect_interval)
        self.connection.hearbeat = self.conf.qpid_heartbeat
        self.connection.protocol = self.conf.qpid_protocol
        self.connection.tcp_nodelay = self.conf.qpid_tcp_nodelay
        self.connection.open()
        self.session = self.connection.session()
        logger.info(_('Connected to AMQP server on %s') % self.broker)

        self.sender_info = self._sender("info")
        self.sender_warn = self._sender("warn")
        self.sender_error = self._sender("error")

    def _sender(self, priority):
        addr_opts = {
            "create": "always",
            "node": {
                "type": "topic",
                "x-declare": {
                    "durable": False,
                    # auto-delete isn't implemented for exchanges in qpid,
                    # but put in here anyway
                    "auto-delete": True,
                },
            },
        }
        topic = "%s.%s" % (self.conf.qpid_notification_topic, priority)
        address = "%s/%s ; %s" % (self.conf.qpid_notification_exchange, topic,
                                  json.dumps(addr_opts))
        return self.session.sender(address)

    def warn(self, msg):
        qpid_msg = qpid.messaging.Message(content=msg,
                                          content_type='application/json')
        self.sender_warn.send(qpid_msg)

    def info(self, msg):
        qpid_msg = qpid.messaging.Message(content=msg,
                                          content_type='application/json')
        self.sender_info.send(qpid_msg)

    def error(self, msg):
        qpid_msg = qpid.messaging.Message(content=msg,
                                          content_type='application/json')
        self.sender_error.send(qpid_msg)
