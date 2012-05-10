# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
#    Copyright (c) 2010 Citrix Systems, Inc.
#    Copyright (c) 2011 Piston Cloud Computing, Inc
#    Copyright (c) 2011 OpenStack LLC
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
import random

from nova import exception
from nova import flags
from nova import utils
from nova.virt import images


FLAGS = flags.FLAGS


def execute(*args, **kwargs):
    return utils.execute(*args, **kwargs)


def get_iscsi_initiator():
    """Get iscsi initiator name for this machine"""
    # NOTE(vish) openiscsi stores initiator name in a file that
    #            needs root permission to read.
    contents = utils.read_file_as_root('/etc/iscsi/initiatorname.iscsi')
    for l in contents.split('\n'):
        if l.startswith('InitiatorName='):
            return l[l.index('=') + 1:].strip()


def create_image(disk_format, path, size):
    """Create a disk image

    :param disk_format: Disk image format (as known by qemu-img)
    :param path: Desired location of the disk image
    :param size: Desired size of disk image. May be given as an int or
                 a string. If given as an int, it will be interpreted
                 as bytes. If it's a string, it should consist of a number
                 with an optional suffix ('K' for Kibibytes,
                 M for Mebibytes, 'G' for Gibibytes, 'T' for Tebibytes).
                 If no suffix is given, it will be interpreted as bytes.
    """
    execute('qemu-img', 'create', '-f', disk_format, path, size)


def create_cow_image(backing_file, path):
    """Create COW image

    Creates a COW image with the given backing file

    :param backing_file: Existing image on which to base the COW image
    :param path: Desired location of the COW image
    """
    execute('qemu-img', 'create', '-f', 'qcow2', '-o',
             'cluster_size=2M,backing_file=%s' % backing_file, path)


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    out, err = execute('qemu-img', 'info', path)
    size = [i.split('(')[1].split()[0] for i in out.split('\n')
        if i.strip().find('virtual size') >= 0]
    return int(size[0])


def get_disk_backing_file(path):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    out, err = execute('qemu-img', 'info', path)
    backing_file = [i.split('actual path:')[1].strip()[:-1]
        for i in out.split('\n') if 0 <= i.find('backing file')]
    if backing_file:
        backing_file = os.path.basename(backing_file[0])
    return backing_file


def copy_image(src, dest):
    """Copy a disk image

    :param src: Source image
    :param dest: Destination path
    """
    # We shell out to cp because that will intelligently copy
    # sparse files.  I.E. holes will not be written to DEST,
    # rather recreated efficiently.  In addition, since
    # coreutils 8.11, holes can be read efficiently too.
    execute('cp', src, dest)


def mkfs(fs, path, label=None):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        execute('mkswap', path)
    else:
        args = ['mkfs', '-t', fs]
        if label:
            args.extend(['-n', label])
        args.append(path)
        execute(*args)


def ensure_tree(path):
    """Create a directory (and any ancestor directories required)

    :param path: Directory to create
    """
    execute('mkdir', '-p', path)


def write_to_file(path, contents, umask=None):
    """Write the given contents to a file

    :param path: Destination file
    :param contents: Desired contents of the file
    :param umask: Umask to set when creating this file (will be reset)
    """
    if umask:
        saved_umask = os.umask(umask)

    try:
        with open(path, 'w') as f:
            f.write(contents)
    finally:
        if umask:
            os.umask(saved_umask)


def chown(path, owner):
    """Change ownership of file or directory

    :param path: File or directory whose ownership to change
    :param owner: Desired new owner (given as uid or username)
    """
    execute('chown', owner, path, run_as_root=True)


def create_snapshot(disk_path, snapshot_name):
    """Create a snapshot in a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    """
    qemu_img_cmd = ('qemu-img',
                    'snapshot',
                    '-c',
                    snapshot_name,
                    disk_path)
    # NOTE(vish): libvirt changes ownership of images
    execute(*qemu_img_cmd, run_as_root=True)


def delete_snapshot(disk_path, snapshot_name):
    """Create a snapshot in a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    """
    qemu_img_cmd = ('qemu-img',
                    'snapshot',
                    '-d',
                    snapshot_name,
                    disk_path)
    # NOTE(vish): libvirt changes ownership of images
    execute(*qemu_img_cmd, run_as_root=True)


def extract_snapshot(disk_path, source_fmt, snapshot_name, out_path, dest_fmt):
    """Extract a named snapshot from a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    :param out_path: Desired path of extracted snapshot
    """
    qemu_img_cmd = ('qemu-img',
                    'convert',
                    '-f',
                    source_fmt,
                    '-O',
                    dest_fmt,
                    '-s',
                    snapshot_name,
                    disk_path,
                    out_path)
    execute(*qemu_img_cmd)


def load_file(path):
    """Read contents of file

    :param path: File to read
    """
    with open(path, 'r+') as fp:
        return fp.read()


def file_open(*args, **kwargs):
    """Open file

    see built-in file() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return file(*args, **kwargs)


def file_delete(path):
    """Delete (unlink) file

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return os.unlink(path)


def get_open_port(start_port, end_port):
    """Find an available port

    :param start_port: Start of acceptable port range
    :param end_port: End of acceptable port range
    """
    for i in xrange(0, 100):  # don't loop forever
        port = random.randint(start_port, end_port)
        # netcat will exit with 0 only if the port is in use,
        # so a nonzero return value implies it is unused
        cmd = 'netcat', '0.0.0.0', port, '-w', '1'
        try:
            stdout, stderr = execute(*cmd, process_input='')
        except exception.ProcessExecutionError:
            return port
    raise Exception(_('Unable to find an open port'))


def get_fs_info(path):
    """Get free/used/total space info for a filesystem

    :param path: Any dirent on the filesystem
    :returns: A dict containing:

             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
             :total: How big the filesystem is (in bytes)
    """
    hddinfo = os.statvfs(path)
    total = hddinfo.f_frsize * hddinfo.f_blocks
    free = hddinfo.f_frsize * hddinfo.f_bavail
    used = hddinfo.f_frsize * (hddinfo.f_blocks - hddinfo.f_bfree)
    return {'total': total,
            'free': free,
            'used': used}


def fetch_image(context, target, image_id, user_id, project_id):
    """Grab image"""
    images.fetch_to_raw(context, image_id, target, user_id, project_id)
