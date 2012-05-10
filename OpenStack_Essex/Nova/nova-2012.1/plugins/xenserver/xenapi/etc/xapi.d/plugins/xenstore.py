#!/usr/bin/env python

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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

#
# XenAPI plugin for reading/writing information to xenstore
#

try:
    import json
except ImportError:
    import simplejson as json
import logging
import os
import subprocess

import XenAPIPlugin

import pluginlib_nova as pluginlib
pluginlib.configure_logging("xenstore")


class XenstoreError(pluginlib.PluginError):
    """Errors that occur when calling xenstore-* through subprocesses"""

    def __init__(self, cmd, return_code, stderr, stdout):
        msg = "cmd: %s; returncode: %d; stderr: %s; stdout: %s"
        msg = msg % (cmd, return_code, stderr, stdout)
        self.cmd = cmd
        self.return_code = return_code
        self.stderr = stderr
        self.stdout = stdout
        pluginlib.PluginError.__init__(self, msg)


def jsonify(fnc):
    def wrapper(*args, **kwargs):
        ret = fnc(*args, **kwargs)
        try:
            json.loads(ret)
        except ValueError:
            # Value should already be JSON-encoded, but some operations
            # may write raw sting values; this will catch those and
            # properly encode them.
            ret = json.dumps(ret)
        return ret
    return wrapper


def _record_exists(arg_dict):
    """Returns whether or not the given record exists. The record path
    is determined from the given path and dom_id in the arg_dict."""
    cmd = ["xenstore-exists", "/local/domain/%(dom_id)s/%(path)s" % arg_dict]
    try:
        ret, result = _run_command(cmd)
    except XenstoreError, e:
        if e.stderr == '':
            # if stderr was empty, this just means the path did not exist
            return False
        # otherwise there was a real problem
        raise
    return True


@jsonify
def read_record(self, arg_dict):
    """Returns the value stored at the given path for the given dom_id.
    These must be encoded as key/value pairs in arg_dict. You can
    optinally include a key 'ignore_missing_path'; if this is present
    and boolean True, attempting to read a non-existent path will return
    the string 'None' instead of raising an exception.
    """
    cmd = ["xenstore-read", "/local/domain/%(dom_id)s/%(path)s" % arg_dict]
    try:
        ret, result = _run_command(cmd)
        return result.strip()
    except XenstoreError, e:
        if not arg_dict.get("ignore_missing_path", False):
            raise
        if not _record_exists(arg_dict):
            return "None"
        # Just try again in case the agent write won the race against
        # the record_exists check. If this fails again, it will likely raise
        # an equally meaningful XenstoreError as the one we just caught
        ret, result = _run_command(cmd)
        return result.strip()


@jsonify
def write_record(self, arg_dict):
    """Writes to xenstore at the specified path. If there is information
    already stored in that location, it is overwritten. As in read_record,
    the dom_id and path must be specified in the arg_dict; additionally,
    you must specify a 'value' key, whose value must be a string. Typically,
    you can json-ify more complex values and store the json output.
    """
    cmd = ["xenstore-write",
           "/local/domain/%(dom_id)s/%(path)s" % arg_dict,
           arg_dict["value"]]
    _run_command(cmd)
    return arg_dict["value"]


@jsonify
def list_records(self, arg_dict):
    """Returns all the stored data at or below the given path for the
    given dom_id. The data is returned as a json-ified dict, with the
    path as the key and the stored value as the value. If the path
    doesn't exist, an empty dict is returned.
    """
    dirpath = "/local/domain/%(dom_id)s/%(path)s" % arg_dict
    cmd = ["xenstore-ls", dirpath.rstrip("/")]
    try:
        ret, recs = _run_command(cmd)
    except XenstoreError, e:
        if not _record_exists(arg_dict):
            return {}
        # Just try again in case the path was created in between
        # the "ls" and the existence check. If this fails again, it will
        # likely raise an equally meaningful XenstoreError
        ret, recs = _run_command(cmd)
    base_path = arg_dict["path"]
    paths = _paths_from_ls(recs)
    ret = {}
    for path in paths:
        if base_path:
            arg_dict["path"] = "%s/%s" % (base_path, path)
        else:
            arg_dict["path"] = path
        rec = read_record(self, arg_dict)
        try:
            val = json.loads(rec)
        except ValueError:
            val = rec
        ret[path] = val
    return ret


@jsonify
def delete_record(self, arg_dict):
    """Just like it sounds: it removes the record for the specified
    VM and the specified path from xenstore.
    """
    cmd = ["xenstore-rm", "/local/domain/%(dom_id)s/%(path)s" % arg_dict]
    ret, result = _run_command(cmd)
    return result


def _paths_from_ls(recs):
    """The xenstore-ls command returns a listing that isn't terribly
    useful. This method cleans that up into a dict with each path
    as the key, and the associated string as the value.
    """
    ret = {}
    last_nm = ""
    level = 0
    path = []
    ret = []
    for ln in recs.splitlines():
        nm, val = ln.rstrip().split(" = ")
        barename = nm.lstrip()
        this_level = len(nm) - len(barename)
        if this_level == 0:
            ret.append(barename)
            level = 0
            path = []
        elif this_level == level:
            # child of same parent
            ret.append("%s/%s" % ("/".join(path), barename))
        elif this_level > level:
            path.append(last_nm)
            ret.append("%s/%s" % ("/".join(path), barename))
            level = this_level
        elif this_level < level:
            path = path[:this_level]
            ret.append("%s/%s" % ("/".join(path), barename))
            level = this_level
        last_nm = barename
    return ret


def _run_command(cmd):
    """Abstracts out the basics of issuing system commands. If the command
    returns anything in stderr, a PluginError is raised with that information.
    Otherwise, a tuple of (return code, stdout data) is returned.
    """
    logging.info(' '.join(cmd))
    pipe = subprocess.PIPE
    proc = subprocess.Popen(cmd, stdin=pipe, stdout=pipe, stderr=pipe,
            close_fds=True)
    out, err = proc.communicate()
    if proc.returncode is not os.EX_OK:
        raise XenstoreError(cmd, proc.returncode, err, out)
    return proc.returncode, out


if __name__ == "__main__":
    XenAPIPlugin.dispatch(
        {"read_record": read_record,
        "write_record": write_record,
        "list_records": list_records,
        "delete_record": delete_record})
