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

import collections
import copy
import logging
from operator import attrgetter
import sys

from django import forms
from django.http import HttpResponse
from django import template
from django.conf import settings
from django.contrib import messages
from django.core import urlresolvers
from django.template.loader import render_to_string
from django.utils import http
from django.utils.datastructures import SortedDict
from django.utils.html import escape
from django.utils.http import urlencode
from django.utils.translation import ugettext_lazy as _
from django.utils.safestring import mark_safe
from django.utils import termcolors

from horizon import exceptions
from horizon.utils import html
from .actions import FilterAction, LinkAction


LOG = logging.getLogger(__name__)
PALETTE = termcolors.PALETTES[termcolors.DEFAULT_PALETTE]
STRING_SEPARATOR = "__"


class Column(html.HTMLElement):
    """ A class which represents a single column in a :class:`.DataTable`.

    .. attribute:: transform

        A string or callable. If ``transform`` is a string, it should be the
        name of the attribute on the underlying data class which
        should be displayed in this column. If it is a callable, it
        will be passed the current row's data at render-time and should
        return the contents of the cell. Required.

    .. attribute:: verbose_name

        The name for this column which should be used for display purposes.
        Defaults to the value of ``transform`` with the first letter
        of each word capitalized.

    .. attribute:: sortable

        Boolean to determine whether this column should be sortable or not.
        Defaults to False.

    .. attribute:: hidden

        Boolean to determine whether or not this column should be displayed
        when rendering the table. Default: ``False``.

    .. attribute:: link

        A string or callable which returns a URL which will be wrapped around
        this column's text as a link.

    .. attribute::  status

        Boolean designating whether or not this column represents a status
        (i.e. "enabled/disabled", "up/down", "active/inactive").
        Default: ``False``.

    .. attribute::  status_choices

        A tuple of tuples representing the possible data values for the
        status column and their associated boolean equivalent. Positive
        states should equate to ``True``, negative states should equate
        to ``False``, and indeterminate states should be ``None``.

        Values are compared in a case-insensitive manner.

        Example (these are also the default values)::

            status_choices = (
                    ('enabled', True),
                    ('true', True)
                    ('up', True),
                    ('active', True),
                    ('on', True),
                    ('none', None),
                    ('unknown', None),
                    ('', None),
                    ('disabled', False),
                    ('down', False),
                    ('false', False),
                    ('inactive', False),
                    ('off', False),
                )

    .. attribute:: empty_value

        A string to be used for cells which have no data. Defaults to an
        empty string.

    .. attribute:: filters

        A list of functions (often template filters) to be applied to the
        value of the data for this column prior to output. This is effectively
        a shortcut for writing a custom ``transform`` function in simple cases.

    .. attribute:: classes

        An iterable of CSS classes which should be added to this column.
        Example: ``classes=('foo', 'bar')``.

    .. attribute:: attrs

        A dict of HTML attribute strings which should be added to this column.
        Example: ``attrs={"data-foo": "bar"}``.
    """
    # Used to retain order when instantiating columns on a table
    creation_counter = 0
    # Used for special auto-generated columns
    auto = None

    transform = None
    name = None
    verbose_name = None
    status_choices = (
        ('enabled', True),
        ('true', True),
        ('up', True),
        ('active', True),
        ('on', True),
        ('none', None),
        ('unknown', None),
        ('', None),
        ('disabled', False),
        ('down', False),
        ('false', False),
        ('inactive', False),
        ('off', False),
    )

    def __init__(self, transform, verbose_name=None, sortable=False,
                 link=None, hidden=False, attrs=None, status=False,
                 status_choices=None, empty_value=None, filters=None,
                 classes=None):
        self.classes = classes or getattr(self, "classes", [])
        super(Column, self).__init__()
        self.attrs.update(attrs or {})

        if callable(transform):
            self.transform = transform
            self.name = transform.__name__
        else:
            self.transform = unicode(transform)
            self.name = self.transform
        self.sortable = sortable
        # Empty string is a valid value for verbose_name
        if verbose_name is None:
            verbose_name = self.transform.title()
        else:
            verbose_name = verbose_name
        self.verbose_name = verbose_name
        self.link = link
        self.hidden = hidden
        self.status = status
        self.empty_value = empty_value or '-'
        self.filters = filters or []
        if status_choices:
            self.status_choices = status_choices

        self.creation_counter = Column.creation_counter
        Column.creation_counter += 1

        if self.sortable:
            self.classes.append("sortable")
        if self.hidden:
            self.classes.append("hide")

    def __unicode__(self):
        return unicode(self.verbose_name)

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.name)

    def get_data(self, datum):
        """
        Returns the appropriate data for this column from the given input.

        The return value will be either the attribute specified for this column
        or the return value of the attr:`~horizon.tables.Column.transform`
        method for this column.
        """
        datum_id = self.table.get_object_id(datum)
        if datum_id in self.table._data_cache[self]:
            return self.table._data_cache[self][datum_id]

        # Callable transformations
        if callable(self.transform):
            data = self.transform(datum)
        # Basic object lookups
        elif hasattr(datum, self.transform):
            data = getattr(datum, self.transform, None)
        # Dict lookups
        elif isinstance(datum, collections.Iterable) and \
                self.transform in datum:
            data = datum.get(self.transform)
        else:
            if settings.DEBUG:
                msg = _("The attribute %(attr)s doesn't exist on "
                        "%(obj)s.") % {'attr': self.transform, 'obj': datum}
                msg = termcolors.colorize(msg, **PALETTE['ERROR'])
                LOG.warning(msg)
            data = None
        for filter_func in self.filters:
            data = filter_func(data)
        self.table._data_cache[self][datum_id] = data
        return self.table._data_cache[self][datum_id]

    def get_link_url(self, datum):
        """ Returns the final value for the column's ``link`` property.

        If ``link`` is a callable, it will be passed the current data object
        and should return a URL. Otherwise ``get_link_url`` will attempt to
        call ``reverse`` on ``link`` with the object's id as a parameter.
        Failing that, it will simply return the value of ``link``.
        """
        obj_id = self.table.get_object_id(datum)
        if callable(self.link):
            return self.link(datum)
        try:
            return urlresolvers.reverse(self.link, args=(obj_id,))
        except urlresolvers.NoReverseMatch:
            return self.link


