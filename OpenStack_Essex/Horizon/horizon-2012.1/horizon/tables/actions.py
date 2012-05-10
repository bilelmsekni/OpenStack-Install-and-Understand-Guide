# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import logging
import new

from django import shortcuts
from django.conf import settings
from django.contrib import messages
from django.core import urlresolvers
from django.utils.functional import Promise
from django.utils.translation import string_concat, ugettext_lazy as _

from horizon import exceptions
from horizon.utils import html


LOG = logging.getLogger(__name__)

# For Bootstrap integration; can be overridden in settings.
ACTION_CSS_CLASSES = ("btn", "btn-small")
STRING_SEPARATOR = "__"


class BaseAction(html.HTMLElement):
    """ Common base class for all ``Action`` classes. """
    table = None
    handles_multiple = False
    requires_input = False
    preempt = False

    def __init__(self, datum=None):
        super(BaseAction, self).__init__()
        self.datum = datum

    def allowed(self, request, datum):
        """ Determine whether this action is allowed for the current request.

        This method is meant to be overridden with more specific checks.
        """
        return True

    def _allowed(self, request, datum):
        return self.allowed(request, datum)

    def update(self, request, datum):
        """ Allows per-action customization based on current conditions.

        This is particularly useful when you wish to create a "toggle"
        action that will be rendered differently based on the value of an
        attribute on the current row's data.

        By default this method is a no-op.
        """
        pass

    def get_default_classes(self):
        """
        Returns a list of the default classes for the action. Defaults to
        ``["btn", "btn-small"]``.
        """
        return getattr(settings, "ACTION_CSS_CLASSES", ACTION_CSS_CLASSES)

    def get_default_attrs(self):
        """
        Returns a list of the default HTML attributes for the action. Defaults
        to returning an ``id`` attribute with the value
        ``{{ table.name }}__action_{{ action.name }}__{{ creation counter }}``.
        """
        if self.datum is not None:
            bits = (self.table.name,
                    "row_%s" % self.table.get_object_id(self.datum),
                    "action_%s" % self.name)
        else:
            bits = (self.table.name, "action_%s" % self.name)
        return {"id": STRING_SEPARATOR.join(bits)}

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)


class Action(BaseAction):
    """ Represents an action which can be taken on this table's data.

    .. attribute:: name

        Required. The short name or "slug" representing this
        action. This name should not be changed at runtime.

    .. attribute:: verbose_name

        A descriptive name used for display purposes. Defaults to the
        value of ``name`` with the first letter of each word capitalized.

    .. attribute:: verbose_name_plural

        Used like ``verbose_name`` in cases where ``handles_multiple`` is
        ``True``. Defaults to ``verbose_name`` with the letter "s" appended.

    .. attribute:: method

        The HTTP method for this action. Defaults to ``POST``. Other methods
        may or may not succeed currently.

    .. attribute:: requires_input

        Boolean value indicating whether or not this action can be taken
        without any additional input (e.g. an object id). Defaults to ``True``.

    .. attribute:: preempt

        Boolean value indicating whether this action should be evaluated in
        the period after the table is instantiated but before the data has
        been loaded.

        This can allow actions which don't need access to the full table data
        to bypass any API calls and processing which would otherwise be
        required to load the table.

    At least one of the following methods must be defined:

    .. method:: single(self, data_table, request, object_id)

        Handler for a single-object action.

    .. method:: multiple(self, data_table, request, object_ids)

        Handler for multi-object actions.

    .. method:: handle(self, data_table, request, object_ids)

        If a single function can work for both single-object and
        multi-object cases then simply providing a ``handle`` function
        will internally route both ``single`` and ``multiple`` requests
        to ``handle`` with the calls from ``single`` being transformed
        into a list containing only the single object id.
    """
    method = "POST"
    requires_input = True

    def __init__(self, verbose_name=None, verbose_name_plural=None,
                 single_func=None, multiple_func=None, handle_func=None,
                 handles_multiple=False, attrs=None, requires_input=True,
                 datum=None):
        super(Action, self).__init__(datum=datum)
        # Priority: constructor, class-defined, fallback
        self.verbose_name = verbose_name or getattr(self, 'verbose_name',
                                                    self.name.title())
        self.verbose_name_plural = verbose_name_plural or \
                                    getattr(self, 'verbose_name_plural',
                                           "%ss" % self.verbose_name)
        self.handles_multiple = getattr(self,
                                        "handles_multiple",
                                        handles_multiple)
        self.requires_input = getattr(self,
                                      "requires_input",
                                      requires_input)
        if attrs:
            self.attrs.update(attrs)

        # Don't set these if they're None
        if single_func:
            self.single = single_func
        if multiple_func:
            self.multiple = multiple_func
        if handle_func:
            self.handle = handle_func

        # Ensure we have the appropriate methods
        has_handler = hasattr(self, 'handle') and callable(self.handle)
        has_single = hasattr(self, 'single') and callable(self.single)
        has_multiple = hasattr(self, 'multiple') and callable(self.multiple)

        if has_handler or has_multiple:
            self.handles_multiple = True

        if not has_handler and (not has_single or has_multiple):
            cls_name = self.__class__.__name__
            raise NotImplementedError('You must define either a "handle" '
                                      'method or a "single" or "multiple" '
                                      'method on %s.' % cls_name)

        if not has_single:
            def single(self, data_table, request, object_id):
                return self.handle(data_table, request, [object_id])
            self.single = new.instancemethod(single, self)

        if not has_multiple and self.handles_multiple:
            def multiple(self, data_table, request, object_ids):
                return self.handle(data_table, request, object_ids)
            self.multiple = new.instancemethod(multiple, self)

    def get_param_name(self):
        """ Returns the full POST parameter name for this action.

        Defaults to
        ``{{ table.name }}__{{ action.name }}``.
        """
        return "__".join([self.table.name, self.name])


