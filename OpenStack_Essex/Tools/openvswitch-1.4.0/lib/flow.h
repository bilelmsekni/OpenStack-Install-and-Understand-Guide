/*
 * Copyright (c) 2008, 2009, 2010, 2011 Nicira Networks.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at:
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#ifndef FLOW_H
#define FLOW_H 1

#include <sys/types.h>
#include <netinet/in.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "openflow/nicira-ext.h"
#include "openflow/openflow.h"
#include "hash.h"
#include "util.h"

struct dpif_flow_stats;
struct ds;
struct flow_wildcards;
struct ofp_match;
struct ofpbuf;

/* This sequence number should be incremented whenever anything involving flows
 * or the wildcarding of flows changes.  This will cause build assertion
 * failures in places which likely need to be updated. */
#define FLOW_WC_SEQ 7

#define FLOW_N_REGS 5
BUILD_ASSERT_DECL(FLOW_N_REGS <= NXM_NX_MAX_REGS);

/* Used for struct flow's dl_type member for frames that have no Ethernet
 * type, that is, pure 802.2 frames. */
#define FLOW_DL_TYPE_NONE 0x5ff

/* Fragment bits, used for IPv4 and IPv6, always zero for non-IP flows. */
#define FLOW_NW_FRAG_ANY   (1 << 0) /* Set for any IP frag. */
#define FLOW_NW_FRAG_LATER (1 << 1) /* Set for IP frag with nonzero offset. */
#define FLOW_NW_FRAG_MASK  (FLOW_NW_FRAG_ANY | FLOW_NW_FRAG_LATER)

BUILD_ASSERT_DECL(FLOW_NW_FRAG_ANY == NX_IP_FRAG_ANY);
BUILD_ASSERT_DECL(FLOW_NW_FRAG_LATER == NX_IP_FRAG_LATER);

struct flow {
    ovs_be64 tun_id;            /* Encapsulating tunnel ID. */
    struct in6_addr ipv6_src;   /* IPv6 source address. */
    struct in6_addr ipv6_dst;   /* IPv6 destination address. */
    struct in6_addr nd_target;  /* IPv6 neighbor discovery (ND) target. */
    uint32_t priority;          /* Packet priority for QoS. */
    uint32_t regs[FLOW_N_REGS]; /* Registers. */
    ovs_be32 nw_src;            /* IPv4 source address. */
    ovs_be32 nw_dst;            /* IPv4 destination address. */
    ovs_be32 ipv6_label;        /* IPv6 flow label. */
    uint16_t in_port;           /* OpenFlow port number of input port. */
    ovs_be16 vlan_tci;          /* If 802.1Q, TCI | VLAN_CFI; otherwise 0. */
    ovs_be16 dl_type;           /* Ethernet frame type. */
    ovs_be16 tp_src;            /* TCP/UDP source port. */
    ovs_be16 tp_dst;            /* TCP/UDP destination port. */
    uint8_t dl_src[6];          /* Ethernet source address. */
    uint8_t dl_dst[6];          /* Ethernet destination address. */
    uint8_t nw_proto;           /* IP protocol or low 8 bits of ARP opcode. */
    uint8_t nw_tos;             /* IP ToS (including DSCP and ECN). */
    uint8_t arp_sha[6];         /* ARP/ND source hardware address. */
    uint8_t arp_tha[6];         /* ARP/ND target hardware address. */
    uint8_t nw_ttl;             /* IP TTL/Hop Limit. */
    uint8_t nw_frag;            /* FLOW_FRAG_* flags. */
    uint8_t reserved[6];        /* Reserved for 64-bit packing. */
};

/* Assert that there are FLOW_SIG_SIZE bytes of significant data in "struct
 * flow", followed by FLOW_PAD_SIZE bytes of padding. */
#define FLOW_SIG_SIZE (110 + FLOW_N_REGS * 4)
#define FLOW_PAD_SIZE 6
BUILD_ASSERT_DECL(offsetof(struct flow, nw_frag) == FLOW_SIG_SIZE - 1);
BUILD_ASSERT_DECL(sizeof(((struct flow *)0)->nw_frag) == 1);
BUILD_ASSERT_DECL(sizeof(struct flow) == FLOW_SIG_SIZE + FLOW_PAD_SIZE);

/* Remember to update FLOW_WC_SEQ when changing 'struct flow'. */
BUILD_ASSERT_DECL(FLOW_SIG_SIZE == 130 && FLOW_WC_SEQ == 7);

void flow_extract(struct ofpbuf *, uint32_t priority, ovs_be64 tun_id,
                  uint16_t in_port, struct flow *);
void flow_zero_wildcards(struct flow *, const struct flow_wildcards *);

char *flow_to_string(const struct flow *);
void flow_format(struct ds *, const struct flow *);
void flow_print(FILE *, const struct flow *);
static inline int flow_compare_3way(const struct flow *, const struct flow *);
static inline bool flow_equal(const struct flow *, const struct flow *);
static inline size_t flow_hash(const struct flow *, uint32_t basis);

void flow_set_vlan_vid(struct flow *, ovs_be16 vid);
void flow_set_vlan_pcp(struct flow *, uint8_t pcp);

void flow_compose(struct ofpbuf *, const struct flow *);

static inline int
flow_compare_3way(const struct flow *a, const struct flow *b)
{
    return memcmp(a, b, FLOW_SIG_SIZE);
}

static inline bool
flow_equal(const struct flow *a, const struct flow *b)
{
    return !flow_compare_3way(a, b);
}