class Row(html.HTMLElement):
    """ Represents a row in the table.

    When iterated, the ``Row`` instance will yield each of its cells.

    Rows are capable of AJAX updating, with a little added work:

    The ``ajax`` property needs to be set to ``True``, and
    subclasses need to define a ``get_data`` method which returns a data
    object appropriate for consumption by the table (effectively the "get"
    lookup versus the table's "list" lookup).

    The automatic update interval is configurable by setting the key
    ``ajax_poll_interval`` in the ``settings.HORIZON_CONFIG`` dictionary.
    Default: ``2500`` (measured in milliseconds).

    .. attribute:: table

        The table which this row belongs to.

    .. attribute:: datum

        The data object which this row represents.

    .. attribute:: id

        A string uniquely representing this row composed of the table name
        and the row data object's identifier.

    .. attribute:: cells

        The cells belonging to this row stored in a ``SortedDict`` object.
        This attribute is populated during instantiation.

    .. attribute:: status

        Boolean value representing the status of this row calculated from
        the values of the table's ``status_columns`` if they are set.

    .. attribute:: status_class

        Returns a css class for the status of the row based on ``status``.

    .. attribute:: ajax

        Boolean value to determine whether ajax updating for this row is
        enabled.

    .. attribute:: ajax_action_name

        String that is used for the query parameter key to request AJAX
        updates. Generally you won't need to change this value.
        Default: ``"row_update"``.
    """
    ajax = False
    ajax_action_name = "row_update"

    def __init__(self, table, datum=None):
        super(Row, self).__init__()
        self.table = table
        self.datum = datum
        if self.datum:
            self.load_cells()
        else:
            self.id = None
            self.cells = []

    def load_cells(self, datum=None):
        """
        Load the row's data (either provided at initialization or as an
        argument to this function), initiailize all the cells contained
        by this row, and set the appropriate row properties which require
        the row's data to be determined.

        This function is called automatically by
        :meth:`~horizon.tables.Row.__init__` if the ``datum`` argument is
        provided. However, by not providing the data during initialization
        this function allows for the possibility of a two-step loading
        pattern when you need a row instance but don't yet have the data
        available.
        """
        # Compile all the cells on instantiation.
        table = self.table
        if datum:
            self.datum = datum
        else:
            datum = self.datum
        cells = []
        for column in table.columns.values():
            if column.auto == "multi_select":
                widget = forms.CheckboxInput(check_test=False)
                # Convert value to string to avoid accidental type conversion
                data = widget.render('object_ids',
                                     unicode(table.get_object_id(datum)))
                table._data_cache[column][table.get_object_id(datum)] = data
            elif column.auto == "actions":
                data = table.render_row_actions(datum)
                table._data_cache[column][table.get_object_id(datum)] = data
            else:
                data = column.get_data(datum)
            cell = Cell(datum, data, column, self)
            cells.append((column.name or column.auto, cell))
        self.cells = SortedDict(cells)

        if self.ajax:
            interval = settings.HORIZON_CONFIG.get('ajax_poll_interval', 2500)
            self.attrs['data-update-interval'] = interval
            self.attrs['data-update-url'] = self.get_ajax_update_url()
            self.classes.append("ajax-update")

        # Add the row's status class and id to the attributes to be rendered.
        self.classes.append(self.status_class)
        id_vals = {"table": self.table.name,
                   "sep": STRING_SEPARATOR,
                   "id": table.get_object_id(datum)}
        self.id = "%(table)s%(sep)srow%(sep)s%(id)s" % id_vals
        self.attrs['id'] = self.id

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.id)

    def __iter__(self):
        return iter(self.cells.values())

    @property
    def status(self):
        column_names = self.table._meta.status_columns
        if column_names:
            statuses = dict([(column_name, self.cells[column_name].status) for
                             column_name in column_names])
            return self.table.calculate_row_status(statuses)

    @property
    def status_class(self):
        column_names = self.table._meta.status_columns
        if column_names:
            return self.table.get_row_status_class(self.status)
        else:
            return ''

    def render(self):
        return render_to_string("horizon/common/_data_table_row.html",
                                {"row": self})

    def get_cells(self):
        """ Returns the bound cells for this row in order. """
        return self.cells.values()

    def get_ajax_update_url(self):
        table_url = self.table.get_absolute_url()
        params = urlencode({"table": self.table.name,
                            "action": self.ajax_action_name,
                            "obj_id": self.table.get_object_id(self.datum)})
        return "%s?%s" % (table_url, params)

    def get_data(self, request, obj_id):
        """
        Fetches the updated data for the row based on the object id
        passed in. Must be implemented by a subclass to allow AJAX updating.
        """
        raise NotImplementedError("You must define a get_data method on %s"
                                  % self.__class__.__name__)


