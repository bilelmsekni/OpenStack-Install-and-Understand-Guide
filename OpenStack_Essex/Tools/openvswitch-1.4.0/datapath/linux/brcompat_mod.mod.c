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
	{ 0x25ec1b28, "strlen" },
	{ 0x6caa079d, "genl_unregister_family" },
	{ 0xc7a4fbed, "rtnl_lock" },
	{ 0xd76ae670, "skb_clone" },
	{ 0x367ff0f8, "ovs_dp_ioctl_hook" },
	{ 0x798ade4a, "mutex_unlock" },
	{ 0x4f8b5ddb, "_copy_to_user" },
	{ 0x5261c814, "nlmsg_notify" },
	{ 0xde0bdcff, "memset" },
	{ 0xb86e4ab9, "random32" },
	{ 0x88941a06, "_raw_spin_unlock_irqrestore" },
	{ 0x27e1a049, "printk" },
	{ 0xa1c76e0a, "_cond_resched" },
	{ 0xb4390f9a, "mcount" },
	{ 0x1c08edd3, "nla_put" },
	{ 0x16305289, "warn_slowpath_null" },
	{ 0xd728ebf2, "mutex_lock" },
	{ 0xb77f65c8, "netlink_unicast" },
	{ 0x310aa232, "genl_register_family_with_ops" },
	{ 0xe6a2828c, "init_net" },
	{ 0xb7b9febb, "__dev_get_by_index" },
	{ 0x7dceceac, "capable" },
	{ 0x888e6174, "__alloc_skb" },
	{ 0x8fbde03d, "netlink_broadcast" },
	{ 0xf0fdf6cb, "__stack_chk_fail" },
	{ 0x4f391d0e, "nla_parse" },
	{ 0x84342e18, "kfree_skb" },
	{ 0x20cea88d, "brioctl_set" },
	{ 0x587c70d8, "_raw_spin_lock_irqsave" },
	{ 0x7d4e3202, "genl_register_mc_group" },
	{ 0x5e09ca75, "complete" },
	{ 0x38d21d9, "skb_put" },
	{ 0x8d4dcdc9, "wait_for_completion_timeout" },
	{ 0x4f6b400b, "_copy_from_user" },
	{ 0x6e720ff2, "rtnl_unlock" },
};

static const char __module_depends[]
__used
__attribute__((section(".modinfo"))) =
"depends=openvswitch_mod";


MODULE_INFO(srcversion, "42539379AA63ABAA1CAF9FC");
