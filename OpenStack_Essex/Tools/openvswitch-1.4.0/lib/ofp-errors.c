/* -*- buffer-read-only: t -*- */
#include <config.h>
#include "ofp-errors.h"
#include <inttypes.h>
#include <stdio.h>
#include "openflow/openflow.h"
#include "openflow/nicira-ext.h"
#include "type-props.h"

static const char *
ofp_bad_action_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPBAC_BAD_TYPE: return "OFPBAC_BAD_TYPE";
    case OFPBAC_BAD_LEN: return "OFPBAC_BAD_LEN";
    case OFPBAC_BAD_VENDOR: return "OFPBAC_BAD_VENDOR";
    case OFPBAC_BAD_VENDOR_TYPE: return "OFPBAC_BAD_VENDOR_TYPE";
    case OFPBAC_BAD_OUT_PORT: return "OFPBAC_BAD_OUT_PORT";
    case OFPBAC_BAD_ARGUMENT: return "OFPBAC_BAD_ARGUMENT";
    case OFPBAC_EPERM: return "OFPBAC_EPERM";
    case OFPBAC_TOO_MANY: return "OFPBAC_TOO_MANY";
    case OFPBAC_BAD_QUEUE: return "OFPBAC_BAD_QUEUE";
    }
    return NULL;
}

static const char *
ofp_bad_request_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPBRC_BAD_VERSION: return "OFPBRC_BAD_VERSION";
    case OFPBRC_BAD_TYPE: return "OFPBRC_BAD_TYPE";
    case OFPBRC_BAD_STAT: return "OFPBRC_BAD_STAT";
    case OFPBRC_BAD_VENDOR: return "OFPBRC_BAD_VENDOR";
    case OFPBRC_BAD_SUBTYPE: return "OFPBRC_BAD_SUBTYPE";
    case OFPBRC_EPERM: return "OFPBRC_EPERM";
    case OFPBRC_BAD_LEN: return "OFPBRC_BAD_LEN";
    case OFPBRC_BUFFER_EMPTY: return "OFPBRC_BUFFER_EMPTY";
    case OFPBRC_BUFFER_UNKNOWN: return "OFPBRC_BUFFER_UNKNOWN";
    case NXBRC_NXM_INVALID: return "NXBRC_NXM_INVALID";
    case NXBRC_NXM_BAD_TYPE: return "NXBRC_NXM_BAD_TYPE";
    case NXBRC_NXM_BAD_VALUE: return "NXBRC_NXM_BAD_VALUE";
    case NXBRC_NXM_BAD_MASK: return "NXBRC_NXM_BAD_MASK";
    case NXBRC_NXM_BAD_PREREQ: return "NXBRC_NXM_BAD_PREREQ";
    case NXBRC_NXM_DUP_TYPE: return "NXBRC_NXM_DUP_TYPE";
    case NXBRC_BAD_TABLE_ID: return "NXBRC_BAD_TABLE_ID";
    case NXBRC_BAD_ROLE: return "NXBRC_BAD_ROLE";
    case NXBRC_BAD_IN_PORT: return "NXBRC_BAD_IN_PORT";
    }
    return NULL;
}

static const char *
ofp_flow_mod_failed_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPFMFC_ALL_TABLES_FULL: return "OFPFMFC_ALL_TABLES_FULL";
    case OFPFMFC_OVERLAP: return "OFPFMFC_OVERLAP";
    case OFPFMFC_EPERM: return "OFPFMFC_EPERM";
    case OFPFMFC_BAD_EMERG_TIMEOUT: return "OFPFMFC_BAD_EMERG_TIMEOUT";
    case OFPFMFC_BAD_COMMAND: return "OFPFMFC_BAD_COMMAND";
    case OFPFMFC_UNSUPPORTED: return "OFPFMFC_UNSUPPORTED";
    case NXFMFC_HARDWARE: return "NXFMFC_HARDWARE";
    case NXFMFC_BAD_TABLE_ID: return "NXFMFC_BAD_TABLE_ID";
    }
    return NULL;
}

static const char *
ofp_hello_failed_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPHFC_INCOMPATIBLE: return "OFPHFC_INCOMPATIBLE";
    case OFPHFC_EPERM: return "OFPHFC_EPERM";
    }
    return NULL;
}

static const char *
ofp_port_mod_failed_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPPMFC_BAD_PORT: return "OFPPMFC_BAD_PORT";
    case OFPPMFC_BAD_HW_ADDR: return "OFPPMFC_BAD_HW_ADDR";
    }
    return NULL;
}

static const char *
ofp_queue_op_failed_code_to_string(uint16_t value)
{
    switch (value) {
    case OFPQOFC_BAD_PORT: return "OFPQOFC_BAD_PORT";
    case OFPQOFC_BAD_QUEUE: return "OFPQOFC_BAD_QUEUE";
    case OFPQOFC_EPERM: return "OFPQOFC_EPERM";
    }
    return NULL;
}

const char *
ofp_error_type_to_string(uint16_t value)
{
    switch (value) {
    case OFPET_FLOW_MOD_FAILED: return "OFPET_FLOW_MOD_FAILED";
    case OFPET_BAD_REQUEST: return "OFPET_BAD_REQUEST";
    case OFPET_BAD_ACTION: return "OFPET_BAD_ACTION";
    case OFPET_QUEUE_OP_FAILED: return "OFPET_QUEUE_OP_FAILED";
    case OFPET_PORT_MOD_FAILED: return "OFPET_PORT_MOD_FAILED";
    case OFPET_HELLO_FAILED: return "OFPET_HELLO_FAILED";
    }
    return NULL;
}

const char *
ofp_error_code_to_string(uint16_t type, uint16_t code)
{
    switch (type) {
    case OFPET_FLOW_MOD_FAILED:
        return ofp_flow_mod_failed_code_to_string(code);
    case OFPET_BAD_REQUEST:
        return ofp_bad_request_code_to_string(code);
    case OFPET_BAD_ACTION:
        return ofp_bad_action_code_to_string(code);
    case OFPET_QUEUE_OP_FAILED:
        return ofp_queue_op_failed_code_to_string(code);
    case OFPET_PORT_MOD_FAILED:
        return ofp_port_mod_failed_code_to_string(code);
    case OFPET_HELLO_FAILED:
        return ofp_hello_failed_code_to_string(code);
    }
    return NULL;
}
