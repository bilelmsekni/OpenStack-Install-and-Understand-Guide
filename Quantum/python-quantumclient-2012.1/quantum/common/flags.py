# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Citrix Systems, Inc.
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

"""Command-line flag library.

Wraps gflags.
Global flags should be defined here, the rest are defined where they're used.

"""
import getopt
import gflags
import os
import string
import sys


class FlagValues(gflags.FlagValues):
    """Extension of gflags.FlagValues that allows undefined and runtime flags.

    Unknown flags will be ignored when parsing the command line, but the
    command line will be kept so that it can be replayed if new flags are
    defined after the initial parsing.

    """

    def __init__(self, extra_context=None):
        gflags.FlagValues.__init__(self)
        self.__dict__['__dirty'] = []
        self.__dict__['__was_already_parsed'] = False
        self.__dict__['__stored_argv'] = []
        self.__dict__['__extra_context'] = extra_context

    def __call__(self, argv):
        # We're doing some hacky stuff here so that we don't have to copy
        # out all the code of the original verbatim and then tweak a few lines.
        # We're hijacking the output of getopt so we can still return the
        # leftover args at the end
        sneaky_unparsed_args = {"value": None}
        original_argv = list(argv)

        if self.IsGnuGetOpt():
            orig_getopt = getattr(getopt, 'gnu_getopt')
            orig_name = 'gnu_getopt'
        else:
            orig_getopt = getattr(getopt, 'getopt')
            orig_name = 'getopt'

        def _sneaky(*args, **kw):
            optlist, unparsed_args = orig_getopt(*args, **kw)
            sneaky_unparsed_args['value'] = unparsed_args
            return optlist, unparsed_args

        try:
            setattr(getopt, orig_name, _sneaky)
            args = gflags.FlagValues.__call__(self, argv)
        except gflags.UnrecognizedFlagError:
            # Undefined args were found, for now we don't care so just
            # act like everything went well
            # (these three lines are copied pretty much verbatim from the end
            # of the __call__ function we are wrapping)
            unparsed_args = sneaky_unparsed_args['value']
            if unparsed_args:
                if self.IsGnuGetOpt():
                    args = argv[:1] + unparsed_args
                else:
                    args = argv[:1] + original_argv[-len(unparsed_args):]
            else:
                args = argv[:1]
        finally:
            setattr(getopt, orig_name, orig_getopt)

        # Store the arguments for later, we'll need them for new flags
        # added at runtime
        self.__dict__['__stored_argv'] = original_argv
        self.__dict__['__was_already_parsed'] = True
        self.ClearDirty()
        return args

    def Reset(self):
        gflags.FlagValues.Reset(self)
        self.__dict__['__dirty'] = []
        self.__dict__['__was_already_parsed'] = False
        self.__dict__['__stored_argv'] = []

    def SetDirty(self, name):
        """Mark a flag as dirty so that accessing it will case a reparse."""
        self.__dict__['__dirty'].append(name)

    def IsDirty(self, name):
        return name in self.__dict__['__dirty']

    def ClearDirty(self):
        self.__dict__['__is_dirty'] = []

    def WasAlreadyParsed(self):
        return self.__dict__['__was_already_parsed']

    def ParseNewFlags(self):
        if '__stored_argv' not in self.__dict__:
            return
        new_flags = FlagValues(self)
        for k in self.__dict__['__dirty']:
            new_flags[k] = gflags.FlagValues.__getitem__(self, k)

        new_flags(self.__dict__['__stored_argv'])
        for k in self.__dict__['__dirty']:
            setattr(self, k, getattr(new_flags, k))
        self.ClearDirty()

    def __setitem__(self, name, flag):
        gflags.FlagValues.__setitem__(self, name, flag)
        if self.WasAlreadyParsed():
            self.SetDirty(name)

    def __getitem__(self, name):
        if self.IsDirty(name):
            self.ParseNewFlags()
        return gflags.FlagValues.__getitem__(self, name)

    def __getattr__(self, name):
        if self.IsDirty(name):
            self.ParseNewFlags()
        val = gflags.FlagValues.__getattr__(self, name)
        if type(val) is str:
            tmpl = string.Template(val)
            context = [self, self.__dict__['__extra_context']]
            return tmpl.substitute(StrWrapper(context))
        return val