static inline size_t
flow_hash(const struct flow *flow, uint32_t basis)
{
    return hash_bytes(flow, FLOW_SIG_SIZE, basis);
}

/* Open vSwitch flow wildcard bits.
 *
 * These are used only internally to Open vSwitch, in the 'wildcards' member of
 * struct flow_wildcards.  They never appear in the wire protocol in this
 * form. */

typedef unsigned int OVS_BITWISE flow_wildcards_t;

/* Same values and meanings as corresponding OFPFW_* bits. */
#define FWW_IN_PORT     ((OVS_FORCE flow_wildcards_t) (1 << 0))
#define FWW_DL_SRC      ((OVS_FORCE flow_wildcards_t) (1 << 2))
#define FWW_DL_DST      ((OVS_FORCE flow_wildcards_t) (1 << 3))
                                              /* excluding the multicast bit */
#define FWW_DL_TYPE     ((OVS_FORCE flow_wildcards_t) (1 << 4))
#define FWW_NW_PROTO    ((OVS_FORCE flow_wildcards_t) (1 << 5))
#define FWW_TP_SRC      ((OVS_FORCE flow_wildcards_t) (1 << 6))
#define FWW_TP_DST      ((OVS_FORCE flow_wildcards_t) (1 << 7))
/* No corresponding OFPFW_* bits. */
#define FWW_ETH_MCAST   ((OVS_FORCE flow_wildcards_t) (1 << 1))
                                                       /* multicast bit only */
#define FWW_ARP_SHA     ((OVS_FORCE flow_wildcards_t) (1 << 8))
#define FWW_ARP_THA     ((OVS_FORCE flow_wildcards_t) (1 << 9))
#define FWW_ND_TARGET   ((OVS_FORCE flow_wildcards_t) (1 << 10))
#define FWW_IPV6_LABEL  ((OVS_FORCE flow_wildcards_t) (1 << 11))
#define FWW_NW_TTL      ((OVS_FORCE flow_wildcards_t) (1 << 12))
#define FWW_NW_DSCP     ((OVS_FORCE flow_wildcards_t) (1 << 13))
#define FWW_NW_ECN      ((OVS_FORCE flow_wildcards_t) (1 << 14))
#define FWW_ALL         ((OVS_FORCE flow_wildcards_t) (((1 << 15)) - 1))

/* Remember to update FLOW_WC_SEQ when adding or removing FWW_*. */
BUILD_ASSERT_DECL(FWW_ALL == ((1 << 15) - 1) && FLOW_WC_SEQ == 7);

/* Information on wildcards for a flow, as a supplement to "struct flow".
 *
 * Note that the meaning of 1-bits in 'wildcards' is opposite that of 1-bits in
 * the rest of the members. */
struct flow_wildcards {
    ovs_be64 tun_id_mask;       /* 1-bit in each significant tun_id bit. */
    flow_wildcards_t wildcards; /* 1-bit in each FWW_* wildcarded field. */
    uint32_t reg_masks[FLOW_N_REGS]; /* 1-bit in each significant regs bit. */
    ovs_be32 nw_src_mask;       /* 1-bit in each significant nw_src bit. */
    ovs_be32 nw_dst_mask;       /* 1-bit in each significant nw_dst bit. */
    struct in6_addr ipv6_src_mask; /* 1-bit in each signficant ipv6_src bit. */
    struct in6_addr ipv6_dst_mask; /* 1-bit in each signficant ipv6_dst bit. */
    ovs_be16 vlan_tci_mask;     /* 1-bit in each significant vlan_tci bit. */
    uint8_t nw_frag_mask;       /* 1-bit in each significant nw_frag bit. */
    uint8_t zeros[5];           /* Padding field set to zero. */
};

/* Remember to update FLOW_WC_SEQ when updating struct flow_wildcards. */
BUILD_ASSERT_DECL(sizeof(struct flow_wildcards) == 80 && FLOW_WC_SEQ == 7);

void flow_wildcards_init_catchall(struct flow_wildcards *);
void flow_wildcards_init_exact(struct flow_wildcards *);

bool flow_wildcards_is_exact(const struct flow_wildcards *);
bool flow_wildcards_is_catchall(const struct flow_wildcards *);

void flow_wildcards_set_reg_mask(struct flow_wildcards *,
                                 int idx, uint32_t mask);

void flow_wildcards_combine(struct flow_wildcards *dst,
                            const struct flow_wildcards *src1,
                            const struct flow_wildcards *src2);
bool flow_wildcards_has_extra(const struct flow_wildcards *,
                              const struct flow_wildcards *);

uint32_t flow_wildcards_hash(const struct flow_wildcards *, uint32_t basis);
bool flow_wildcards_equal(const struct flow_wildcards *,
                          const struct flow_wildcards *);
uint32_t flow_hash_symmetric_l4(const struct flow *flow, uint32_t basis);

const uint8_t *flow_wildcards_to_dl_dst_mask(flow_wildcards_t);
bool flow_wildcards_is_dl_dst_mask_valid(const uint8_t[6]);
flow_wildcards_t flow_wildcards_set_dl_dst_mask(flow_wildcards_t,
                                                const uint8_t mask[6]);
uint32_t flow_hash_fields(const struct flow *, enum nx_hash_fields,
                          uint16_t basis);
const char *flow_hash_fields_to_str(enum nx_hash_fields);
bool flow_hash_fields_valid(enum nx_hash_fields);

#endif /* flow.h */