class Cell(html.HTMLElement):
    """ Represents a single cell in the table. """
    def __init__(self, datum, data, column, row, attrs=None, classes=None):
        self.classes = classes or getattr(self, "classes", [])
        super(Cell, self).__init__()
        self.attrs.update(attrs or {})

        self.datum = datum
        self.data = data
        self.column = column
        self.row = row

    def __repr__(self):
        return '<%s: %s, %s>' % (self.__class__.__name__,
                                 self.column.name,
                                 self.row.id)

    @property
    def value(self):
        """
        Returns a formatted version of the data for final output.

        This takes into consideration the
        :attr:`~horizon.tables.Column.link`` and
        :attr:`~horizon.tables.Column.empty_value`
        attributes.
        """
        try:
            data = self.column.get_data(self.datum) or self.column.empty_value
        except:
            data = None
            exc_info = sys.exc_info()
            raise template.TemplateSyntaxError, exc_info[1], exc_info[2]
        if self.column.link:
            url = self.column.get_link_url(self.datum)
            if url:
                # Escape the data inside while allowing our HTML to render
                data = mark_safe('<a href="%s">%s</a>' % (url, escape(data)))
        return data

    @property
    def status(self):
        """ Gets the status for the column based on the cell's data. """
        # Deal with status column mechanics based in this cell's data
        if hasattr(self, '_status'):
            return self._status

        if self.column.status or \
                self.column.name in self.column.table._meta.status_columns:
            #returns the first matching status found
            data_value_lower = unicode(self.data).lower()
            for status_name, status_value in self.column.status_choices:
                if unicode(status_name).lower() == data_value_lower:
                    self._status = status_value
                    return self._status
        self._status = None
        return self._status

    def get_status_class(self, status):
        """ Returns a css class name determined by the status value. """
        if status is True:
            return "status_up"
        elif status is False:
            return "status_down"
        else:
            return "status_unknown"

    def get_default_classes(self):
        """ Returns a flattened string of the cell's CSS classes. """
        column_class_string = self.column.get_final_attrs().get('class', "")
        classes = set(column_class_string.split(" "))
        if self.column.status:
            classes.add(self.get_status_class(self.status))
        return list(classes)


