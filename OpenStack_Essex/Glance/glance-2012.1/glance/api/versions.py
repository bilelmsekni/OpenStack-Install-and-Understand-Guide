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

"""
Controller that returns information on the Glance API versions
"""

import httplib
import json

import webob.dec


class Controller(object):

    """
    A controller that produces information on the Glance API versions.
    """

    def __init__(self, conf):
        self.conf = conf

    @webob.dec.wsgify
    def __call__(self, req):
        """Respond to a request for all OpenStack API versions."""
        version_objs = [
            {
                "id": "v1.1",
                "status": "CURRENT",
                "links": [
                    {
                        "rel": "self",
                        "href": self.get_href(req)}]},
            {
                "id": "v1.0",
                "status": "SUPPORTED",
                "links": [
                    {
                        "rel": "self",
                        "href": self.get_href(req)}]}]

        body = json.dumps(dict(versions=version_objs))

        response = webob.Response(request=req,
                                  status=httplib.MULTIPLE_CHOICES,
                                  content_type='application/json')
        response.body = body

        return response

    def get_href(self, req):
        return "%s/v1/" % req.host_url
