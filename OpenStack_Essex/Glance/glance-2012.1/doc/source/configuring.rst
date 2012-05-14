..
      Copyright 2011 OpenStack, LLC
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

Configuring Glance
==================

Glance has a number of options that you can use to configure the Glance API
server, the Glance Registry server, and the various storage backends that
Glance can use to store images.

Most configuration is done via configuration files, with the Glance API
server and Glance Registry server using separate configuration files.

When starting up a Glance server, you can specify the configuration file to
use (see `the documentation on controller Glance servers <controllingservers>`_).
If you do **not** specify a configuration file, Glance will look in the following
directories for a configuration file, in order:

* ``~/.glance``
* ``~/``
* ``/etc/glance``
* ``/etc``

The Glance API server configuration file should be named ``glance-api.conf``.
Similarly, the Glance Registry server configuration file should be named
``glance-registry.conf``. If you installed Glance via your operating system's
package management system, it is likely that you will have sample
configuration files installed in ``/etc/glance``.

In addition to this documentation page, you can check the
``etc/glance-api.conf`` and ``etc/glance-registry.conf`` sample configuration
files distributed with Glance for example configuration files for each server
application with detailed comments on what each options does.

The PasteDeploy configuration (controlling the deployment of the WSGI
application for each component) may be found by default in
<component>-paste.ini alongside the main configuration file, <component>.conf.
For example, ``glance-api-paste.ini`` corresponds to ``glance-api.conf``.
This pathname for the paste config is configurable, as follows::

  [paste_deploy]
  config_file = /path/to/paste/config


Common Configuration Options in Glance
--------------------------------------

Glance has a few command-line options that are common to all Glance programs:

* ``--verbose``

Optional. Default: ``False``

Can be specified on the command line and in configuration files.

Turns on the INFO level in logging and prints more verbose command-line
interface printouts.

* ``--debug``

Optional. Default: ``False``

Can be specified on the command line and in configuration files.

Turns on the DEBUG level in logging.

* ``--config-file=PATH``

Optional. Default: ``None``

Specified on the command line only.

Takes a path to a configuration file to use when running the program. If this
CLI option is not specified, then we check to see if the first argument is a
file. If it is, then we try to use that as the configuration file. If there is
no file or there were no arguments, we search for a configuration file in the
following order:

* ``~/.glance``
* ``~/``
* ``/etc/glance``
* ``/etc``

The filename that is searched for depends on the server application name. So,
if you are starting up the API server, ``glance-api.conf`` is searched for,
otherwise ``glance-registry.conf``.

Configuring Server Startup Options
----------------------------------

You can put the following options in the ``glance-api.conf`` and
``glance-registry.conf`` files, under the ``[DEFAULT]`` section. They enable
startup and binding behaviour for the API and registry servers, respectively.

* ``bind_host=ADDRESS``

The address of the host to bind to.

Optional. Default: ``0.0.0.0``

* ``bind_port=PORT``

The port the server should bind to.

Optional. Default: ``9191`` for the registry server, ``9292`` for the API server

* ``backlog=REQUESTS``

Number of backlog requests to configure the socket with.

Optional. Default: ``4096``

* ``workers=PROCESSES``

Number of Glance API worker processes to start. Each worker
process will listen on the same port. Increasing this
value may increase performance (especially if using SSL
with compression enabled). Typically it is recommended
to have one worker process per CPU. The value `0` will
prevent any new processes from being created.

Optional. Default: ``0``

Configurating SSL Support
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``cert_file=PATH``

Path to the the certificate file the server should use when binding to an
SSL-wrapped socket.

Optional. Default: not enabled.

* ``key_file=PATH``

Path to the the private key file the server should use when binding to an
SSL-wrapped socket.

Optional. Default: not enabled.

* ``registry_client_protocol=PROTOCOL``

If you run a secure Registry server, you need to set this value to ``https``
and also set ``registry_client_key_file`` and optionally
``registry_client_cert_file``.

Optional. Default: http

* ``registry_client_key_file=PATH``

The path to the key file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_KEY_FILE`` environ variable to a filepath of the key file

Optional. Default: Not set.

* ``registry_client_cert_file=PATH``

Optional. Default: Not set.

The path to the cert file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_CERT_FILE`` environ variable to a filepath of the cert file