class DataTableOptions(object):
    """ Contains options for :class:`.DataTable` objects.

    .. attribute:: name

        A short name or slug for the table.

    .. attribute:: verbose_name

        A more verbose name for the table meant for display purposes.

    .. attribute:: columns

        A list of column objects or column names. Controls ordering/display
        of the columns in the table.

    .. attribute:: table_actions

        A list of action classes derived from the :class:`.Action` class.
        These actions will handle tasks such as bulk deletion, etc. for
        multiple objects at once.

    .. attribute:: row_actions

        A list similar to ``table_actions`` except tailored to appear for
        each row. These actions act on a single object at a time.

    .. attribute:: actions_column

        Boolean value to control rendering of an additional column containing
        the various actions for each row. Defaults to ``True`` if any actions
        are specified in the ``row_actions`` option.

    .. attribute:: multi_select

        Boolean value to control rendering of an extra column with checkboxes
        for selecting multiple objects in the table. Defaults to ``True`` if
        any actions are specified in the ``table_actions`` option.

    .. attribute:: filter

        Boolean value to control the display of the "filter" search box
        in the table actions. By default it checks whether or not an instance
        of :class:`.FilterAction` is in :attr:`.table_actions`.

    .. attribute:: template

        String containing the template which should be used to render the
        table. Defaults to ``"horizon/common/_data_table.html"``.

    .. attribute:: context_var_name

        The name of the context variable which will contain the table when
        it is rendered. Defaults to ``"table"``.

    .. attribute:: status_columns

        A list or tuple of column names which represents the "state"
        of the data object being represented.

        If ``status_columns`` is set, when the rows are rendered the value
        of this column will be used to add an extra class to the row in
        the form of ``"status_up"`` or ``"status_down"`` for that row's
        data.

        The row status is used by other Horizon components to trigger tasks
        such as dynamic AJAX updating.

    .. attribute:: row_class

        The class which should be used for rendering the rows of this table.
        Optional. Default: :class:`~horizon.tables.Row`.

    .. attribute:: column_class

        The class which should be used for handling the columns of this table.
        Optional. Default: :class:`~horizon.tables.Column`.
    """
    def __init__(self, options):
        self.name = getattr(options, 'name', self.__class__.__name__)
        verbose_name = getattr(options, 'verbose_name', None) \
                                    or self.name.title()
        self.verbose_name = verbose_name
        self.columns = getattr(options, 'columns', None)
        self.status_columns = getattr(options, 'status_columns', [])
        self.table_actions = getattr(options, 'table_actions', [])
        self.row_actions = getattr(options, 'row_actions', [])
        self.row_class = getattr(options, 'row_class', Row)
        self.column_class = getattr(options, 'column_class', Column)

        # Set self.filter if we have any FilterActions
        filter_actions = [action for action in self.table_actions if
                          issubclass(action, FilterAction)]
        if len(filter_actions) > 1:
            raise NotImplementedError("Multiple filter actions is not "
                                      "currently supported.")
        self.filter = getattr(options, 'filter', len(filter_actions) > 0)
        if len(filter_actions) == 1:
            self._filter_action = filter_actions.pop()
        else:
            self._filter_action = None

        self.template = 'horizon/common/_data_table.html'
        self.row_actions_template = \
                        'horizon/common/_data_table_row_actions.html'
        self.table_actions_template = \
                        'horizon/common/_data_table_table_actions.html'
        self.context_var_name = unicode(getattr(options,
                                                'context_var_nam',
                                                'table'))
        self.actions_column = getattr(options,
                                     'actions_column',
                                     len(self.row_actions) > 0)
        self.multi_select = getattr(options,
                                    'multi_select',
                                    len(self.table_actions) > 0)

        # Set runtime table defaults; not configurable.
        self.has_more_data = False


