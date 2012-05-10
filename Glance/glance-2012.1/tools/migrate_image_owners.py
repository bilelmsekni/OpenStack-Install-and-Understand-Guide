#!/usr/bin/python

import logging
import sys

import keystoneclient.v2_0.client

import glance.common.context
import glance.common.cfg
import glance.registry.context
import glance.registry.db.api as db_api


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


def get_owner_map(ksclient, owner_is_tenant=True):
    if owner_is_tenant:
        entities = ksclient.tenants.list()
    else:
        entities = ksclient.users.list()
    # build mapping of (user or tenant) name to id
    return dict([(entity.name, entity.id) for entity in entities])


def build_image_owner_map(owner_map, db, context):
    image_owner_map = {}
    for image in db.image_get_all(context):
        image_id = image['id']
        owner_name = image['owner']

        if not owner_name:
            logger.info('Image %s has no owner. Skipping.' % image_id)
            continue

        try:
            owner_id = owner_map[owner_name]
        except KeyError:
            msg = 'Image %s owner %s was not found. Skipping.'
            logger.error(msg % (image_id, owner_name))
            continue

        image_owner_map[image_id] = owner_id

        msg = 'Image %s owner %s -> %s' % (image_id, owner_name, owner_id)
        logger.info(msg)

    return image_owner_map


def update_image_owners(image_owner_map, db, context):
    for (image_id, image_owner) in image_owner_map.items():
        db.image_update(context, image_id, {'owner': image_owner})
        logger.info('Image %s successfully updated.' % image_id)


if __name__ == "__main__":
    config = glance.common.cfg.CommonConfigOpts(project='glance',
                                                prog='glance-registry')
    extra_cli_opts = [
        glance.common.cfg.BoolOpt('dry-run',
                help='Print output but do not make db changes.'),
        glance.common.cfg.StrOpt('keystone-auth-uri',
                help='Authentication endpoint'),
        glance.common.cfg.StrOpt('keystone-admin-tenant-name',
                help='Administrative user\'s tenant name'),
        glance.common.cfg.StrOpt('keystone-admin-user',
                help='Administrative user\'s id'),
        glance.common.cfg.StrOpt('keystone-admin-password',
                help='Administrative user\'s password'),
    ]
    config.register_cli_opts(extra_cli_opts)
    config()
    config.register_opts(glance.common.context.ContextMiddleware.opts)

    db_api.configure_db(config)

    context = glance.registry.context.RequestContext(is_admin=True)

    auth_uri = config.keystone_auth_uri
    admin_tenant_name = config.keystone_admin_tenant_name
    admin_user = config.keystone_admin_user
    admin_password = config.keystone_admin_password

    if not (auth_uri and admin_tenant_name and admin_user and admin_password):
        logger.critical('Missing authentication arguments')
        sys.exit(1)

    ks = keystoneclient.v2_0.client.Client(username=admin_user,
                                           password=admin_password,
                                           tenant_name=admin_tenant_name,
                                           auth_url=auth_uri)

    owner_map = get_owner_map(ks, config.owner_is_tenant)
    image_updates = build_image_owner_map(owner_map, db_api, context)
    if not config.dry_run:
        update_image_owners(image_updates, db_api, context)
