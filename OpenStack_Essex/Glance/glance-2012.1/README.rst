======
Glance
======

Glance is a project that defines services for discovering, registering,
retrieving and storing virtual machine images. The discovery and registration
responsibilities are handled by the `glance-registry` component while the
retrieval and storage responsiblities are handled by the `glance-api`
component.


Quick Start
-----------

If you'd like to run trunk, you can clone the git repo:

    git clone git@github.com:openstack/glance.git


Install Glance by running::

    python setup.py build
    sudo python setup.py install


By default, `glance-registry` will use a SQLite database. If you'd like to use
MySQL, or make other adjustments, you can modify the glance.cnf file (see
documentation for more details).


Now that Glance is installed, you can start the service.  The easiest way to
do that is by using the `glance-control` utility which runs both the
`glance-api` and `glance-registry` services::

    glance-control all start


Once both services are running, you can now use the `glance` tool to
register new images in Glance.

    glance add name="My Image" < /path/to/my/image


With an image registered, you can now configure your IAAS provider to use
Glance as its image service and begin spinning up instances from your
newly registered images.
