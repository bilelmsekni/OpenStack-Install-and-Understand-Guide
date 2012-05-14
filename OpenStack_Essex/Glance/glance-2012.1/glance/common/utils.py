# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
System-level utilities and helper functions.
"""

import datetime
import errno
import logging
import os
import platform
import subprocess
import sys
import uuid

import iso8601

from glance.common import exception


logger = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def chunkreadable(iter, chunk_size=65536):
    """
    Wrap a readable iterator with a reader yielding chunks of
    a preferred size, otherwise leave iterator unchanged.

    :param iter: an iter which may also be readable
    :param chunk_size: maximum size of chunk
    """
    return chunkiter(iter, chunk_size) if hasattr(iter, 'read') else iter


def chunkiter(fp, chunk_size=65536):
    """
    Return an iterator to a file-like obj which yields fixed size chunks

    :param fp: a file-like object
    :param chunk_size: maximum size of chunk
    """
    while True:
        chunk = fp.read(chunk_size)
        if chunk:
            yield chunk
        else:
            break


def image_meta_to_http_headers(image_meta):
    """
    Returns a set of image metadata into a dict
    of HTTP headers that can be fed to either a Webob
    Request object or an httplib.HTTP(S)Connection object

    :param image_meta: Mapping of image metadata
    """
    headers = {}
    for k, v in image_meta.items():
        if v is not None:
            if k == 'properties':
                for pk, pv in v.items():
                    if pv is not None:
                        headers["x-image-meta-property-%s"
                                % pk.lower()] = unicode(pv)
            else:
                headers["x-image-meta-%s" % k.lower()] = unicode(v)
    return headers


def add_features_to_http_headers(features, headers):
    """
    Adds additional headers representing glance features to be enabled.

    :param headers: Base set of headers
    :param features: Map of enabled features
    """
    if features:
        for k, v in features.items():
            if v is not None:
                headers[k.lower()] = unicode(v)


def get_image_meta_from_headers(response):
    """
    Processes HTTP headers from a supplied response that
    match the x-image-meta and x-image-meta-property and
    returns a mapping of image metadata and properties

    :param response: Response to process
    """
    result = {}
    properties = {}

    if hasattr(response, 'getheaders'):  # httplib.HTTPResponse
        headers = response.getheaders()
    else:  # webob.Response
        headers = response.headers.items()

    for key, value in headers:
        key = str(key.lower())
        if key.startswith('x-image-meta-property-'):
            field_name = key[len('x-image-meta-property-'):].replace('-', '_')
            properties[field_name] = value or None
        elif key.startswith('x-image-meta-'):
            field_name = key[len('x-image-meta-'):].replace('-', '_')
            result[field_name] = value or None
    result['properties'] = properties
    if 'size' in result:
        try:
            result['size'] = int(result['size'])
        except ValueError:
            raise exception.Invalid
    for key in ('is_public', 'deleted', 'protected'):
        if key in result:
            result[key] = bool_from_string(result[key])
    return result


def bool_from_string(subject):
    """Interpret a string as a boolean-like value."""
    if isinstance(subject, bool):
        return subject
    elif isinstance(subject, int):
        return subject == 1
    if hasattr(subject, 'startswith'):  # str or unicode...
        if subject.strip().lower() in ('true', 'on', '1', 'yes', 'y'):
            return True
    return False


def import_class(import_str):
    """Returns a class from a string including module and class"""
    mod_str, _sep, class_str = import_str.rpartition('.')
    try:
        __import__(mod_str)
        return getattr(sys.modules[mod_str], class_str)
    except (ImportError, ValueError, AttributeError), e:
        raise exception.ImportFailure(import_str=import_str,
                                      reason=e)


def import_object(import_str):
    """Returns an object including a module or module and class"""
    try:
        __import__(import_str)
        return sys.modules[import_str]
    except ImportError:
        cls = import_class(import_str)
        return cls()


def generate_uuid():
    return str(uuid.uuid4())


def is_uuid_like(value):
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


def isotime(at=None):
    """Stringify time in ISO 8601 format"""
    if not at:
        at = datetime.datetime.utcnow()
    str = at.strftime(TIME_FORMAT)
    tz = at.tzinfo.tzname(None) if at.tzinfo else 'UTC'
    str += ('Z' if tz == 'UTC' else tz)
    return str


def parse_isotime(timestr):
    """Parse time from ISO 8601 format"""
    try:
        return iso8601.parse_date(timestr)
    except iso8601.ParseError as e:
        raise ValueError(e.message)
    except TypeError as e:
        raise ValueError(e.message)


def normalize_time(timestamp):
    """Normalize time in arbitrary timezone to UTC"""
    offset = timestamp.utcoffset()
    return timestamp.replace(tzinfo=None) - offset if offset else timestamp


def safe_mkdirs(path):
    try:
        os.makedirs(path)
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise


def safe_remove(path):
    try:
        os.remove(path)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise


class PrettyTable(object):
    """Creates an ASCII art table for use in bin/glance

    Example:

        ID  Name              Size         Hits
        --- ----------------- ------------ -----
        122 image                       22     0
    """
    def __init__(self):
        self.columns = []

    def add_column(self, width, label="", just='l'):
        """Add a column to the table

        :param width: number of characters wide the column should be
        :param label: column heading
        :param just: justification for the column, 'l' for left,
                     'r' for right
        """
        self.columns.append((width, label, just))

    def make_header(self):
        label_parts = []
        break_parts = []
        for width, label, _ in self.columns:
            # NOTE(sirp): headers are always left justified
            label_part = self._clip_and_justify(label, width, 'l')
            label_parts.append(label_part)

            break_part = '-' * width
            break_parts.append(break_part)

        label_line = ' '.join(label_parts)
        break_line = ' '.join(break_parts)
        return '\n'.join([label_line, break_line])

    def make_row(self, *args):
        row = args
        row_parts = []
        for data, (width, _, just) in zip(row, self.columns):
            row_part = self._clip_and_justify(data, width, just)
            row_parts.append(row_part)

        row_line = ' '.join(row_parts)
        return row_line

    @staticmethod
    def _clip_and_justify(data, width, just):
        # clip field to column width
        clipped_data = str(data)[:width]

        if just == 'r':
            # right justify
            justified = clipped_data.rjust(width)
        else:
            # left justify
            justified = clipped_data.ljust(width)

        return justified


def get_terminal_size():

    def _get_terminal_size_posix():
        import fcntl
        import struct
        import termios

        height_width = None

        try:
            height_width = struct.unpack('hh', fcntl.ioctl(sys.stderr.fileno(),
                                        termios.TIOCGWINSZ,
                                        struct.pack('HH', 0, 0)))
        except:
            pass

        if not height_width:
            try:
                p = subprocess.Popen(['stty', 'size'],
                                    shell=False,
                                    stdout=subprocess.PIPE,
                                    stderr=open(os.devnull, 'w'))
                result = p.communicate()
                if p.returncode == 0:
                    return tuple(int(x) for x in result[0].split())
            except:
                pass

        return height_width

    def _get_terminal_size_win32():
        try:
            from ctypes import windll, create_string_buffer
            handle = windll.kernel32.GetStdHandle(-12)
            csbi = create_string_buffer(22)
            res = windll.kernel32.GetConsoleScreenBufferInfo(handle, csbi)
        except:
            return None
        if res:
            import struct
            unpack_tmp = struct.unpack("hhhhHhhhhhh", csbi.raw)
            (bufx, bufy, curx, cury, wattr,
            left, top, right, bottom, maxx, maxy) = unpack_tmp
            height = bottom - top + 1
            width = right - left + 1
            return (height, width)
        else:
            return None

    def _get_terminal_size_unknownOS():
        raise NotImplementedError

    func = {'posix': _get_terminal_size_posix,
            'win32': _get_terminal_size_win32}

    height_width = func.get(platform.os.name, _get_terminal_size_unknownOS)()

    if height_width == None:
        raise exception.Invalid()

    for i in height_width:
        if not isinstance(i, int) or i <= 0:
            raise exception.Invalid()

    return height_width[0], height_width[1]
