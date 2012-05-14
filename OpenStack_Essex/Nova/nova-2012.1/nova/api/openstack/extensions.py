# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2011 Justin Santa Barbara
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

import os

import webob.dec
import webob.exc

import nova.api.openstack
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova import flags
from nova import log as logging
import nova.policy
from nova import utils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class ExtensionDescriptor(object):
    """Base class that defines the contract for extensions.

    Note that you don't have to derive from this class to have a valid
    extension; it is purely a convenience.

    """

    # The name of the extension, e.g., 'Fox In Socks'
    name = None

    # The alias for the extension, e.g., 'FOXNSOX'
    alias = None

    # Description comes from the docstring for the class

    # The XML namespace for the extension, e.g.,
    # 'http://www.fox.in.socks/api/ext/pie/v1.0'
    namespace = None

    # The timestamp when the extension was last updated, e.g.,
    # '2011-01-22T13:25:27-06:00'
    updated = None

    def __init__(self, ext_mgr):
        """Register extension with the extension manager."""

        ext_mgr.register(self)

    def get_resources(self):
        """List of extensions.ResourceExtension extension objects.

        Resources define new nouns, and are accessible through URLs.

        """
        resources = []
        return resources

    def get_controller_extensions(self):
        """List of extensions.ControllerExtension extension objects.

        Controller extensions are used to extend existing controllers.
        """
        controller_exts = []
        return controller_exts

    @classmethod
    def nsmap(cls):
        """Synthesize a namespace map from extension."""

        # Start with a base nsmap
        nsmap = ext_nsmap.copy()

        # Add the namespace for the extension
        nsmap[cls.alias] = cls.namespace

        return nsmap

    @classmethod
    def xmlname(cls, name):
        """Synthesize element and attribute names."""

        return '{%s}%s' % (cls.namespace, name)


def make_ext(elem):
    elem.set('name')
    elem.set('namespace')
    elem.set('alias')
    elem.set('updated')

    desc = xmlutil.SubTemplateElement(elem, 'description')
    desc.text = 'description'

    xmlutil.make_links(elem, 'links')


ext_nsmap = {None: xmlutil.XMLNS_COMMON_V10, 'atom': xmlutil.XMLNS_ATOM}


class ExtensionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('extension', selector='extension')
        make_ext(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=ext_nsmap)


class ExtensionsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('extensions')
        elem = xmlutil.SubTemplateElement(root, 'extension',
                                          selector='extensions')
        make_ext(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=ext_nsmap)


class ExtensionsResource(wsgi.Resource):

    def __init__(self, extension_manager):
        self.extension_manager = extension_manager
        super(ExtensionsResource, self).__init__(None)

    def _translate(self, ext):
        ext_data = {}
        ext_data['name'] = ext.name
        ext_data['alias'] = ext.alias
        ext_data['description'] = ext.__doc__
        ext_data['namespace'] = ext.namespace
        ext_data['updated'] = ext.updated
        ext_data['links'] = []  # TODO(dprince): implement extension links
        return ext_data

    @wsgi.serializers(xml=ExtensionsTemplate)
    def index(self, req):
        extensions = []
        for _alias, ext in self.extension_manager.extensions.iteritems():
            extensions.append(self._translate(ext))
        return dict(extensions=extensions)

    @wsgi.serializers(xml=ExtensionTemplate)
    def show(self, req, id):
        try:
            # NOTE(dprince): the extensions alias is used as the 'id' for show
            ext = self.extension_manager.extensions[id]
        except KeyError:
            raise webob.exc.HTTPNotFound()

        return dict(extension=self._translate(ext))

    def delete(self, req, id):
        raise webob.exc.HTTPNotFound()

    def create(self, req):
        raise webob.exc.HTTPNotFound()


