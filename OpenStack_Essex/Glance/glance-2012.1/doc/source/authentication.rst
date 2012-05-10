..
      Copyright 2010 OpenStack, LLC
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Glance Authentication With Keystone
===================================

Glance may optionally be integrated with Keystone.  Setting this up is
relatively straightforward, as the Keystone distribution includes the
necessary middleware. Once you have installed Keystone
and edited your configuration files, newly created images will have
their `owner` attribute set to the tenant of the authenticated users,
and the `is_public` attribute will cause access to those images for
which it is `false` to be restricted to only the owner.

.. note::

  The exception is those images for which `owner` is set to `null`,
  which may only be done by those users having the ``Admin`` role.
  These images may still be accessed by the public, but will not
  appear in the list of public images.  This allows the Glance
  Registry owner to publish images for beta testing without allowing
  those images to show up in lists, potentially confusing users.


Configuring the Glance servers to use Keystone
----------------------------------------------

Keystone is integrated with Glance through the use of middleware. The
default configuration files for both the Glance API and the Glance
Registry use a single piece of middleware called ``context``, which
generates a request context containing all the necesary authorization
information. In order to configure Glance to use Keystone, the
``authtoken`` middleware must also be deployed (which may be found in the
Keystone distribution). The ``authtoken`` middleware performs the Keystone
token validation, which is the heart of Keystone authentication.

It is important to note that the Glance API and the Glance Registry
use two different context classes; this is because the registry needs
advanced methods that are not available in the default context class.
The implications of this will be obvious in the below example for
configuring the Glance Registry.

Configuring Glance API to use Keystone
--------------------------------------

Configuring Glance API to use Keystone is relatively straight
forward.  The first step is to ensure that declarations for the two
pieces of middleware exist in the ``glance-api-paste.ini``.  Here is
an example for ``authtoken``::

  [filter:authtoken]
  paste.filter_factory = keystone.middleware.auth_token:filter_factory
  service_protocol = http
  service_host = 127.0.0.1
  service_port = 5000
  auth_host = 127.0.0.1
  auth_port = 35357
  auth_protocol = http
  auth_uri = http://127.0.0.1:5000/
  admin_user = glance_admin
  admin_tenant_name = service_admins
  admin_password = password1234

The actual values for these variables will need to be set depending on
your situation.  For more information, please refer to the Keystone
documentation on the ``auth_token`` middleware, but in short:

* Those variables beginning with ``service_`` are only needed if you
  are using a proxy; they define the actual location of Glance.  That
  said, they must be present.
* Except for ``auth_uri``, those variables beginning with ``auth_``
  point to the Keystone Admin service.  This information is used by
  the middleware to actually query Keystone about the validity of the
  authentication tokens.
* The ``auth_uri`` variable must point to the Keystone Auth service,
  which is the service users use to obtain Keystone tokens.  If the
  user does not have a valid Keystone token, they will be redirected
  to this URI to obtain one.
* The admin auth credentials (``admin_user``, ``admin_tenant_name``,
  ``admin_password``) will be used to retrieve an admin token. That
  token will be used to authorize user tokens behind the scenes.

Finally, to actually enable using Keystone authentication, the
application pipeline must be modified.  By default, it looks like::

  [pipeline:glance-api]
  pipeline = versionnegotiation context apiv1app

(Your particular pipeline may vary depending on other options, such as
the image cache.)  This must be changed by inserting ``authtoken``
before ``context``::

  [pipeline:glance-api]
  pipeline = versionnegotiation authtoken context apiv1app

Configuring Glance Registry to use Keystone
-------------------------------------------

Configuring Glance Registry to use Keystone is also relatively
straight forward.  The same middleware needs to be added
to ``glance-registry-paste.ini`` as was needed by Glance API;
see above for an example of the ``authtoken`` configuration.

Again, to enable using Keystone authentication, the appropriate
application pipeline must be selected.  By default, it looks like::

  [pipeline:glance-registry-keystone]
  pipeline = authtoken context registryapp

To enable the above application pipeline, in your main ``glance-registry.conf``
configuration file, select the appropriate deployment flavor by adding a
``flavor`` attribute in the ``paste_deploy`` group::

  [paste_deploy]
  flavor = keystone

.. note::
  If your authentication service uses a role other than ``admin`` to identify
  which users should be granted admin-level privileges, you must define it
  in the ``admin_role`` config attribute in both ``glance-registry.conf`` and
  ``glance-api.conf``.

Sharing Images With Others
--------------------------

It is possible to allow a private image to be shared with one or more
alternate tenants.  This is done through image *memberships*, which
are available via the `members` resource of images.  (For more
details, see :doc:`glanceapi`.)  Essentially, a membership is an
association between an image and a tenant which has permission to
access that image.  These membership associations may also have a
`can_share` attribute, which, if set to `true`, delegates the
authority to share an image to the named tenant.

Configuring the Glance Client to use Keystone
---------------------------------------------

Once the Glance API and Registry servers have been configured to use
Keystone, you will need to configure the Glance client (``bin/glance``)
to use Keystone as well. Like the other OpenStack projects, this is
done through a common set of environment variables. These credentials may
may alternatively be specified using the following switches to
the ``bin/glance`` command:

  OS_USERNAME=<USERNAME>, -I <USERNAME>, --os_username=<USERNAME>
                        User name used to acquire an authentication token
  OS_PASSWORD=<PASSWORD>, -K <PASSWORD>, --os_password=<PASSWORD>
                        Password used to acquire an authentication token
  OS_TENANT_NAME=<TENANT_NAME> -T <TENANT_NAME>, --os_tenant_name=<TENANT_NAME>
                        Tenant name
  OS_AUTH_URL=<AUTH_URL>, -N <AUTH_URL>, --os_auth_url=<AUTH_URL>
                        Authentication endpoint
  OS_REGION_NAME=<REGION_NAME>, -R <REGION_NAME>, --os_region_name=<REGION_NAME>
                        Used to select a specific region while
                        authenticating against Keystone

Or, if a pre-authenticated token is preferred, the following option allows
the client-side interaction with keystone to be bypassed (useful if a long
sequence of commands is being scripted):

  OS_TOKEN=<TOKEN>, -A <TOKEN>, --os_auth_token=<TOKEN>
                        User's authentication token that identifies the
                        client to the glance server. This is not
                        an admin token.

In general the command line switch takes precedence over the corresponding
OS_* environment variable, if both are set.
