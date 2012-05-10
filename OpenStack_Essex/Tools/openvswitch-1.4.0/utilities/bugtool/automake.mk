if HAVE_PYTHON
sbin_SCRIPTS += utilities/bugtool/ovs-bugtool
CLEANFILES += utilities/bugtool/ovs-bugtool
man_MANS += utilities/bugtool/ovs-bugtool.8
MAN_ROOTS += utilities/bugtool/ovs-bugtool.8

bugtool_plugins = \
	utilities/bugtool/plugins/kernel-info/openvswitch.xml \
	utilities/bugtool/plugins/network-status/openvswitch.xml \
	utilities/bugtool/plugins/system-configuration.xml \
	utilities/bugtool/plugins/system-logs/openvswitch.xml \
	utilities/bugtool/plugins/system-configuration/openvswitch.xml

bugtool_scripts = \
	utilities/bugtool/ovs-bugtool-cfm-show \
	utilities/bugtool/ovs-bugtool-lacp-show \
	utilities/bugtool/ovs-bugtool-tc-class-show \
	utilities/bugtool/ovs-bugtool-ovsdb-dump
scripts_SCRIPTS += $(bugtool_scripts)

bugtoolpluginsdir = $(pkgdatadir)/bugtool-plugins
INSTALL_DATA_LOCAL += bugtool-install-data-local
bugtool-install-data-local:
	for plugin in $(bugtool_plugins); do \
	  stem=`echo "$$plugin" | sed 's,utilities/bugtool/plugins/,,'`; \
	  dir=`expr "$$stem" : '\(.*\)/[^/]*$$'`; \
	  $(MKDIR_P) "$(DESTDIR)$(bugtoolpluginsdir)/$$dir"; \
	  $(INSTALL_DATA) "$(srcdir)/$$plugin" "$(DESTDIR)$(bugtoolpluginsdir)/$$stem"; \
	done

UNINSTALL_LOCAL += bugtool-uninstall-local
bugtool-uninstall-local:
	for plugin in $(bugtool_plugins); do \
	  stem=`echo "$$plugin" | sed 's,utilities/bugtool/plugins/,,'`; \
	  rm -f "$(DESTDIR)$(bugtoolpluginsdir)/$$stem"; \
	done
	for plugin in $(bugtool_plugins); do \
	  stem=`echo "$$plugin" | sed 's,utilities/bugtool/plugins/,,'`; \
	  dir=`expr "$$stem" : '\(.*\)/[^/]*$$'`; \
	  rmdir "$(DESTDIR)$(bugtoolpluginsdir)/$$dir"; \
	done; exit 0
endif

EXTRA_DIST += \
	$(bugtool_plugins) \
	$(bugtool_scripts) \
	utilities/bugtool/ovs-bugtool.8 \
	utilities/bugtool/ovs-bugtool.in