* ``registry_client_ca_file=PATH``

Optional. Default: Not set.

The path to a Certifying Authority's cert file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_CA_FILE`` environ variable to a filepath of the CA cert file

Configuring Logging in Glance
-----------------------------

There are a number of configuration options in Glance that control how Glance
servers log messages.

* ``--log-config=PATH``

Optional. Default: ``None``

Specified on the command line only.

Takes a path to a configuration file to use for configuring logging.

Logging Options Available Only in Configuration Files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You will want to place the different logging options in the **[DEFAULT]** section
in your application configuration file. As an example, you might do the following
for the API server, in a configuration file called ``etc/glance-api.conf``::

  [DEFAULT]
  log_file = /var/log/glance/api.log

* ``log_file``

The filepath of the file to use for logging messages from Glance's servers. If
missing, the default is to output messages to ``stdout``, so if you are running
Glance servers in a daemon mode (using ``glance-control``) you should make
sure that the ``log_file`` option is set appropriately.

* ``log_dir``

The filepath of the directory to use for log files. If not specified (the default)
the ``log_file`` is used as an absolute filepath.

* ``log_date_format``

The format string for timestamps in the log output.

Defaults to ``%Y-%m-%d %H:%M:%S``. See the
`logging module <http://docs.python.org/library/logging.html>`_ documentation for
more information on setting this format string.

* ``log_use_syslog``

Use syslog logging functionality.

Defaults to False.

Configuring Glance Storage Backends
-----------------------------------

There are a number of configuration options in Glance that control how Glance
stores disk images. These configuration options are specified in the
``glance-api.conf`` config file in the section ``[DEFAULT]``.

* ``default_store=STORE``

Optional. Default: ``file``

Can only be specified in configuration files.

Sets the storage backend to use by default when storing images in Glance.
Available options for this option are (``file``, ``swift``, ``s3``, or ``rbd``).

Configuring the Filesystem Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``filesystem_store_datadir=PATH``

Optional. Default: ``/var/lib/glance/images/``

Can only be specified in configuration files.

`This option is specific to the filesystem storage backend.`

Sets the path where the filesystem storage backend write disk images. Note that
the filesystem storage backend will attempt to create this directory if it does
not exist. Ensure that the user that ``glance-api`` runs under has write
permissions to this directory.

Configuring the Swift Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``swift_store_auth_address=URL``

Required when using the Swift storage backend.

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Sets the authentication URL supplied to Swift when making calls to its storage
system. For more information about the Swift authentication system, please
see the `Swift auth <http://swift.openstack.org/overview_auth.html>`_
documentation and the
`overview of Swift authentication <http://docs.openstack.org/openstack-object-storage/admin/content/ch02s02.html>`_.

**IMPORTANT NOTE**: Swift authentication addresses use HTTPS by default. This
means that if you are running Swift with authentication over HTTP, you need
to set your ``swift_store_auth_address`` to the full URL, including the ``http://``.

* ``swift_store_user=USER``

Required when using the Swift storage backend.

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Sets the user to authenticate against the ``swift_store_auth_address`` with.

* ``swift_store_key=KEY``

Required when using the Swift storage backend.

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Sets the authentication key to authenticate against the
``swift_store_auth_address`` with for the user ``swift_store_user``.

* ``swift_store_container=CONTAINER``

Optional. Default: ``glance``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Sets the name of the container to use for Glance images in Swift.

* ``swift_store_create_container_on_put``

Optional. Default: ``False``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

If true, Glance will attempt to create the container ``swift_store_container``
if it does not exist.

* ``swift_store_large_object_size=SIZE_IN_MB``

Optional. Default: ``5120``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

What size, in MB, should Glance start chunking image files
and do a large object manifest in Swift? By default, this is
the maximum object size in Swift, which is 5GB

* ``swift_store_large_object_chunk_size=SIZE_IN_MB``

Optional. Default: ``200``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

When doing a large object manifest, what size, in MB, should
Glance write chunks to Swift?  The default is 200MB.

Configuring the S3 Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``s3_store_host=URL``

Required when using the S3 storage backend.

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

Default: s3.amazonaws.com

Sets the main service URL supplied to S3 when making calls to its storage
system. For more information about the S3 authentication system, please
see the `S3 documentation <http://aws.amazon.com/documentation/s3/>`_

