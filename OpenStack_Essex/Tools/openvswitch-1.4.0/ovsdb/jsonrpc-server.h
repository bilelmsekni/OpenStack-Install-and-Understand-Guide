/* Copyright (c) 2009, 2010, 2011 Nicira Networks
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

#ifndef OVSDB_JSONRPC_SERVER_H
#define OVSDB_JSONRPC_SERVER_H 1

#include <stdbool.h>

struct ovsdb;
struct shash;

struct ovsdb_jsonrpc_server *ovsdb_jsonrpc_server_create(struct ovsdb *);
void ovsdb_jsonrpc_server_destroy(struct ovsdb_jsonrpc_server *);

/* Options for a remote. */
struct ovsdb_jsonrpc_options {
    int max_backoff;            /* Maximum reconnection backoff, in msec. */
    int probe_interval;         /* Max idle time before probing, in msec. */
};
struct ovsdb_jsonrpc_options *ovsdb_jsonrpc_default_options(void);

void ovsdb_jsonrpc_server_set_remotes(struct ovsdb_jsonrpc_server *,
                                      const struct shash *);

/* Status of a single remote connection. */
struct ovsdb_jsonrpc_remote_status {
    const char *state;
    int last_error;
    unsigned int sec_since_connect;
    unsigned int sec_since_disconnect;
    bool is_connected;
    char *locks_held;
    char *locks_waiting;
    char *locks_lost;
    int n_connections;
};
bool ovsdb_jsonrpc_server_get_remote_status(
    const struct ovsdb_jsonrpc_server *, const char *target,
    struct ovsdb_jsonrpc_remote_status *);
void ovsdb_jsonrpc_server_free_remote_status(
    struct ovsdb_jsonrpc_remote_status *);

void ovsdb_jsonrpc_server_reconnect(struct ovsdb_jsonrpc_server *);

void ovsdb_jsonrpc_server_run(struct ovsdb_jsonrpc_server *);
void ovsdb_jsonrpc_server_wait(struct ovsdb_jsonrpc_server *);

#endif /* ovsdb/jsonrpc-server.h */
