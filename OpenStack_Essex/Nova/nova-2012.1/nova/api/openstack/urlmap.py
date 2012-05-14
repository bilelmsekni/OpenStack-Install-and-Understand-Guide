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

import paste.urlmap
import re
import urllib2

from nova import log as logging
from nova.api.openstack import wsgi


_quoted_string_re = r'"[^"\\]*(?:\\.[^"\\]*)*"'
_option_header_piece_re = re.compile(r';\s*([^\s;=]+|%s)\s*'
                                     r'(?:=\s*([^;]+|%s))?\s*' %
    (_quoted_string_re, _quoted_string_re))

LOG = logging.getLogger(__name__)


def unquote_header_value(value):
    """Unquotes a header value.
    This does not use the real unquoting but what browsers are actually
    using for quoting.

    :param value: the header value to unquote.
    """
    if value and value[0] == value[-1] == '"':
        # this is not the real unquoting, but fixing this so that the
        # RFC is met will result in bugs with internet explorer and
        # probably some other browsers as well.  IE for example is
        # uploading files with "C:\foo\bar.txt" as filename
        value = value[1:-1]
    return value


def parse_list_header(value):
    """Parse lists as described by RFC 2068 Section 2.

    In particular, parse comma-separated lists where the elements of
    the list may include quoted-strings.  A quoted-string could
    contain a comma.  A non-quoted string could have quotes in the
    middle.  Quotes are removed automatically after parsing.

    The return value is a standard :class:`list`:

    >>> parse_list_header('token, "quoted value"')
    ['token', 'quoted value']

    :param value: a string with a list header.
    :return: :class:`list`
    """
    result = []
    for item in urllib2.parse_http_list(value):
        if item[:1] == item[-1:] == '"':
            item = unquote_header_value(item[1:-1])
        result.append(item)
    return result


def parse_options_header(value):
    """Parse a ``Content-Type`` like header into a tuple with the content
    type and the options:

    >>> parse_options_header('Content-Type: text/html; mimetype=text/html')
    ('Content-Type:', {'mimetype': 'text/html'})

    :param value: the header to parse.
    :return: (str, options)
    """
    def _tokenize(string):
        for match in _option_header_piece_re.finditer(string):
            key, value = match.groups()
            key = unquote_header_value(key)
            if value is not None:
                value = unquote_header_value(value)
            yield key, value

    if not value:
        return '', {}

    parts = _tokenize(';' + value)
    name = parts.next()[0]
    extra = dict(parts)
    return name, extra


class Accept(object):
    def __init__(self, value):
        self._content_types = [parse_options_header(v) for v in
                               parse_list_header(value)]

    def best_match(self, supported_content_types):
        # FIXME: Should we have a more sophisticated matching algorithm that
        # takes into account the version as well?
        best_quality = -1
        best_content_type = None
        best_params = {}
        best_match = '*/*'

        for content_type in supported_content_types:
            for content_mask, params in self._content_types:
                try:
                    quality = float(params.get('q', 1))
                except ValueError:
                    continue

                if quality < best_quality:
                    continue
                elif best_quality == quality:
                    if best_match.count('*') <= content_mask.count('*'):
                        continue

                if self._match_mask(content_mask, content_type):
                    best_quality = quality
                    best_content_type = content_type
                    best_params = params
                    best_match = content_mask

        return best_content_type, best_params

    def content_type_params(self, best_content_type):
        """Find parameters in Accept header for given content type."""
        for content_type, params in self._content_types:
            if best_content_type == content_type:
                return params

        return {}

    def _match_mask(self, mask, content_type):
        if '*' not in mask:
            return content_type == mask
        if mask == '*/*':
            return True
        mask_major = mask[:-2]
        content_type_major = content_type.split('/', 1)[0]
        return content_type_major == mask_major


def urlmap_factory(loader, global_conf, **local_conf):
    if 'not_found_app' in local_conf:
        not_found_app = local_conf.pop('not_found_app')
    else:
        not_found_app = global_conf.get('not_found_app')
    if not_found_app:
        not_found_app = loader.get_app(not_found_app, global_conf=global_conf)
    urlmap = URLMap(not_found_app=not_found_app)
    for path, app_name in local_conf.items():
        path = paste.urlmap.parse_path_expression(path)
        app = loader.get_app(app_name, global_conf=global_conf)
        urlmap[path] = app
    return urlmap


