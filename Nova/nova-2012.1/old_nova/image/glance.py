# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

"""Implementation of an image service that uses Glance as the backend"""

from __future__ import absolute_import

import copy
import datetime
import json
import random
import sys
import time
import urlparse

from glance.common import exception as glance_exception

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


GlanceClient = utils.import_class('glance.client.Client')


def _parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, host, port)
    :raises ValueError

    """
    o = urlparse.urlparse(image_href)
    port = o.port or 80
    host = o.netloc.split(':', 1)[0]
    image_id = o.path.split('/')[-1]
    return (image_id, host, port)


def _create_glance_client(context, host, port):
    if FLAGS.auth_strategy == 'keystone':
        # NOTE(dprince): Glance client just needs auth_tok right? Should we
        # add username and tenant to the creds below?
        creds = {'strategy': 'keystone',
                 'username': context.user_id,
                 'tenant': context.project_id}
        glance_client = GlanceClient(host, port, auth_tok=context.auth_token,
                                     creds=creds)
    else:
        glance_client = GlanceClient(host, port)
    return glance_client


def pick_glance_api_server():
    """Return which Glance API server to use for the request

    This method provides a very primitive form of load-balancing suitable for
    testing and sandbox environments. In production, it would be better to use
    one IP and route that to a real load-balancer.

        Returns (host, port)
    """
    host_port = random.choice(FLAGS.glance_api_servers)
    host, port_str = host_port.split(':')
    port = int(port_str)
    return host, port


def get_glance_client(context, image_href):
    """Get the correct glance client and id for the given image_href.

    The image_href param can be an href of the form
    http://myglanceserver:9292/images/42, or just an int such as 42. If the
    image_href is an int, then flags are used to create the default
    glance client.

    :param image_href: image ref/id for an image
    :returns: a tuple of the form (glance_client, image_id)

    """
    glance_host, glance_port = pick_glance_api_server()

    # check if this is an id
    if '/' not in str(image_href):
        glance_client = _create_glance_client(context,
                                              glance_host,
                                              glance_port)
        return (glance_client, image_href)

    else:
        try:
            (image_id, host, port) = _parse_image_ref(image_href)
        except ValueError:
            raise exception.InvalidImageRef(image_href=image_href)

        glance_client = _create_glance_client(context,
                                              glance_host,
                                              glance_port)
        return (glance_client, image_id)


class GlanceImageService(object):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self, client=None):
        self._client = client

    def _get_client(self, context):
        # NOTE(sirp): we want to load balance each request across glance
        # servers. Since GlanceImageService is a long-lived object, `client`
        # is made to choose a new server each time via this property.
        if self._client is not None:
            return self._client
        glance_host, glance_port = pick_glance_api_server()
        return _create_glance_client(context, glance_host, glance_port)

    def _call_retry(self, context, name, *args, **kwargs):
        """Retry call to glance server if there is a connection error.
        Suitable only for idempotent calls."""
        for i in xrange(FLAGS.glance_num_retries + 1):
            client = self._get_client(context)
            try:
                return getattr(client, name)(*args, **kwargs)
            except glance_exception.ClientConnectionError as e:
                LOG.exception(_('Connection error contacting glance'
                                ' server, retrying'))

                time.sleep(1)

        raise exception.GlanceConnectionFailed(
                reason=_('Maximum attempts reached'))

    def index(self, context, **kwargs):
        """Calls out to Glance for a list of images available."""
        params = self._extract_query_params(kwargs)
        image_metas = self._get_images(context, **params)

        images = []
        for image_meta in image_metas:
            # NOTE(sirp): We need to use `get_images_detailed` and not
            # `get_images` here because we need `is_public` and `properties`
            # included so we can filter by user
            if self._is_image_available(context, image_meta):
                meta_subset = utils.subset_dict(image_meta, ('id', 'name'))
                images.append(meta_subset)
        return images

    def detail(self, context, **kwargs):
        """Calls out to Glance for a list of detailed image information."""
        params = self._extract_query_params(kwargs)
        image_metas = self._get_images(context, **params)

        images = []
        for image_meta in image_metas:
            if self._is_image_available(context, image_meta):
                base_image_meta = self._translate_from_glance(image_meta)
                images.append(base_image_meta)
        return images

    def _extract_query_params(self, params):
        _params = {}
        accepted_params = ('filters', 'marker', 'limit',
                           'sort_key', 'sort_dir')
        for param in accepted_params:
            if param in params:
                _params[param] = params.get(param)

        return _params

    def _get_images(self, context, **kwargs):
        """Get image entitites from images service"""

        # ensure filters is a dict
        kwargs['filters'] = kwargs.get('filters') or {}
        # NOTE(vish): don't filter out private images
        kwargs['filters'].setdefault('is_public', 'none')

        client = self._get_client(context)
        return self._fetch_images(client.get_images_detailed, **kwargs)

    def _fetch_images(self, fetch_func, **kwargs):
        """Paginate through results from glance server"""
        try:
            images = fetch_func(**kwargs)
        except Exception:
            _reraise_translated_exception()

        if not images:
            # break out of recursive loop to end pagination
            return

        for image in images:
            yield image

        try:
            # attempt to advance the marker in order to fetch next page
            kwargs['marker'] = images[-1]['id']
        except KeyError:
            raise exception.ImagePaginationFailed()

        try:
            kwargs['limit'] = kwargs['limit'] - len(images)
            # break if we have reached a provided limit
            if kwargs['limit'] <= 0:
                return
        except KeyError:
            # ignore missing limit, just proceed without it
            pass

        for image in self._fetch_images(fetch_func, **kwargs):
            yield image

    def show(self, context, image_id):
        """Returns a dict with image data for the given opaque image id."""
        try:
            image_meta = self._call_retry(context, 'get_image_meta',
                                          image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_from_glance(image_meta)
        return base_image_meta

    def show_by_name(self, context, name):
        """Returns a dict containing image data for the given name."""
        image_metas = self.detail(context, filters={'name': name})
        try:
            return image_metas[0]
        except (IndexError, TypeError):
            raise exception.ImageNotFound(image_id=name)

    def get(self, context, image_id, data):
        """Calls out to Glance for metadata and data and writes data."""
        try:
            image_meta, image_chunks = self._call_retry(context, 'get_image',
                                                        image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        for chunk in image_chunks:
            data.write(chunk)

        base_image_meta = self._translate_from_glance(image_meta)
        return base_image_meta

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image id.

        :raises: AlreadyExists if the image already exist.

        """
        # Translate Base -> Service
        LOG.debug(_('Creating image in Glance. Metadata passed in %s'),
                  image_meta)
        sent_service_image_meta = self._translate_to_glance(image_meta)
        LOG.debug(_('Metadata after formatting for Glance %s'),
                  sent_service_image_meta)

        recv_service_image_meta = self._get_client(context).add_image(
            sent_service_image_meta, data)

        # Translate Service -> Base
        base_image_meta = self._translate_from_glance(recv_service_image_meta)
        LOG.debug(_('Metadata returned from Glance formatted for Base %s'),
                  base_image_meta)
        return base_image_meta

    def update(self, context, image_id, image_meta, data=None):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        # NOTE(vish): show is to check if image is available
        self.show(context, image_id)
        image_meta = self._translate_to_glance(image_meta)
        client = self._get_client(context)
        try:
            image_meta = client.update_image(image_id, image_meta, data)
        except Exception:
            _reraise_translated_image_exception(image_id)

        base_image_meta = self._translate_from_glance(image_meta)
        return base_image_meta

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.

        """
        # NOTE(vish): show is to check if image is available
        image_meta = self.show(context, image_id)

        if FLAGS.auth_strategy == 'deprecated':
            # NOTE(parthi): only allow image deletions if the user
            # is a member of the project owning the image, in case of
            # setup without keystone
            # TODO(parthi): Currently this access control breaks if
            # 1. Image is not owned by a project
            # 2. Deleting user is not bound a project
            properties = image_meta['properties']
            if (context.project_id and ('project_id' in properties)
                and (context.project_id != properties['project_id'])):
                raise exception.NotAuthorized(_("Not the image owner"))

            if (context.project_id and ('owner_id' in properties)
                and (context.project_id != properties['owner_id'])):
                raise exception.NotAuthorized(_("Not the image owner"))

        try:
            result = self._get_client(context).delete_image(image_id)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return result

    def delete_all(self):
        """Clears out all images."""
        pass

    @classmethod
    def _translate_to_glance(cls, image_meta):
        image_meta = _convert_to_string(image_meta)
        image_meta = _remove_read_only(image_meta)
        return image_meta

    @classmethod
    def _translate_from_glance(cls, image_meta):
        image_meta = _limit_attributes(image_meta)
        image_meta = _convert_timestamps_to_datetimes(image_meta)
        image_meta = _convert_from_string(image_meta)
        return image_meta

    @staticmethod
    def _is_image_available(context, image_meta):
        """Check image availability.

        Under Glance, images are always available if the context has
        an auth_token.

        """
        if hasattr(context, 'auth_token') and context.auth_token:
            return True

        if image_meta['is_public'] or context.is_admin:
            return True

        properties = image_meta['properties']

        if context.project_id and ('owner_id' in properties):
            return str(properties['owner_id']) == str(context.project_id)

        if context.project_id and ('project_id' in properties):
            return str(properties['project_id']) == str(context.project_id)

        try:
            user_id = properties['user_id']
        except KeyError:
            return False

        return str(user_id) == str(context.user_id)


# utility functions
def _convert_timestamps_to_datetimes(image_meta):
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = _parse_glance_iso8601_timestamp(
                image_meta[attr])
    return image_meta


def _parse_glance_iso8601_timestamp(timestamp):
    """Parse a subset of iso8601 timestamps into datetime objects."""
    iso_formats = ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S']

    for iso_format in iso_formats:
        try:
            return datetime.datetime.strptime(timestamp, iso_format)
        except ValueError:
            pass

    raise ValueError(_('%(timestamp)s does not follow any of the '
                       'signatures: %(iso_formats)s') % locals())


# TODO(yamahata): use block-device-mapping extension to glance
def _json_loads(properties, attr):
    prop = properties[attr]
    if isinstance(prop, basestring):
        properties[attr] = json.loads(prop)


def _json_dumps(properties, attr):
    prop = properties[attr]
    if not isinstance(prop, basestring):
        properties[attr] = json.dumps(prop)


_CONVERT_PROPS = ('block_device_mapping', 'mappings')


def _convert(method, metadata):
    metadata = copy.deepcopy(metadata)  # don't touch original metadata
    properties = metadata.get('properties')
    if properties:
        for attr in _CONVERT_PROPS:
            if attr in properties:
                method(properties, attr)

    return metadata


def _convert_from_string(metadata):
    return _convert(_json_loads, metadata)


def _convert_to_string(metadata):
    return _convert(_json_dumps, metadata)


def _limit_attributes(image_meta):
    IMAGE_ATTRIBUTES = ['size', 'disk_format',
                        'container_format', 'checksum', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted_at', 'deleted', 'status',
                        'min_disk', 'min_ram', 'is_public']
    output = {}
    for attr in IMAGE_ATTRIBUTES:
        output[attr] = image_meta.get(attr)

    output['properties'] = image_meta.get('properties', {})

    return output


def _remove_read_only(image_meta):
    IMAGE_ATTRIBUTES = ['updated_at', 'created_at', 'deleted_at']
    output = copy.deepcopy(image_meta)
    for attr in IMAGE_ATTRIBUTES:
        if attr in output:
            del output[attr]
    return output


def _reraise_translated_image_exception(image_id):
    """Transform the exception for the image but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_image_exception(image_id, exc_type, exc_value)
    raise new_exc, None, exc_trace


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_type, exc_value)
    raise new_exc, None, exc_trace


def _translate_image_exception(image_id, exc_type, exc_value):
    if exc_type in (glance_exception.Forbidden,
                    glance_exception.NotAuthenticated,
                    glance_exception.MissingCredentialError):
        return exception.ImageNotAuthorized(image_id=image_id)
    if exc_type is glance_exception.NotFound:
        return exception.ImageNotFound(image_id=image_id)
    if exc_type is glance_exception.Invalid:
        return exception.Invalid(exc_value)
    return exc_value


def _translate_plain_exception(exc_type, exc_value):
    if exc_type in (glance_exception.Forbidden,
                    glance_exception.NotAuthenticated,
                    glance_exception.MissingCredentialError):
        return exception.NotAuthorized(exc_value)
    if exc_type is glance_exception.NotFound:
        return exception.NotFound(exc_value)
    if exc_type is glance_exception.Invalid:
        return exception.Invalid(exc_value)
    return exc_value
