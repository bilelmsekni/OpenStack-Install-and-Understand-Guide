# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Nebula, Inc.
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

from django.conf.urls.defaults import patterns, url

from .views import (IndexView, CreateView, UpdateView, QuotasView, UsersView,
                    AddUserView, TenantUsageView)


urlpatterns = patterns('',
    url(r'^$', IndexView.as_view(), name='index'),
    url(r'^create$', CreateView.as_view(), name='create'),
    url(r'^(?P<tenant_id>[^/]+)/update/$',
        UpdateView.as_view(), name='update'),
    url(r'^(?P<tenant_id>[^/]+)/quotas/$',
        QuotasView.as_view(), name='quotas'),
    url(r'^(?P<tenant_id>[^/]+)/usage/$',
        TenantUsageView.as_view(), name='usage'),
    url(r'^(?P<tenant_id>[^/]+)/users/$', UsersView.as_view(), name='users'),
    url(r'^(?P<tenant_id>[^/]+)/users/(?P<user_id>[^/]+)/add/$',
        AddUserView.as_view(), name='add_user')
)
