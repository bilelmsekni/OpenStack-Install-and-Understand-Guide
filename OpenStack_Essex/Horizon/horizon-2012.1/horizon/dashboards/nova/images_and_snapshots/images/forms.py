# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
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

"""
Views for managing Nova images.
"""

import logging

from django import shortcuts
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.forms import ValidationError
from django.utils.text import normalize_newlines
from django.utils.translation import ugettext_lazy as _

from horizon import api
from horizon import exceptions
from horizon import forms

LOG = logging.getLogger(__name__)


class UpdateImageForm(forms.SelfHandlingForm):
    completion_view = 'horizon:nova:images_and_snapshots:index'

    image_id = forms.CharField(widget=forms.HiddenInput())
    name = forms.CharField(max_length="255", label=_("Name"))
    kernel = forms.CharField(max_length="36", label=_("Kernel ID"),
                             required=False,
                             widget=forms.TextInput(
                                attrs={'readonly': 'readonly'}
                             ))
    ramdisk = forms.CharField(max_length="36", label=_("Ramdisk ID"),
                              required=False,
                              widget=forms.TextInput(
                                attrs={'readonly': 'readonly'}
                              ))
    architecture = forms.CharField(label=_("Architecture"), required=False,
                                   widget=forms.TextInput(
                                    attrs={'readonly': 'readonly'}
                                   ))
    container_format = forms.CharField(label=_("Container Format"),
                                       widget=forms.TextInput(
                                        attrs={'readonly': 'readonly'}
                                       ))
    disk_format = forms.CharField(label=_("Disk Format"),
                                  widget=forms.TextInput(
                                    attrs={'readonly': 'readonly'}
                                  ))

    def handle(self, request, data):
        # TODO add public flag to image meta properties
        image_id = data['image_id']
        error_updating = _('Unable to update image "%s".')

        meta = {'is_public': True,
                'disk_format': data['disk_format'],
                'container_format': data['container_format'],
                'name': data['name'],
                'properties': {}}
        if data['kernel']:
            meta['properties']['kernel_id'] = data['kernel']
        if data['ramdisk']:
            meta['properties']['ramdisk_id'] = data['ramdisk']
        if data['architecture']:
            meta['properties']['architecture'] = data['architecture']

        try:
            api.image_update(request, image_id, meta)
            messages.success(request, _('Image was successfully updated.'))
        except:
            exceptions.handle(request, error_updating % image_id)
        return shortcuts.redirect(self.get_success_url())


class LaunchForm(forms.SelfHandlingForm):
    name = forms.CharField(max_length=80, label=_("Server Name"))
    image_id = forms.CharField(widget=forms.HiddenInput())
    tenant_id = forms.CharField(widget=forms.HiddenInput())
    user_data = forms.CharField(widget=forms.Textarea,
                                label=_("User Data"),
                                required=False)
    flavor = forms.ChoiceField(label=_("Flavor"),
                               help_text=_("Size of image to launch."))
    keypair = forms.ChoiceField(label=_("Keypair"),
                                required=False,
                                help_text=_("Which keypair to use for "
                                            "authentication."))
    count = forms.IntegerField(label=_("Instance Count"),
                            required=True,
                            min_value=1,
                            initial=1,
                            help_text=_("Number of instances to launch."))
    security_groups = forms.MultipleChoiceField(
                                label=_("Security Groups"),
                                required=True,
                                initial=["default"],
                                widget=forms.CheckboxSelectMultiple(),
                                help_text=_("Launch instance in these "
                                            "security groups."))
    volume = forms.ChoiceField(label=_("Volume or Volume Snapshot"),
                               required=False,
                               help_text=_("Volume to boot from."))
    device_name = forms.CharField(label=_("Device Name"),
                                  required=False,
                                  initial="vda",
                                  help_text=_("Volume mount point (e.g. 'vda' "
                                              "mounts at '/dev/vda')."))
    delete_on_terminate = forms.BooleanField(
            label=_("Delete on Terminate"),
            initial=False,
            required=False,
            help_text=_("Delete volume on instance terminate"))

    def __init__(self, *args, **kwargs):
        flavor_list = kwargs.pop('flavor_list')
        keypair_list = kwargs.pop('keypair_list')
        if keypair_list:
            keypair_list.insert(0, ("", _("Select a keypair")))
        else:
            keypair_list = (("", _("No keypairs available.")),)
        security_group_list = kwargs.pop('security_group_list')
        volume_list = kwargs.pop('volume_list')
        super(LaunchForm, self).__init__(*args, **kwargs)
        self.fields['flavor'].choices = flavor_list
        self.fields['keypair'].choices = keypair_list
        self.fields['security_groups'].choices = security_group_list
        self.fields['volume'].choices = volume_list

    def clean(self):
        cleaned_data = super(LaunchForm, self).clean()
        count = cleaned_data.get('count', 1)
        volume = cleaned_data.get('volume', None)

        if volume and count > 1:
            msg = _('Cannot launch more than one instance if '
                    'volume is specified.')
            raise ValidationError(msg)

        return cleaned_data

    def handle(self, request, data):
        try:
            if(len(data['volume']) > 0):
                if(data['delete_on_terminate']):
                    delete_on_terminate = 1
                else:
                    delete_on_terminate = 0
                dev_mapping = {data['device_name']:
                        ("%s::%s" % (data['volume'], delete_on_terminate))}
            else:
                dev_mapping = None

            api.server_create(request,
                              data['name'],
                              data['image_id'],
                              data['flavor'],
                              data.get('keypair'),
                              normalize_newlines(data.get('user_data')),
                              data.get('security_groups'),
                              dev_mapping,
                              instance_count=data.get('count'))
            messages.success(request,
                         _('Instance "%s" launched.') % data["name"])
        except:
            redirect = reverse("horizon:nova:images_and_snapshots:index")
            exceptions.handle(request,
                              _('Unable to launch instance: %(exc)s'),
                              redirect=redirect)
        return shortcuts.redirect('horizon:nova:instances_and_volumes:index')