class LinkAction(BaseAction):
    """ A table action which is simply a link rather than a form POST.

    .. attribute:: name

        Required. The short name or "slug" representing this
        action. This name should not be changed at runtime.

    .. attribute:: verbose_name

        A string which will be rendered as the link text. (Required)

    .. attribute:: url

        A string or a callable which resolves to a url to be used as the link
        target. You must either define the ``url`` attribute or a override
        the ``get_link_url`` method on the class.
    """
    method = "GET"
    bound_url = None

    def __init__(self, verbose_name=None, url=None, attrs=None):
        super(LinkAction, self).__init__()
        self.verbose_name = verbose_name or getattr(self,
                                            "verbose_name",
                                            self.name.title())
        self.url = getattr(self, "url", url)
        if not self.verbose_name:
            raise NotImplementedError('A LinkAction object must have a '
                                      'verbose_name attribute.')
        if attrs:
            self.attrs.update(attrs)

    def get_link_url(self, datum=None):
        """ Returns the final URL based on the value of ``url``.

        If ``url`` is callable it will call the function.
        If not, it will then try to call ``reverse`` on ``url``.
        Failing that, it will simply return the value of ``url`` as-is.

        When called for a row action, the current row data object will be
        passed as the first parameter.
        """
        if not self.url:
            raise NotImplementedError('A LinkAction class must have a '
                                      'url attribute or define its own '
                                      'get_link_url method.')
        if callable(self.url):
            return self.url(datum, **self.kwargs)
        try:
            if datum:
                obj_id = self.table.get_object_id(datum)
                return urlresolvers.reverse(self.url, args=(obj_id,))
            else:
                return urlresolvers.reverse(self.url)
        except urlresolvers.NoReverseMatch, ex:
            LOG.info('No reverse found for "%s": %s' % (self.url, ex))
            return self.url


class FilterAction(BaseAction):
    """ A base class representing a filter action for a table.

    .. attribute:: name

        The short name or "slug" representing this action. Defaults to
        ``"filter"``.

    .. attribute:: verbose_name

        A descriptive name used for display purposes. Defaults to the
        value of ``name`` with the first letter of each word capitalized.

    .. attribute:: param_name

        A string representing the name of the request parameter used for the
        search term. Default: ``"q"``.
    """
    # TODO(gabriel): The method for a filter action should be a GET,
    # but given the form structure of the table that's currently impossible.
    # At some future date this needs to be reworked to get the filter action
    # separated from the table's POST form.
    method = "POST"
    name = "filter"
    verbose_name = _("Filter")

    def __init__(self, verbose_name=None, param_name=None):
        super(FilterAction, self).__init__()
        self.verbose_name = verbose_name or self.name
        self.param_name = param_name or 'q'

    def get_param_name(self):
        """ Returns the full query parameter name for this action.

        Defaults to
        ``{{ table.name }}__{{ action.name }}__{{ action.param_name }}``.
        """
        return "__".join([self.table.name, self.name, self.param_name])

    def get_default_classes(self):
        classes = super(FilterAction, self).get_default_classes()
        classes += ("btn-search",)
        return classes

    def filter(self, table, data, filter_string):
        """ Provides the actual filtering logic.

        This method must be overridden by subclasses and return
        the filtered data.
        """
        raise NotImplementedError("The filter method has not been implemented "
                                  "by %s." % self.__class__)