* ``s3_store_access_key=ACCESS_KEY``

Required when using the S3 storage backend.

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

Sets the access key to authenticate against the ``s3_store_host`` with.

You should set this to your 20-character Amazon AWS access key.

* ``s3_store_secret_key=SECRET_KEY``

Required when using the S3 storage backend.

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

Sets the secret key to authenticate against the
``s3_store_host`` with for the access key ``s3_store_access_key``.

You should set this to your 40-character Amazon AWS secret key.

* ``s3_store_bucket=BUCKET``

Required when using the S3 storage backend.

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

Sets the name of the bucket to use for Glance images in S3.

Note that the namespace for S3 buckets is **global**, and
therefore you must use a name for the bucket that is unique. It
is recommended that you use a combination of your AWS access key,
**lowercased** with "glance".

For instance if your Amazon AWS access key is:

``ABCDEFGHIJKLMNOPQRST``

then make your bucket value be:

``abcdefghijklmnopqrstglance``

* ``s3_store_create_bucket_on_put``

Optional. Default: ``False``

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

If true, Glance will attempt to create the bucket ``s3_store_bucket``
if it does not exist.

* ``s3_store_object_buffer_dir=PATH``

Optional. Default: ``the platform's default temporary directory``

Can only be specified in configuration files.

`This option is specific to the S3 storage backend.`

When sending images to S3, what directory should be
used to buffer the chunks? By default the platform's
temporary directory will be used.

Configuring the RBD Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Note**: the RBD storage backend requires the python bindings for
librados and librbd. These are in the python-ceph package on
Debian-based distributions.

* ``rbd_store_pool=POOL``

Optional. Default: ``rbd``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the RADOS pool in which images are stored.

* ``rbd_store_chunk_size=CHUNK_SIZE_MB``

Optional. Default: ``4``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Images will be chunked into objects of this size (in megabytes).
For best performance, this should be a power of two.

* ``rbd_store_ceph_conf=PATH``

Optional. Default: ``/etc/ceph/ceph.conf``, ``~/.ceph/config``, and ``./ceph.conf``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the Ceph configuration file to use.

* ``rbd_store_user=NAME``

Optional. Default: ``admin``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the RADOS user to authenticate as. This is only needed
when `RADOS authentication <http://ceph.newdream.net/wiki/Cephx>`_
is `enabled. <http://ceph.newdream.net/wiki/Cluster_configuration#Cephx_auth>`_

A keyring must be set for this user in the Ceph
configuration file, e.g. with a user ``glance``::

  [client.glance]
  keyring=/etc/glance/rbd.keyring

To set up a user named ``glance`` with minimal permissions, using a pool called
``images``, run::

  rados mkpool images
  ceph-authtool --create-keyring /etc/glance/rbd.keyring
  ceph-authtool --gen-key --name client.glance --cap mon 'allow r' --cap osd 'allow rwx pool=images' /etc/glance/rbd.keyring
  ceph auth add client.glance -i /etc/glance/rbd.keyring

Configuring the Image Cache
---------------------------

Glance API servers can be configured to have a local image cache. Caching of
image files is transparent and happens using a piece of middleware that can
optionally be placed in the server application pipeline.

This pipeline is configured in the PasteDeploy configuration file,
<component>-paste.ini. You should not generally have to edit this file
directly, as it ships with ready-made pipelines for all common deployment
flavors.

Enabling the Image Cache Middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the image cache middleware, the cache middleware must occur in
the application pipeline **after** the appropriate context middleware.

The cache middleware should be in your ``glance-api-paste.ini`` in a section
titled ``[filter:cache]``. It should look like this::

  [filter:cache]
  paste.filter_factory = glance.common.wsgi:filter_factory
  glance.filter_factory = glance.api.middleware.cache:CacheFilter

A ready-made application pipeline including this filter is defined in
the ``glance-api-paste.ini`` file, looking like so::

  [pipeline:glance-api-caching]
  pipeline = versionnegotiation context cache apiv1app

To enable the above application pipeline, in your main ``glance-api.conf``
configuration file, select the appropriate deployment flavor like so::

  [paste_deploy]
  flavor = caching

And that would give you a transparent image cache on the API server.