class StrWrapper(object):
    """Wrapper around FlagValues objects.

    Wraps FlagValues objects for string.Template so that we're
    sure to return strings.

    """
    def __init__(self, context_objs):
        self.context_objs = context_objs

    def __getitem__(self, name):
        for context in self.context_objs:
            val = getattr(context, name, False)
            if val:
                return str(val)
        raise KeyError(name)


# Copied from gflags with small mods to get the naming correct.
# Originally gflags checks for the first module that is not gflags that is
# in the call chain, we want to check for the first module that is not gflags
# and not this module.
def _GetCallingModule():
    """Returns the name of the module that's calling into this module.

    We generally use this function to get the name of the module calling a
    DEFINE_foo... function.

    """
    # Walk down the stack to find the first globals dict that's not ours.
    for depth in range(1, sys.getrecursionlimit()):
        if not sys._getframe(depth).f_globals is globals():
            module_name = __GetModuleName(sys._getframe(depth).f_globals)
            if module_name == 'gflags':
                continue
            if module_name is not None:
                return module_name
    raise AssertionError("No module was found")


# Copied from gflags because it is a private function
def __GetModuleName(globals_dict):
    """Given a globals dict, returns the name of the module that defines it.

    Args:
    globals_dict: A dictionary that should correspond to an environment
      providing the values of the globals.

    Returns:
    A string (the name of the module) or None (if the module could not
    be identified.

    """
    for name, module in sys.modules.iteritems():
        if getattr(module, '__dict__', None) is globals_dict:
            if name == '__main__':
                return sys.argv[0]
            return name
    return None


def _wrapper(func):
    def _wrapped(*args, **kw):
        kw.setdefault('flag_values', FLAGS)
        func(*args, **kw)
    _wrapped.func_name = func.func_name
    return _wrapped


FLAGS = FlagValues()
gflags.FLAGS = FLAGS
gflags._GetCallingModule = _GetCallingModule


DEFINE = _wrapper(gflags.DEFINE)
DEFINE_string = _wrapper(gflags.DEFINE_string)
DEFINE_integer = _wrapper(gflags.DEFINE_integer)
DEFINE_bool = _wrapper(gflags.DEFINE_bool)
DEFINE_boolean = _wrapper(gflags.DEFINE_boolean)
DEFINE_float = _wrapper(gflags.DEFINE_float)
DEFINE_enum = _wrapper(gflags.DEFINE_enum)
DEFINE_list = _wrapper(gflags.DEFINE_list)
DEFINE_spaceseplist = _wrapper(gflags.DEFINE_spaceseplist)
DEFINE_multistring = _wrapper(gflags.DEFINE_multistring)
DEFINE_multi_int = _wrapper(gflags.DEFINE_multi_int)
DEFINE_flag = _wrapper(gflags.DEFINE_flag)
HelpFlag = gflags.HelpFlag
HelpshortFlag = gflags.HelpshortFlag
HelpXMLFlag = gflags.HelpXMLFlag


def DECLARE(name, module_string, flag_values=FLAGS):
    if module_string not in sys.modules:
        __import__(module_string, globals(), locals())
    if name not in flag_values:
        raise gflags.UnrecognizedFlag(
                "%s not defined by %s" % (name, module_string))


# __GLOBAL FLAGS ONLY__
# Define any app-specific flags in their own files, docs at:
# http://code.google.com/p/python-gflags/source/browse/trunk/gflags.py#a9

DEFINE_string('state_path', os.path.join(os.path.dirname(__file__), '../../'),
              "Top-level directory for maintaining quantum's state")