class URLMap(paste.urlmap.URLMap):
    def _match(self, host, port, path_info):
        """Find longest match for a given URL path."""
        for (domain, app_url), app in self.applications:
            if domain and domain != host and domain != host + ':' + port:
                continue
            if (path_info == app_url
                or path_info.startswith(app_url + '/')):
                return app, app_url

        return None, None

    def _set_script_name(self, app, app_url):
        def wrap(environ, start_response):
            environ['SCRIPT_NAME'] += app_url
            return app(environ, start_response)

        return wrap

    def _munge_path(self, app, path_info, app_url):
        def wrap(environ, start_response):
            environ['SCRIPT_NAME'] += app_url
            environ['PATH_INFO'] = path_info[len(app_url):]
            return app(environ, start_response)

        return wrap

    def _path_strategy(self, host, port, path_info):
        """Check path suffix for MIME type and path prefix for API version."""
        mime_type = app = app_url = None

        parts = path_info.rsplit('.', 1)
        if len(parts) > 1:
            possible_type = 'application/' + parts[1]
            if possible_type in wsgi.SUPPORTED_CONTENT_TYPES:
                mime_type = possible_type

        parts = path_info.split('/')
        if len(parts) > 1:
            possible_app, possible_app_url = self._match(host, port, path_info)
            # Don't use prefix if it ends up matching default
            if possible_app and possible_app_url:
                app_url = possible_app_url
                app = self._munge_path(possible_app, path_info, app_url)

        return mime_type, app, app_url

    def _content_type_strategy(self, host, port, environ):
        """Check Content-Type header for API version."""
        app = None
        params = parse_options_header(environ.get('CONTENT_TYPE', ''))[1]
        if 'version' in params:
            app, app_url = self._match(host, port, '/v' + params['version'])
            if app:
                app = self._set_script_name(app, app_url)

        return app

    def _accept_strategy(self, host, port, environ, supported_content_types):
        """Check Accept header for best matching MIME type and API version."""
        accept = Accept(environ.get('HTTP_ACCEPT', ''))

        app = None

        # Find the best match in the Accept header
        mime_type, params = accept.best_match(supported_content_types)
        if 'version' in params:
            app, app_url = self._match(host, port, '/v' + params['version'])
            if app:
                app = self._set_script_name(app, app_url)

        return mime_type, app

    def __call__(self, environ, start_response):
        host = environ.get('HTTP_HOST', environ.get('SERVER_NAME')).lower()
        if ':' in host:
            host, port = host.split(':', 1)
        else:
            if environ['wsgi.url_scheme'] == 'http':
                port = '80'
            else:
                port = '443'

        path_info = environ['PATH_INFO']
        path_info = self.normalize_url(path_info, False)[1]

        # The MIME type for the response is determined in one of two ways:
        # 1) URL path suffix (eg /servers/detail.json)
        # 2) Accept header (eg application/json;q=0.8, application/xml;q=0.2)

        # The API version is determined in one of three ways:
        # 1) URL path prefix (eg /v1.1/tenant/servers/detail)
        # 2) Content-Type header (eg application/json;version=1.1)
        # 3) Accept header (eg application/json;q=0.8;version=1.1)

        supported_content_types = list(wsgi.SUPPORTED_CONTENT_TYPES)

        mime_type, app, app_url = self._path_strategy(host, port, path_info)

        # Accept application/atom+xml for the index query of each API
        # version mount point as well as the root index
        if (app_url and app_url + '/' == path_info) or path_info == '/':
            supported_content_types.append('application/atom+xml')

        if not app:
            app = self._content_type_strategy(host, port, environ)

        if not mime_type or not app:
            possible_mime_type, possible_app = self._accept_strategy(
                    host, port, environ, supported_content_types)
            if possible_mime_type and not mime_type:
                mime_type = possible_mime_type
            if possible_app and not app:
                app = possible_app

        if not mime_type:
            mime_type = 'application/json'

        if not app:
            # Didn't match a particular version, probably matches default
            app, app_url = self._match(host, port, path_info)
            if app:
                app = self._munge_path(app, path_info, app_url)

        if app:
            environ['nova.best_content_type'] = mime_type
            return app(environ, start_response)

        environ['paste.urlmap_object'] = self
        return self.not_found_application(environ, start_response)