Configuration Options Affecting the Image Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One main configuration file option affects the image cache.

 * ``image_cache_dir=PATH``

Required when image cache middleware is enabled.

Default: ``/var/lib/glance/image-cache``

This is the base directory the image cache can write files to.
Make sure the directory is writeable by the user running the
``glance-api`` server

 * ``image_cache_driver=DRIVER``

Optional. Choice of ``sqlite`` or ``xattr``

Default: ``sqlite``

The default ``sqlite`` cache driver has no special dependencies, other
than the ``python-sqlite3`` library, which is installed on virtually
all operating systems with modern versions of Python. It stores
information about the cached files in a SQLite database.

The ``xattr`` cache driver required the ``python-xattr>=0.6.0`` library
and requires that the filesystem containing ``image_cache_dir`` have
access times tracked for all files (in other words, the noatime option
CANNOT be set for that filesystem). In addition, ``user_xattr`` must be
set on the filesystem's description line in fstab. Because of these
requirements, the ``xattr`` cache driver is not available on Windows.

 * ``image_cache_sqlite_db=DB_FILE``

Optional.

Default: ``cache.db``

When using the ``sqlite`` cache driver, you can set the name of the database
that will be used to store the cached images information. The database
is always contained in the ``image_cache_dir``.

 * ``image_cache_max_size=SIZE``

Optional.

Default: ``10737418240`` (10 GB)

Size, in bytes, that the image cache should be constrained to. Images files
are cached automatically in the local image cache, even if the writing of that
image file would put the total cache size over this size. The
``glance-cache-pruner`` executable is what prunes the image cache to be equal
to or less than this value. The ``glance-cache-pruner`` executable is designed
to be run via cron on a regular basis. See more about this executable in
:doc:`Controlling the Growth of the Image Cache <cache>`

.. note::

  These configuration options must be set in both the glance-cache
  and glance-api configuration files.

Configuring the Glance Registry
-------------------------------

There are a number of configuration options in Glance that control how 
this registry server operates. These configuration options are specified in the
``glance-registry.conf`` config file in the section ``[DEFAULT]``.

* ``sql_connection=CONNECTION_STRING`` (``--sql-connection`` when specified
  on command line)

Optional. Default: ``None``

Can be specified in configuration files. Can also be specified on the
command-line for the ``glance-manage`` program.

Sets the SQLAlchemy connection string to use when connecting to the registry
database. Please see the documentation for
`SQLAlchemy connection strings <http://www.sqlalchemy.org/docs/05/reference/sqlalchemy/connections.html>`_
online.

* ``sql_timeout=SECONDS``
  on command line)

Optional. Default: ``3600``

Can only be specified in configuration files.

Sets the number of seconds after which SQLAlchemy should reconnect to the
datastore if no activity has been made on the connection.

Configuring Notifications
-------------------------

Glance can optionally generate notifications to be logged or sent to
a RabbitMQ queue. The configuration options are specified in the
``glance-api.conf`` config file in the section ``[DEFAULT]``.

* ``notifier_strategy``

Optional. Default: ``noop``

Sets the strategy used for notifications. Options are ``logging``,
``rabbit``, ``qpid`` and ``noop``.
For more information :doc:`Glance notifications <notifications>`

* ``rabbit_host``

Optional. Default: ``localhost``

Host to connect to when using ``rabbit`` strategy.

* ``rabbit_port``

Optional. Default: ``5672``

Port to connect to when using ``rabbit`` strategy.

* ``rabbit_use_ssl``

Optional. Default: ``false``

Boolean to use SSL for connecting when using ``rabbit`` strategy.

* ``rabbit_userid``

Optional. Default: ``guest``

Userid to use for connection when using ``rabbit`` strategy.

* ``rabbit_password``

Optional. Default: ``guest``

Password to use for connection when using ``rabbit`` strategy.

* ``rabbit_virtual_host``

Optional. Default: ``/``

Virtual host to use for connection when using ``rabbit`` strategy.

* ``rabbit_notification_exchange``

Optional. Default: ``glance``

Exchange name to use for connection when using ``rabbit`` strategy.

* ``rabbit_notification_topic``

Optional. Default: ``glance_notifications``

Topic to use for connection when using ``rabbit`` strategy.

* ``rabbit_max_retries``

Optional. Default: ``0``

