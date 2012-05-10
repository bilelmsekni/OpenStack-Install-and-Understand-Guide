==================
Horizon Quickstart
==================

Setup
=====

To setup an Horizon development environment simply clone the Horizon git
repository at http://github.com/openstack/horizon and execute the
``run_tests.sh`` script from the root folder (see :doc:`ref/run_tests`).

Horizon assumes a single end-point for OpenStack services which defaults to
the local host (127.0.0.1). If this is not the case change the
``OPENSTACK_HOST`` setting in the ``local_settings.py`` file, located in the
``openstack-dashboard/local`` folder, to the actual IP address of the
OpenStack end-point Horizon should use.

To start the Horizon development server use the Django ``manage.py`` utility
from the ``openstack-dashboard`` directory with the context of the virtual
environment::

    > tools/with_venv.sh dashboard/manage.py runserver

Alternately specify the listen IP and port::

    > tools/with_venv.sh dashboard/manage.py runserver 0.0.0.0:8080

Once the Horizon server is running point a web browser to http://localhost:8000
or to the IP and port the server is listening.

.. note::

    The ``DevStack`` project (http://devstack.org/) can be used to install
    an OpenStack development environment from scratch.

.. note::

    The minimum required set of OpenStack services running includes the
    following:

    * Nova (compute, api, scheduler, network, *and* volume services)
    * Glance
    * Keystone

    Optional support is provided for Swift.

Horizon's Structure
===================

This project is a bit different from other OpenStack projects in that it has
two very distinct components underneath it: ``horizon``, and
``openstack-dashboard``.

The ``horizon`` directory holds the generic libraries and components that can
be used in any Django project.

The ``openstack-dashboard`` directory contains a reference Django project that
uses ``horizon``.

For development, both pieces share an environment which (by default) is
built with the ``tools/install_venv.py`` script. That script creates a
virtualenv and installs all the necessary packages.

If dependencies are added to either ``horizon`` or ``openstack-dashboard``,
they should be added to ``tools/pip-requires``.

  .. important::

    If you do anything which changes the environment (adding new dependencies
    or renaming directories are both great examples) be sure to increment the
    ``environment_version`` counter in :doc:`run_tests.sh <ref/run_tests>`.

Project
=======

INSTALLED_APPS
--------------

At the project level you add Horizon and any desired dashboards to your
``settings.INSTALLED_APPS``::

    INSTALLED_APPS = (
        'django',
        ...
        'horizon',
        'horizon.dash',
        'horizon.syspanel',
    )

URLs
----

Then you add a single line to your project's ``urls.py``::

    url(r'', include(horizon.urls)),

Those urls are automatically constructed based on the registered Horizon apps.
If a different URL structure is desired it can be constructed by hand.

Templates
---------

Pre-built template tags generate navigation. In your ``nav.html``
template you might have the following::

    {% load horizon %}

    <div class='nav'>
        {% horizon_main_nav %}
    </div>

And in your ``sidebar.html`` you might have::

    {% load horizon %}

    <div class='sidebar'>
        {% horizon_dashboard_nav %}
    </div>

These template tags are aware of the current "active" dashboard and panel
via template context variables and will render accordingly.

Application
===========

Structure
---------

An application would have the following structure (we'll use syspanel as
an example)::

    syspanel/
    |---__init__.py
    |---dashboard.py <-----Registers the app with Horizon and sets dashboard properties
    |---templates/
    |---templatetags/
    |---overview/
    |---services/
    |---images/
        |---__init__.py
        |---panel.py <-----Registers the panel in the app and defines panel properties
        |---urls.py
        |---views.py
        |---forms.py
        |---tests.py
        |---api.py <-------Optional additional API methods for non-core services
        |---templates/
        ...
    ...

Dashboard Classes
-----------------

Inside of ``dashboard.py`` you would have a class definition and the registration
process::

    import horizon


    class Syspanel(horizon.Dashboard):
        name = "Syspanel" # Appears in navigation
        slug = 'syspanel' # Appears in url
        panels = ('overview', 'services', 'instances', 'flavors', 'images',
                  'tenants', 'users', 'quotas',)
        default_panel = 'overview'
        roles = ('admin',) # Provides RBAC at the dashboard-level
        ...


    horizon.register(Syspanel)

Panel Classes
-------------

To connect a :class:`~horizon.Panel` with a :class:`~horizon.Dashboard` class
you register it in a ``panels.py`` file like so::

    import horizon

    from horizon.dashboard.syspanel import dashboard


    class Images(horizon.Panel):
        name = "Images"
        slug = 'images'
        roles = ('admin', 'my_other_role',) # Fine-grained RBAC per-panel


    # You could also register your panel with another application's dashboard
    dashboard.Syspanel.register(Images)

By default a :class:`~horizon.Panel` class looks for a ``urls.py`` file in the
same directory as ``panel.py`` to include in the rollup of url patterns from
panels to dashboards to Horizon, resulting in a wholly extensible, configurable
URL structure.