class ExtensionManager(object):
    """Load extensions from the configured extension path.

    See nova/tests/api/openstack/extensions/foxinsocks/extension.py for an
    example extension implementation.

    """

    def register(self, ext):
        # Do nothing if the extension doesn't check out
        if not self._check_extension(ext):
            return

        alias = ext.alias
        LOG.audit(_('Loaded extension: %s'), alias)

        if alias in self.extensions:
            raise exception.Error("Found duplicate extension: %s" % alias)
        self.extensions[alias] = ext

    def get_resources(self):
        """Returns a list of ResourceExtension objects."""

        resources = []
        resources.append(ResourceExtension('extensions',
                                           ExtensionsResource(self)))

        for ext in self.extensions.values():
            try:
                resources.extend(ext.get_resources())
            except AttributeError:
                # NOTE(dprince): Extension aren't required to have resource
                # extensions
                pass
        return resources

    def get_controller_extensions(self):
        """Returns a list of ControllerExtension objects."""
        controller_exts = []
        for ext in self.extensions.values():
            try:
                controller_exts.extend(ext.get_controller_extensions())
            except AttributeError:
                # NOTE(Vek): Extensions aren't required to have
                # controller extensions
                pass
        return controller_exts

    def _check_extension(self, extension):
        """Checks for required methods in extension objects."""
        try:
            LOG.debug(_('Ext name: %s'), extension.name)
            LOG.debug(_('Ext alias: %s'), extension.alias)
            LOG.debug(_('Ext description: %s'),
                      ' '.join(extension.__doc__.strip().split()))
            LOG.debug(_('Ext namespace: %s'), extension.namespace)
            LOG.debug(_('Ext updated: %s'), extension.updated)
        except AttributeError as ex:
            LOG.exception(_("Exception loading extension: %s"), unicode(ex))
            return False

        return True

    def load_extension(self, ext_factory):
        """Execute an extension factory.

        Loads an extension.  The 'ext_factory' is the name of a
        callable that will be imported and called with one
        argument--the extension manager.  The factory callable is
        expected to call the register() method at least once.
        """

        LOG.debug(_("Loading extension %s"), ext_factory)

        # Load the factory
        factory = utils.import_class(ext_factory)

        # Call it
        LOG.debug(_("Calling extension factory %s"), ext_factory)
        factory(self)

    def _load_extensions(self):
        """Load extensions specified on the command line."""

        extensions = list(self.cls_list)

        for ext_factory in extensions:
            try:
                self.load_extension(ext_factory)
            except Exception as exc:
                LOG.warn(_('Failed to load extension %(ext_factory)s: '
                           '%(exc)s') % locals())


class ControllerExtension(object):
    """Extend core controllers of nova OpenStack API.

    Provide a way to extend existing nova OpenStack API core
    controllers.
    """

    def __init__(self, extension, collection, controller):
        self.extension = extension
        self.collection = collection
        self.controller = controller


class ResourceExtension(object):
    """Add top level resources to the OpenStack API in nova."""

    def __init__(self, collection, controller, parent=None,
                 collection_actions=None, member_actions=None,
                 custom_routes_fn=None):
        if not collection_actions:
            collection_actions = {}
        if not member_actions:
            member_actions = {}
        self.collection = collection
        self.controller = controller
        self.parent = parent
        self.collection_actions = collection_actions
        self.member_actions = member_actions
        self.custom_routes_fn = custom_routes_fn


def wrap_errors(fn):
    """Ensure errors are not passed along."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except webob.exc.HTTPException:
            raise
        except Exception:
            raise webob.exc.HTTPInternalServerError()
    return wrapped


def load_standard_extensions(ext_mgr, logger, path, package, ext_list=None):
    """Registers all standard API extensions."""

    # Walk through all the modules in our directory...
    our_dir = path[0]
    for dirpath, dirnames, filenames in os.walk(our_dir):
        # Compute the relative package name from the dirpath
        relpath = os.path.relpath(dirpath, our_dir)
        if relpath == '.':
            relpkg = ''
        else:
            relpkg = '.%s' % '.'.join(relpath.split(os.sep))

        # Now, consider each file in turn, only considering .py files
        for fname in filenames:
            root, ext = os.path.splitext(fname)

            # Skip __init__ and anything that's not .py
            if ext != '.py' or root == '__init__':
                continue

            # Try loading it
            classname = "%s%s" % (root[0].upper(), root[1:])
            classpath = ("%s%s.%s.%s" %
                         (package, relpkg, root, classname))

            if ext_list is not None and classname not in ext_list:
                logger.debug("Skipping extension: %s" % classpath)
                continue

            try:
                ext_mgr.load_extension(classpath)
            except Exception as exc:
                logger.warn(_('Failed to load extension %(classpath)s: '
                              '%(exc)s') % locals())

        # Now, let's consider any subdirectories we may have...
        subdirs = []
        for dname in dirnames:
            # Skip it if it does not have __init__.py
            if not os.path.exists(os.path.join(dirpath, dname,
                                               '__init__.py')):
                continue

            # If it has extension(), delegate...
            ext_name = ("%s%s.%s.extension" %
                        (package, relpkg, dname))
            try:
                ext = utils.import_class(ext_name)
            except exception.ClassNotFound:
                # extension() doesn't exist on it, so we'll explore
                # the directory for ourselves
                subdirs.append(dname)
            else:
                try:
                    ext(ext_mgr)
                except Exception as exc:
                    logger.warn(_('Failed to load extension %(ext_name)s: '
                                  '%(exc)s') % locals())

        # Update the list of directories we'll explore...
        dirnames[:] = subdirs


def extension_authorizer(api_name, extension_name):
    def authorize(context, target=None):
        if target is None:
            target = {'project_id': context.project_id,
                      'user_id': context.user_id}
        action = '%s_extension:%s' % (api_name, extension_name)
        nova.policy.enforce(context, action, target)
    return authorize


def soft_extension_authorizer(api_name, extension_name):
    hard_authorize = extension_authorizer(api_name, extension_name)

    def authorize(context):
        try:
            hard_authorize(context)
            return True
        except exception.NotAuthorized:
            return False
    return authorize