Number of retries on communication failures when using ``rabbit`` strategy.
A value of 0 means to retry forever.

* ``rabbit_retry_backoff``

Optional. Default: ``2``

Number of seconds to wait before reconnecting on failures when using
``rabbit`` strategy.

* ``rabbit_retry_max_backoff``

Optional. Default: ``30``

Maximum seconds to wait before reconnecting on failures when using
``rabbit`` strategy.

* ``qpid_notification_exchange``

Optional. Default: ``glance``

Message exchange to use when using the ``qpid`` notification strategy.

* ``qpid_notification_topic``

Optional. Default: ``glanice_notifications``

This is the topic prefix for notifications when using the ``qpid``
notification strategy. When a notification is sent at the ``info`` priority,
the topic will be ``glance_notifications.info``. The same idea applies for
the ``error`` and ``warn`` notification priorities. To receive all
notifications, you would set up a receiver with a topic of
``glance_notifications.*``.

* ``qpid_host``

Optional. Default: ``localhost``

This is the hostname or IP address of the Qpid broker that will be used
when Glance has been configured to use the ``qpid`` notification strategy.

* ``qpid_port``

Optional. Default: ``5672``

This is the port number to connect to on the Qpid broker, ``qpid_host``,
when using the ``qpid`` notification strategy.

* ``qpid_username``

Optional. Default: None

This is the username that Glance will use to authenticate with the Qpid
broker if using the ``qpid`` notification strategy.

* ``qpid_password``

Optional. Default: None

This is the username that Glance will use to authenticate with the Qpid
broker if using the ``qpid`` notification strategy.

* ``qpid_sasl_mechanisms``

Optional. Default: None

This is a space separated list of SASL mechanisms to use for authentication
with the Qpid broker if using the ``qpid`` notification strategy.

* ``qpid_reconnect_timeout``

Optional. Default: None

This option specifies a timeout in seconds for automatic reconnect attempts
to the Qpid broker if the ``qpid`` notification strategy is used.  In general,
it is safe to leave all of the reconnect timing options not set. In that case,
the Qpid client's default behavior will be used, which is to attempt to
reconnect to the broker at exponential back-off intervals (in 1 second, then 2
seconds, then 4, 8, 16, etc).

* ``qpid_reconnect_limit``

Optional. Default: None

This option specifies a maximum number of reconnect attempts to the Qpid
broker if the ``qpid`` notification strategy is being used.  Normally the
Qpid client will continue attempting to reconnect until successful.

* ``qpid_reconnect_interval_min``

Optional. Default: None

This option specifies the minimum number of seconds between reconnection
attempts if the ``qpid`` notification strategy is being used.

* ``qpid_reconnect_interval_max``

Optional. Default: None

This option specifies the maximum number of seconds between reconnection
attempts if the ``qpid`` notification strategy is being used.

* ``qpid_reconnect_interval``

This option specifies the exact number of seconds between reconnection
attempts if the ``qpid`` notification strategy is being used. Setting
this option is equivalent to setting ``qpid_reconnect_interval_max`` and
``qpid_reconnect_interval_min`` to the same value.

* ``qpid_heartbeat``

Optional. Default: ``5``

This option is used to specify the number of seconds between heartbeat messages
exchanged between the Qpid client and Qpid broker if the ``qpid`` notification
strategy is being used.  Heartbeats are used to more quickly detect that a
connection has been lost.

* ``qpid_protocol``

Optional. Default: ``tcp``

This option is used to specify the transport protocol to use if using the
``qpid`` notification strategy. To enable SSL, set this option to ``ssl``.

* ``qpid_tcp_nodelay``

Optional. Default: ``True``

This option can be used to disable the TCP NODELAY option. It effectively
disables the Nagle algorithm for the connection to the Qpid broker. This
option only applies if the ``qpid`` notification strategy is used.

Configuring Access Policies
---------------------------

Access rules may be configured using a
:doc:`Policy Configuration file <policies>`. Two configuration options tell
the Glance API server about the policies to use.

* ``policy_file=PATH``

Optional. Default: Looks for a file called ``policy.json`` or
``glance.policy.json`` in standard configuration directories.

Policy file to load when starting the API server

* ``policy_default_rule=RULE``

Optional. Default: "default"

Name of the rule in the policy configuration file to use as the default rule
