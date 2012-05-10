# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack, LLC
# Copyright 2012 Red Hat, Inc
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

"""Functional test asserting strongly typed exceptions from glance client"""

import eventlet.patcher
import webob.dec
import webob.exc

from glance.common import client
from glance.common import exception
from glance.common import wsgi
from glance.tests import functional
from glance.tests import utils


eventlet.patcher.monkey_patch(socket=True)


class ExceptionTestApp(object):
    """
    Test WSGI application which can respond with multiple kinds of HTTP
    status codes
    """

    @webob.dec.wsgify
    def __call__(self, request):
        path = request.path_qs

        if path == "/rate-limit":
            request.response = webob.exc.HTTPRequestEntityTooLarge()

        elif path == "/rate-limit-retry":
            request.response.retry_after = 10
            request.response.status = 413

        elif path == "/service-unavailable":
            request.response = webob.exc.HTTPServiceUnavailable()

        elif path == "/service-unavailable-retry":
            request.response.retry_after = 10
            request.response.status = 503

        elif path == "/expectation-failed":
            request.response = webob.exc.HTTPExpectationFailed()

        elif path == "/server-error":
            request.response = webob.exc.HTTPServerError()


class TestClientExceptions(functional.FunctionalTest):

    def setUp(self):
        super(TestClientExceptions, self).setUp()
        self.port = utils.get_unused_port()
        server = wsgi.Server()
        conf = utils.TestConfigOpts({'bind_host': '127.0.0.1'})
        server.start(ExceptionTestApp(), conf, self.port)
        self.client = client.BaseClient("127.0.0.1", self.port)

    def _do_test_exception(self, path, exc_type):
        try:
            self.client.do_request("GET", path)
            self.fail('expected %s' % exc_type)
        except exc_type as e:
            if 'retry' in path:
                self.assertEquals(e.retry_after, 10)

    def test_rate_limited(self):
        """
        Test rate limited response
        """
        self._do_test_exception('/rate-limit', exception.LimitExceeded)

    def test_rate_limited_retry(self):
        """
        Test rate limited response with retry
        """
        self._do_test_exception('/rate-limit-retry', exception.LimitExceeded)

    def test_service_unavailable(self):
        """
        Test service unavailable response
        """
        self._do_test_exception('/service-unavailable',
                                exception.ServiceUnavailable)

    def test_service_unavailable_retry(self):
        """
        Test service unavailable response with retry
        """
        self._do_test_exception('/service-unavailable-retry',
                                exception.ServiceUnavailable)

    def test_expectation_failed(self):
        """
        Test expectation failed response
        """
        self._do_test_exception('/expectation-failed',
                                exception.UnexpectedStatus)

    def test_server_error(self):
        """
        Test server error response
        """
        self._do_test_exception('/server-error',
                                exception.ServerError)