class BatchAction(Action):
    """ A table action which takes batch action on one or more
        objects. This action should not require user input on a
        per-object basis.

    .. attribute:: name

       An internal name for this action.

    .. attribute:: action_present

       String or tuple/list. The display forms of the name.
       Should be a transitive verb, capitalized and translated. ("Delete",
       "Rotate", etc.) If tuple or list - then setting
       self.current_present_action = n will set the current active item
       from the list(action_present[n])

    .. attribute:: action_past

       String or tuple/list. The past tense of action_present. ("Deleted",
       "Rotated", etc.) If tuple or list - then
       setting self.current_past_action = n will set the current active item
       from the list(action_past[n])

    .. attribute:: data_type_singular

       A display name for the type of data that receives the
       action. ("Keypair", "Floating IP", etc.)

    .. attribute:: data_type_plural

       Optional plural word for the type of data being acted
       on. Defaults to appending 's'. Relying on the default is bad
       for translations and should not be done.

    .. attribute:: success_url

       Optional location to redirect after completion of the delete
       action. Defaults to the current page.
    """
    completion_url = None

    def __init__(self):
        self.current_present_action = 0
        self.current_past_action = 0
        self.data_type_plural = getattr(self, 'data_type_plural',
                                        self.data_type_singular + 's')
        self.verbose_name = getattr(self, "verbose_name",
                                    self._conjugate())
        self.verbose_name_plural = getattr(self, "verbose_name_plural",
                                           self._conjugate('plural'))
        super(BatchAction, self).__init__()

    def _allowed(self, request, datum=None):
        # Override the default internal action method to prevent batch
        # actions from appearing on tables with no data.
        if not self.table.data and not datum:
            return False
        return super(BatchAction, self)._allowed(request, datum)

    def _conjugate(self, items=None, past=False):
        """
        Builds combinations like 'Delete Object' and 'Deleted
        Objects' based on the number of items and `past` flag.
        """
        action_type = "past" if past else "present"
        action_attr = getattr(self, "action_%s" % action_type)
        if isinstance(action_attr, (basestring, Promise)):
            action = action_attr
        else:
            toggle_selection = getattr(self, "current_%s_action" % action_type)
            action = action_attr[toggle_selection]
        if items is None or len(items) == 1:
            data_type = self.data_type_singular
        else:
            data_type = self.data_type_plural
        return string_concat(action, ' ', data_type)

    def action(self, request, datum_id):
        """
        Required. Accepts a single object id and performs the specific action.

        Return values are discarded, errors raised are caught and logged.
        """
        raise NotImplementedError('action() must be defined for '
                                  'BatchAction: %s' % self.data_type_singular)

    def update(self, request, datum):
        """
        Switches the action verbose name, if needed
        """
        if getattr(self, 'action_present', False):
            self.verbose_name = self._conjugate()
            self.verbose_name_plural = self._conjugate('plural')

    def get_success_url(self, request=None):
        """
        Returns the URL to redirect to after a successful action.
        """
        if self.completion_url:
            return self.completion_url
        return request.get_full_path()

    def handle(self, table, request, obj_ids):
        action_success = []
        action_failure = []
        action_not_allowed = []
        for datum_id in obj_ids:
            datum = table.get_object_by_id(datum_id)
            datum_display = table.get_object_display(datum)
            if not table._filter_action(self, request, datum):
                action_not_allowed.append(datum_display)
                LOG.info('Permission denied to %s: "%s"' %
                         (self._conjugate(past=True).lower(), datum_display))
                continue
            try:
                self.action(request, datum_id)
                #Call update to invoke changes if needed
                self.update(request, datum)
                action_success.append(datum_display)
                LOG.info('%s: "%s"' %
                         (self._conjugate(past=True), datum_display))
            except:
                # Handle the exception but silence it since we'll display
                # an aggregate error message later. Otherwise we'd get
                # multiple error messages displayed to the user.
                exceptions.handle(request, ignore=True)
                action_failure.append(datum_display)

        #Begin with success message class, downgrade to info if problems
        success_message_level = messages.success
        if action_not_allowed:
            msg = _('You do not have permission to %(action)s: %(objs)s')
            params = {"action": self._conjugate(action_not_allowed).lower(),
                      "objs": ", ".join(action_not_allowed)}
            messages.error(request, msg % params)
            success_message_level = messages.info
        if action_failure:
            msg = _('Unable to %(action)s: %(objs)s')
            params = {"action": self._conjugate(action_failure).lower(),
                      "objs": ", ".join(action_failure)}
            messages.error(request, msg % params)
            success_message_level = messages.info
        if action_success:
            msg = _('%(action)s: %(objs)s')
            params = {"action": self._conjugate(action_success, True),
                      "objs": ", ".join(action_success)}
            success_message_level(request, msg % params)

        return shortcuts.redirect(self.get_success_url(request))


class DeleteAction(BatchAction):
    name = "delete"
    action_present = _("Delete")
    action_past = _("Deleted")

    def action(self, request, obj_id):
        return self.delete(request, obj_id)

    def delete(self, request, obj_id):
        raise NotImplementedError("DeleteAction must define a delete method.")

    def get_default_classes(self):
        classes = super(DeleteAction, self).get_default_classes()
        classes += ("btn-danger", "btn-delete")
        return classes
