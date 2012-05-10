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

import nova
from nova import flags
from nova import log
import nova.notifier.no_op_notifier
from nova.notifier import api as notifier_api
from nova import test


class NotifierTestCase(test.TestCase):
    """Test case for notifications"""
    def setUp(self):
        super(NotifierTestCase, self).setUp()
        self.flags(notification_driver='nova.notifier.no_op_notifier')

    def test_send_notification(self):
        self.notify_called = False

        def mock_notify(cls, *args):
            self.notify_called = True

        self.stubs.Set(nova.notifier.no_op_notifier, 'notify',
                mock_notify)

        notifier_api.notify('publisher_id', 'event_type',
                nova.notifier.api.WARN, dict(a=3))
        self.assertEqual(self.notify_called, True)

    def test_verify_message_format(self):
        """A test to ensure changing the message format is prohibitively
        annoying"""

        def message_assert(message):
            fields = [('publisher_id', 'publisher_id'),
                      ('event_type', 'event_type'),
                      ('priority', 'WARN'),
                      ('payload', dict(a=3))]
            for k, v in fields:
                self.assertEqual(message[k], v)
            self.assertTrue(len(message['message_id']) > 0)
            self.assertTrue(len(message['timestamp']) > 0)

        self.stubs.Set(nova.notifier.no_op_notifier, 'notify',
                message_assert)
        notifier_api.notify('publisher_id', 'event_type',
                nova.notifier.api.WARN, dict(a=3))

    def test_send_rabbit_notification(self):
        self.stubs.Set(nova.flags.FLAGS, 'notification_driver',
                'nova.notifier.rabbit_notifier')
        self.mock_notify = False

        def mock_notify(cls, *args):
            self.mock_notify = True

        self.stubs.Set(nova.rpc, 'notify', mock_notify)
        notifier_api.notify('publisher_id', 'event_type',
                nova.notifier.api.WARN, dict(a=3))

        self.assertEqual(self.mock_notify, True)

    def test_invalid_priority(self):
        self.assertRaises(nova.notifier.api.BadPriorityException,
                notifier_api.notify, 'publisher_id',
                'event_type', 'not a priority', dict(a=3))

    def test_rabbit_priority_queue(self):
        flags.DECLARE('notification_topics', 'nova.notifier.rabbit_notifier')
        self.stubs.Set(nova.flags.FLAGS, 'notification_driver',
                'nova.notifier.rabbit_notifier')
        self.stubs.Set(nova.flags.FLAGS, 'notification_topics',
                       ['testnotify', ])

        self.test_topic = None

        def mock_notify(context, topic, msg):
            self.test_topic = topic

        self.stubs.Set(nova.rpc, 'notify', mock_notify)
        notifier_api.notify('publisher_id', 'event_type', 'DEBUG', dict(a=3))
        self.assertEqual(self.test_topic, 'testnotify.debug')

    def test_error_notification(self):
        self.stubs.Set(nova.flags.FLAGS, 'notification_driver',
            'nova.notifier.rabbit_notifier')
        self.stubs.Set(nova.flags.FLAGS, 'publish_errors', True)
        LOG = log.getLogger('nova')
        log.setup()
        msgs = []

        def mock_notify(context, topic, data):
            msgs.append(data)

        self.stubs.Set(nova.rpc, 'notify', mock_notify)
        LOG.error('foo')
        self.assertEqual(1, len(msgs))
        msg = msgs[0]
        self.assertEqual(msg['event_type'], 'error_notification')
        self.assertEqual(msg['priority'], 'ERROR')
        self.assertEqual(msg['payload']['error'], 'foo')

    def test_send_notification_by_decorator(self):
        self.notify_called = False

        def example_api(arg1, arg2):
            return arg1 + arg2

        example_api = nova.notifier.api.notify_decorator(
                            'example_api',
                             example_api)

        def mock_notify(cls, *args):
            self.notify_called = True

        self.stubs.Set(nova.notifier.no_op_notifier, 'notify',
                mock_notify)

        self.assertEqual(3, example_api(1, 2))
        self.assertEqual(self.notify_called, True)
