#!/usr/bin/env bash
ifconfig eth0 0.0.0.0
cd /home/rs2m/OpenStack_Essex/Tools/openvswitch-1.4.0
rmmod bridge
insmod datapath/linux/openvswitch_mod.ko
insmod datapath/linux/brcompat_mod.ko
modprobe nbd
ovsdb-server /usr/local/etc/openvswitch/conf.db --remote=punix:/usr/local/var/run/openvswitch/db.sock --remote=db:Open_vSwitch,manager_options --pidfile --detach
ovs-vsctl --no-wait init
ovs-vswitchd --pidfile --detach
ovs-brcompatd --pidfile --detach
dhclient br-int
cd /home/rs2m/
