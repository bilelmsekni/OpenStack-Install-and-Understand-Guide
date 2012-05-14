#include <linux/module.h>
#include <linux/vermagic.h>
#include <linux/compiler.h>

MODULE_INFO(vermagic, VERMAGIC_STRING);

struct module __this_module
__attribute__((section(".gnu.linkonce.this_module"))) = {
 .name = KBUILD_MODNAME,
 .init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
 .exit = cleanup_module,
#endif
 .arch = MODULE_ARCH_INIT,
};

static const struct modversion_info ____versions[]
__used
__attribute__((section("__versions"))) = {
	{ 0x53eda548, "module_layout" },
	{ 0x5d4266ce, "register_netdevice" },
	{ 0x72c1310b, "kobject_put" },
	{ 0x7f711350, "kmem_cache_destroy" },
	{ 0xba66affe, "kmalloc_caches" },
	{ 0x5a34a45c, "__kmalloc" },
	{ 0x852ea7f5, "skb_gso_segment" },
	{ 0xe93e6f06, "inet_frag_kill" },
	{ 0xb85f3bbe, "pv_lock_ops" },
	{ 0x25ec1b28, "strlen" },
	{ 0x2abfd53f, "ip_route_output_key" },
	{ 0xb0562c98, "dev_get_flags" },
	{ 0x60a13e90, "rcu_barrier" },
	{ 0x6caa079d, "genl_unregister_family" },
	{ 0x33b0e1bb, "ip_local_out" },
	{ 0x79aa04a2, "get_random_bytes" },
	{ 0xd5565197, "netdev_rx_handler_register" },
	{ 0xc7a4fbed, "rtnl_lock" },
	{ 0x51a67a2, "sock_release" },
	{ 0xcb601d0e, "skb_copy_and_csum_dev" },
	{ 0xaba259f1, "_raw_read_lock" },
	{ 0x54af6a9, "kobject_uevent" },
	{ 0x2ad84ef3, "dst_release" },
	{ 0x87a45ee9, "_raw_spin_lock_bh" },
	{ 0xbc4f96a2, "icmp_send" },
	{ 0xd76ae670, "skb_clone" },
	{ 0x5c57bfb4, "dev_get_by_name" },
	{ 0x20000329, "simple_strtoul" },
	{ 0x7dba3cb2, "ethtool_op_get_sg" },
	{ 0xc0a3d105, "find_next_bit" },
	{ 0x2124474, "ip_send_check" },
	{ 0x63ecad53, "register_netdevice_notifier" },
	{ 0xf7471df3, "rtnl_notify" },
	{ 0x8b7fe311, "kmemdup" },
	{ 0x55f2580b, "__alloc_percpu" },
	{ 0x3a8ce6a4, "inet_proto_csum_replace4" },
	{ 0xfb5f846a, "cancel_delayed_work_sync" },
	{ 0xb0df7d74, "kobject_del" },
	{ 0x4c50215e, "inet_del_protocol" },
	{ 0x47c7b0d2, "cpu_number" },
	{ 0x3c2c5af5, "sprintf" },
	{ 0xb134aae, "sysfs_remove_group" },
	{ 0x7d11c268, "jiffies" },
	{ 0xc9ec4e21, "free_percpu" },
	{ 0xd8d21eb8, "inetdev_by_index" },
	{ 0xfe769456, "unregister_netdevice_notifier" },
	{ 0xa97cbdc7, "skb_trim" },
	{ 0xe2d5255a, "strcmp" },
	{ 0xe74b2829, "inet_frag_find" },
	{ 0x27c33efe, "csum_ipv6_magic" },
	{ 0x1365de5, "netif_rx" },
	{ 0xe1d81fc4, "__pskb_pull_tail" },
	{ 0xfe7c4287, "nr_cpu_ids" },
	{ 0xf1db1704, "nla_memcpy" },
	{ 0x5261c814, "nlmsg_notify" },
	{ 0xde0bdcff, "memset" },
	{ 0xf27e531b, "ethtool_op_set_tso" },
	{ 0x1397cd08, "skb_checksum" },
	{ 0xa48f8394, "dev_set_mac_address" },
	{ 0xfdb0508f, "dev_alloc_skb" },
	{ 0xf6388c56, "sysctl_ip_default_ttl" },
	{ 0xb86e4ab9, "random32" },
	{ 0xd7150a4d, "_raw_spin_trylock_bh" },
	{ 0x37befc70, "jiffies_to_msecs" },
	{ 0x27e1a049, "printk" },
	{ 0x82d80a38, "ethtool_op_get_link" },
	{ 0xf609aa30, "_raw_spin_trylock" },
	{ 0xafc5a928, "sysfs_create_group" },
	{ 0x94d32a88, "__tracepoint_module_get" },
	{ 0x8e0b7743, "ipv6_ext_hdr" },
	{ 0x561cd5d4, "__skb_warn_lro_forwarding" },
	{ 0x4a05985a, "free_netdev" },
	{ 0xb4390f9a, "mcount" },
	{ 0x1c08edd3, "nla_put" },
	{ 0x8636455, "inet_frags_fini" },
	{ 0x812c8ad5, "inet_frags_exit_net" },
	{ 0x5dba8214, "kmem_cache_free" },
	{ 0x16305289, "warn_slowpath_null" },
	{ 0x9972b8d3, "skb_push" },
	{ 0x16592094, "_raw_write_lock" },
	{ 0x5bc0d97b, "dev_get_by_index_rcu" },
	{ 0x482e2db7, "inet_add_protocol" },
	{ 0xc2cdbf1, "synchronize_sched" },
	{ 0xb77f65c8, "netlink_unicast" },
	{ 0x310aa232, "genl_register_family_with_ops" },
	{ 0x5e823af7, "sysfs_remove_link" },
	{ 0xf53c2e48, "kobject_add" },
	{ 0xe6a2828c, "init_net" },
	{ 0x7ce94405, "boot_tvec_bases" },
	{ 0x136e7ae6, "sysfs_create_link" },
	{ 0xa1a63c67, "module_put" },
	{ 0x7dceceac, "capable" },
	{ 0x3ff62317, "local_bh_disable" },
	{ 0xd83c7304, "__secpath_destroy" },
	{ 0x776e8f7c, "rtnl_set_sk_err" },
	{ 0x49be481, "kmem_cache_alloc" },
	{ 0x1ae2e5ac, "__nla_reserve" },
	{ 0x888e6174, "__alloc_skb" },
	{ 0xa71377e1, "ipv6_skip_exthdr" },
	{ 0x76ea7a14, "ethtool_op_set_sg" },
	{ 0x8fbde03d, "netlink_broadcast" },
	{ 0xc100cc3b, "inet_frag_evictor" },
	{ 0x6223cafb, "_raw_spin_unlock_bh" },
	{ 0xf0fdf6cb, "__stack_chk_fail" },
	{ 0x4f391d0e, "nla_parse" },
	{ 0xb9249d16, "cpu_possible_mask" },
	{ 0xf1bea6f1, "schedule_delayed_work" },
	{ 0x8e38dbed, "netdev_rx_handler_unregister" },
	{ 0xf61296e5, "skb_checksum_help" },
	{ 0x4b5814ef, "kmalloc_order_trace" },
	{ 0x84342e18, "kfree_skb" },
	{ 0x2923335f, "inet_frag_destroy" },
	{ 0x6b2dc060, "dump_stack" },
	{ 0x799aca4, "local_bh_enable" },
	{ 0x3648f6a0, "alloc_netdev_mqs" },
	{ 0xbd7c86ff, "ip_mc_inc_group" },
	{ 0xd9c922b7, "eth_type_trans" },
	{ 0x56980a29, "sysfs_create_file" },
	{ 0xaad0cb40, "pskb_expand_head" },
	{ 0x4714aade, "ether_setup" },
	{ 0x33e4cbc6, "kmem_cache_alloc_trace" },
	{ 0x6443d74d, "_raw_spin_lock" },
	{ 0x3928efe9, "__per_cpu_offset" },
	{ 0x2a18c74, "nf_conntrack_destroy" },
	{ 0x31a62d49, "kmem_cache_create" },
	{ 0xd4369424, "unregister_netdevice_queue" },
	{ 0xefdd5a63, "ktime_get_ts" },
	{ 0xf6ebc03b, "net_ratelimit" },
	{ 0x780c4046, "netlink_set_err" },
	{ 0x12f99022, "inet_frags_init_net" },
	{ 0xb318a109, "ethtool_op_set_tx_hw_csum" },
	{ 0xdfd3a7af, "dev_set_promiscuity" },
	{ 0x9ffd228a, "skb_copy_and_csum_bits" },
	{ 0x37a0cba, "kfree" },
	{ 0x236c8c64, "memcpy" },
	{ 0x50f5e532, "call_rcu_sched" },
	{ 0xc44e02cc, "kobject_init" },
	{ 0x944ae8c8, "sock_create" },
	{ 0xda2203d8, "kernel_bind" },
	{ 0x7d4e3202, "genl_register_mc_group" },
	{ 0x7628f3c7, "this_cpu_off" },
	{ 0xcb520584, "ethtool_op_get_tx_csum" },
	{ 0xe7a70646, "nla_reserve" },
	{ 0x58950fb1, "inet_frags_init" },
	{ 0xa6f46039, "ethtool_op_get_tso" },
	{ 0xa3a5be95, "memmove" },
	{ 0xe113bbbc, "csum_partial" },
	{ 0x56cc4e2d, "consume_skb" },
	{ 0x85670f1d, "rtnl_is_locked" },
	{ 0x8be5e37b, "dev_queue_xmit" },
	{ 0x38d21d9, "skb_put" },
	{ 0xdd7e1115, "sock_wfree" },
	{ 0x85fa7fea, "ip_mc_dec_group" },
	{ 0x52818c27, "skb_copy_bits" },
	{ 0xd542439, "__ipv6_addr_type" },
	{ 0x6e720ff2, "rtnl_unlock" },
	{ 0xa7e7338e, "__ip_select_ident" },
	{ 0x21e2006d, "__skb_checksum_complete" },
	{ 0xe914e41e, "strcpy" },
};

static const char __module_depends[]
__used
__attribute__((section(".modinfo"))) =
"depends=";


MODULE_INFO(srcversion, "1AE77A4DACA668FD72ECCCF");