class DataTableMetaclass(type):
    """ Metaclass to add options to DataTable class and collect columns. """
    def __new__(mcs, name, bases, attrs):
        # Process options from Meta
        attrs["_meta"] = opts = DataTableOptions(attrs.get("Meta", None))

        # Gather columns; this prevents the column from being an attribute
        # on the DataTable class and avoids naming conflicts.
        columns = []
        for name, obj in attrs.items():
            if issubclass(type(obj), (opts.column_class, Column)):
                column_instance = attrs.pop(name)
                column_instance.name = name
                columns.append((name, column_instance))
        columns.sort(key=lambda x: x[1].creation_counter)

        # Iterate in reverse to preserve final order
        for base in bases[::-1]:
            if hasattr(base, 'base_columns'):
                columns = base.base_columns.items() + columns
        attrs['base_columns'] = SortedDict(columns)

        if opts.columns:
            # Remove any columns that weren't declared if we're being explicit
            # NOTE: we're iterating a COPY of the list here!
            for column_data in columns[:]:
                if column_data[0] not in opts.columns:
                    columns.pop(columns.index(column_data))
            # Re-order based on declared columns
            columns.sort(key=lambda x: attrs['_meta'].columns.index(x[0]))
        # Add in our auto-generated columns
        if opts.multi_select:
            multi_select = opts.column_class("multi_select",
                                             verbose_name="")
            multi_select.classes.append('multi_select_column')
            multi_select.auto = "multi_select"
            columns.insert(0, ("multi_select", multi_select))
        if opts.actions_column:
            actions_column = opts.column_class("actions",
                                               verbose_name=_("Actions"))
            actions_column.classes.append('actions_column')
            actions_column.auto = "actions"
            columns.append(("actions", actions_column))
        # Store this set of columns internally so we can copy them per-instance
        attrs['_columns'] = SortedDict(columns)

        # Gather and register actions for later access since we only want
        # to instantiate them once.
        # (list() call gives deterministic sort order, which sets don't have.)
        actions = list(set(opts.row_actions) | set(opts.table_actions))
        actions.sort(key=attrgetter('name'))
        actions_dict = SortedDict([(action.name, action()) \
                                   for action in actions])
        attrs['base_actions'] = actions_dict
        if opts._filter_action:
            # Replace our filter action with the instantiated version
            opts._filter_action = actions_dict[opts._filter_action.name]

        # Create our new class!
        return type.__new__(mcs, name, bases, attrs)


