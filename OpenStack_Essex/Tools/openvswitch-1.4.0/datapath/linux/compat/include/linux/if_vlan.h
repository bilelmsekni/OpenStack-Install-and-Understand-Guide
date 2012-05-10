#ifndef __LINUX_IF_VLAN_WRAPPER_H
#define __LINUX_IF_VLAN_WRAPPER_H 1

#include_next <linux/if_vlan.h>
#include <linux/skbuff.h>

/*
 * The behavior of __vlan_put_tag() has changed over time:
 *
 *      - In 2.6.26 and earlier, it adjusted both MAC and network header
 *        pointers.  (The latter didn't make any sense.)
 *
 *      - In 2.6.27 and 2.6.28, it did not adjust any header pointers at all.
 *
 *      - In 2.6.29 and later, it adjusts the MAC header pointer only.
 *
 * This is the version from 2.6.33.  We unconditionally substitute this version
 * to avoid the need to guess whether the version in the kernel tree is
 * acceptable.
 */
#define __vlan_put_tag rpl_vlan_put_tag
static inline struct sk_buff *__vlan_put_tag(struct sk_buff *skb, u16 vlan_tci)
{
	struct vlan_ethhdr *veth;

	if (skb_cow_head(skb, VLAN_HLEN) < 0) {
		kfree_skb(skb);
		return NULL;
	}
	veth = (struct vlan_ethhdr *)skb_push(skb, VLAN_HLEN);

	/* Move the mac addresses to the beginning of the new header. */
	memmove(skb->data, skb->data + VLAN_HLEN, 2 * VLAN_ETH_ALEN);
	skb->mac_header -= VLAN_HLEN;

	/* first, the ethernet type */
	veth->h_vlan_proto = htons(ETH_P_8021Q);

	/* now, the TCI */
	veth->h_vlan_TCI = htons(vlan_tci);

	skb->protocol = htons(ETH_P_8021Q);

	return skb;
}


/* All of these were introduced in a single commit preceding 2.6.33, so
 * presumably all of them or none of them are present. */
#ifndef VLAN_PRIO_MASK
#define VLAN_PRIO_MASK		0xe000 /* Priority Code Point */
#define VLAN_PRIO_SHIFT		13
#define VLAN_CFI_MASK		0x1000 /* Canonical Format Indicator */
#define VLAN_TAG_PRESENT	VLAN_CFI_MASK
#endif

/* This function is not exported from kernel. OVS Upstreaming patch will
 * fix that. */
static inline void vlan_set_encap_proto(struct sk_buff *skb, struct vlan_hdr *vhdr)
{
	__be16 proto;
	unsigned char *rawp;

	/*
	 * Was a VLAN packet, grab the encapsulated protocol, which the layer
	 * three protocols care about.
	 */

	proto = vhdr->h_vlan_encapsulated_proto;
	if (ntohs(proto) >= 1536) {
		skb->protocol = proto;
		return;
	}

	rawp = skb->data;
	if (*(unsigned short *) rawp == 0xFFFF)
		/*
		 * This is a magic hack to spot IPX packets. Older Novell
		 * breaks the protocol design and runs IPX over 802.3 without
		 * an 802.2 LLC layer. We look for FFFF which isn't a used
		 * 802.2 SSAP/DSAP. This won't work for fault tolerant netware
		 * but does for the rest.
		 */
		skb->protocol = htons(ETH_P_802_3);
	else
		/*
		 * Real 802.2 LLC
		 */
		skb->protocol = htons(ETH_P_802_2);
}
#endif	/* linux/if_vlan.h wrapper */