class DataTable(object):
    """ A class which defines a table with all data and associated actions.

    .. attribute:: name

        String. Read-only access to the name specified in the
        table's Meta options.

    .. attribute:: multi_select

        Boolean. Read-only access to whether or not this table
        should display a column for multi-select checkboxes.

    .. attribute:: data

        Read-only access to the data this table represents.

    .. attribute:: filtered_data

        Read-only access to the data this table represents, filtered by
        the :meth:`~horizon.tables.FilterAction.filter` method of the table's
        :class:`~horizon.tables.FilterAction` class (if one is provided)
        using the current request's query parameters.
    """
    __metaclass__ = DataTableMetaclass

    def __init__(self, request, data=None, **kwargs):
        self._meta.request = request
        self._meta.data = data
        self.kwargs = kwargs

        # Create a new set
        columns = []
        for key, _column in self._columns.items():
            column = copy.copy(_column)
            column.table = self
            columns.append((key, column))
        self.columns = SortedDict(columns)
        self._populate_data_cache()

        # Associate these actions with this table
        for action in self.base_actions.values():
            action.table = self

    def __unicode__(self):
        return unicode(self._meta.verbose_name)

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.name)

    @property
    def name(self):
        return self._meta.name

    @property
    def data(self):
        return self._meta.data

    @data.setter
    def data(self, data):
        self._meta.data = data

    @property
    def multi_select(self):
        return self._meta.multi_select

    @property
    def filtered_data(self):
        if not hasattr(self, '_filtered_data'):
            self._filtered_data = self.data
            if self._meta.filter and self._meta._filter_action:
                action = self._meta._filter_action
                filter_string = self.get_filter_string()
                request_method = self._meta.request.method
                if filter_string and request_method == action.method:
                    self._filtered_data = action.filter(self,
                                                        self.data,
                                                        filter_string)
        return self._filtered_data

    def get_filter_string(self):
        filter_action = self._meta._filter_action
        param_name = filter_action.get_param_name()
        filter_string = self._meta.request.POST.get(param_name, '')
        return filter_string

    def _populate_data_cache(self):
        self._data_cache = {}
        # Set up hash tables to store data points for each column
        for column in self.get_columns():
            self._data_cache[column] = {}

    def _filter_action(self, action, request, datum=None):
        try:
            # Catch user errors in permission functions here
            return action._allowed(request, datum)
        except Exception:
            LOG.exception("Error while checking action permissions.")
            return None

    def render(self):
        """ Renders the table using the template from the table options. """
        table_template = template.loader.get_template(self._meta.template)
        extra_context = {self._meta.context_var_name: self}
        context = template.RequestContext(self._meta.request, extra_context)
        return table_template.render(context)

    def get_absolute_url(self):
        """ Returns the canonical URL for this table.

        This is used for the POST action attribute on the form element
        wrapping the table. In many cases it is also useful for redirecting
        after a successful action on the table.

        For convenience it defaults to the value of
        ``request.get_full_path()`` with any query string stripped off,
        e.g. the path at which the table was requested.
        """
        return self._meta.request.get_full_path().partition('?')[0]

    def get_empty_message(self):
        """ Returns the message to be displayed when there is no data. """
        return _("No items to display.")

    def get_object_by_id(self, lookup):
        """
        Returns the data object from the table's dataset which matches
        the ``lookup`` parameter specified. An error will be raised if
        the match is not a single data object.

        Uses :meth:`~horizon.tables.DataTable.get_object_id` internally.
        """
        matches = [datum for datum in self.data if
                   self.get_object_id(datum) == lookup]
        if len(matches) > 1:
            raise ValueError("Multiple matches were returned for that id: %s."
                           % matches)
        if not matches:
            raise exceptions.Http302(self.get_absolute_url(),
                                     _('No match returned for the id "%s".')
                                       % lookup)
        return matches[0]

    def get_table_actions(self):
        """ Returns a list of the action instances for this table. """
        bound_actions = [self.base_actions[action.name] for
                         action in self._meta.table_actions]
        return [action for action in bound_actions if
                self._filter_action(action, self._meta.request)]

    def get_row_actions(self, datum):
        """ Returns a list of the action instances for a specific row. """
        bound_actions = []
        for action in self._meta.row_actions:
            # Copy to allow modifying properties per row
            bound_action = copy.copy(self.base_actions[action.name])
            bound_action.attrs = copy.copy(bound_action.attrs)
            bound_action.datum = datum
            # Remove disallowed actions.
            if not self._filter_action(bound_action,
                                       self._meta.request,
                                       datum):
                continue
            # Hook for modifying actions based on data. No-op by default.
            bound_action.update(self._meta.request, datum)
            # Pre-create the URL for this link with appropriate parameters
            if issubclass(bound_action.__class__, LinkAction):
                bound_action.bound_url = bound_action.get_link_url(datum)
            bound_actions.append(bound_action)
        return bound_actions

    def render_table_actions(self):
        """ Renders the actions specified in ``Meta.table_actions``. """
        template_path = self._meta.table_actions_template
        table_actions_template = template.loader.get_template(template_path)
        bound_actions = self.get_table_actions()
        extra_context = {"table_actions": bound_actions}
        if self._meta.filter:
            extra_context["filter"] = self._meta._filter_action
        context = template.RequestContext(self._meta.request, extra_context)
        return table_actions_template.render(context)

    def render_row_actions(self, datum):
        """
        Renders the actions specified in ``Meta.row_actions`` using the
        current row data. """
        template_path = self._meta.row_actions_template
        row_actions_template = template.loader.get_template(template_path)
        bound_actions = self.get_row_actions(datum)
        extra_context = {"row_actions": bound_actions,
                         "row_id": self.get_object_id(datum)}
        context = template.RequestContext(self._meta.request, extra_context)
        return row_actions_template.render(context)

    @staticmethod
    def parse_action(action_string):
        """
        Parses the ``action`` parameter (a string) sent back with the
        POST data. By default this parses a string formatted as
        ``{{ table_name }}__{{ action_name }}__{{ row_id }}`` and returns
        each of the pieces. The ``row_id`` is optional.
        """
        if action_string:
            bits = action_string.split(STRING_SEPARATOR)
            bits.reverse()
            table = bits.pop()
            action = bits.pop()
            try:
                object_id = bits.pop()
            except IndexError:
                object_id = None
            return table, action, object_id

    def take_action(self, action_name, obj_id=None, obj_ids=None):
        """
        Locates the appropriate action and routes the object
        data to it. The action should return an HTTP redirect
        if successful, or a value which evaluates to ``False``
        if unsuccessful.
        """
        # See if we have a list of ids
        obj_ids = obj_ids or self._meta.request.POST.getlist('object_ids')
        action = self.base_actions.get(action_name, None)
        if not action or action.method != self._meta.request.method:
            # We either didn't get an action or we're being hacked. Goodbye.
            return None

        # Meanhile, back in Gotham...
        if not action.requires_input or obj_id or obj_ids:
            if obj_id:
                obj_id = self.sanitize_id(obj_id)
            if obj_ids:
                obj_ids = [self.sanitize_id(i) for i in obj_ids]
            # Single handling is easy
            if not action.handles_multiple:
                response = action.single(self, self._meta.request, obj_id)
            # Otherwise figure out what to pass along
            else:
                # Preference given to a specific id, since that implies
                # the user selected an action for just one row.
                if obj_id:
                    obj_ids = [obj_id]
                response = action.multiple(self, self._meta.request, obj_ids)
            return response
        elif action and action.requires_input and not (obj_id or obj_ids):
            messages.info(self._meta.request,
                          _("Please select a row before taking that action."))
        return None

    @classmethod
    def check_handler(cls, request):
        """ Determine whether the request should be handled by this table. """
        if request.method == "POST" and "action" in request.POST:
            table, action, obj_id = cls.parse_action(request.POST["action"])
        elif "table" in request.GET and "action" in request.GET:
            table = request.GET["table"]
            action = request.GET["action"]
            obj_id = request.GET.get("obj_id", None)
        else:
            table = action = obj_id = None
        return table, action, obj_id

    def maybe_preempt(self):
        """
        Determine whether the request should be handled by a preemptive action
        on this table or by an AJAX row update before loading any data.
        """
        request = self._meta.request
        table_name, action_name, obj_id = self.check_handler(request)

        if table_name == self.name:
            # Handle AJAX row updating.
            new_row = self._meta.row_class(self)
            if new_row.ajax and new_row.ajax_action_name == action_name:
                try:
                    datum = new_row.get_data(request, obj_id)
                    new_row.load_cells(datum)
                    error = False
                except:
                    datum = None
                    error = exceptions.handle(request, ignore=True)
                if request.is_ajax():
                    if not error:
                        return HttpResponse(new_row.render())
                    else:
                        return HttpResponse(status=error.status_code)

            preemptive_actions = [action for action in
                                  self.base_actions.values() if action.preempt]
            if action_name:
                for action in preemptive_actions:
                    if action.name == action_name:
                        handled = self.take_action(action_name, obj_id)
                        if handled:
                            return handled
        return None

    def maybe_handle(self):
        """
        Determine whether the request should be handled by any action on this
        table after data has been loaded.
        """
        request = self._meta.request
        table_name, action_name, obj_id = self.check_handler(request)
        if table_name == self.name and action_name:
            return self.take_action(action_name, obj_id)
        return None

    def sanitize_id(self, obj_id):
        """ Override to modify an incoming obj_id to match existing
        API data types or modify the format.
        """
        return obj_id

    def get_object_id(self, datum):
        """ Returns the identifier for the object this row will represent.

        By default this returns an ``id`` attribute on the given object,
        but this can be overridden to return other values.

        .. warning::

            Make sure that the value returned is a unique value for the id
            otherwise rendering issues can occur.
        """
        return datum.id

    def get_object_display(self, datum):
        """ Returns a display name that identifies this object.

        By default, this returns a ``name`` attribute from the given object,
        but this can be overriden to return other values.
        """
        return datum.name

    def has_more_data(self):
        """
        Returns a boolean value indicating whether there is more data
        available to this table from the source (generally an API).

        The method is largely meant for internal use, but if you want to
        override it to provide custom behavior you can do so at your own risk.
        """
        return self._meta.has_more_data

    def get_marker(self):
        """
        Returns the identifier for the last object in the current data set
        for APIs that use marker/limit-based paging.
        """
        return http.urlquote_plus(self.get_object_id(self.data[-1]))

    def calculate_row_status(self, statuses):
        """
        Returns a boolean value determining the overall row status
        based on the dictionary of column name to status mappings passed in.

        By default, it uses the following logic:

        #. If any statuses are ``False``, return ``False``.
        #. If no statuses are ``False`` but any or ``None``, return ``None``.
        #. If all statuses are ``True``, return ``True``.

        This provides the greatest protection against false positives without
        weighting any particular columns.

        The ``statuses`` parameter is passed in as a dictionary mapping
        column names to their statuses in order to allow this function to
        be overridden in such a way as to weight one column's status over
        another should that behavior be desired.
        """
        values = statuses.values()
        if any([status is False for status in values]):
            return False
        elif any([status is None for status in values]):
            return None
        else:
            return True

    def get_row_status_class(self, status):
        """
        Returns a css class name determined by the status value. This class
        name is used to indicate the status of the rows in the table if
        any ``status_columns`` have been specified.
        """
        if status is True:
            return "status_up"
        elif status is False:
            return "status_down"
        else:
            return "status_unknown"

    def get_columns(self):
        """ Returns this table's columns including auto-generated ones."""
        return self.columns.values()

    def get_rows(self):
        """ Return the row data for this table broken out by columns. """
        rows = []
        try:
            for datum in self.filtered_data:
                rows.append(self._meta.row_class(self, datum))
        except:
            # Exceptions can be swallowed at the template level here,
            # re-raising as a TemplateSyntaxError makes them visible.
            LOG.exception("Error while rendering table rows.")
            exc_info = sys.exc_info()
            raise template.TemplateSyntaxError, exc_info[1], exc_info[2]
        return rows
