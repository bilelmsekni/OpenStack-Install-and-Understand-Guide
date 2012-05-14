/*
 * Copyright (c) 2009, 2010, 2011 Nicira Networks.
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

#include <config.h>

#include "jsonrpc.h"

#include <assert.h>
#include <errno.h>

#include "byteq.h"
#include "dynamic-string.h"
#include "fatal-signal.h"
#include "json.h"
#include "list.h"
#include "ofpbuf.h"
#include "poll-loop.h"
#include "reconnect.h"
#include "stream.h"
#include "timeval.h"
#include "vlog.h"

VLOG_DEFINE_THIS_MODULE(jsonrpc);

struct jsonrpc {
    struct stream *stream;
    char *name;
    int status;

    /* Input. */
    struct byteq input;
    struct json_parser *parser;
    struct jsonrpc_msg *received;

    /* Output. */
    struct list output;         /* Contains "struct ofpbuf"s. */
    size_t backlog;
};

/* Rate limit for error messages. */
static struct vlog_rate_limit rl = VLOG_RATE_LIMIT_INIT(5, 5);

static void jsonrpc_received(struct jsonrpc *);
static void jsonrpc_cleanup(struct jsonrpc *);

/* This is just the same as stream_open() except that it uses the default
 * JSONRPC ports if none is specified. */
int
jsonrpc_stream_open(const char *name, struct stream **streamp)
{
    return stream_open_with_default_ports(name, JSONRPC_TCP_PORT,
                                          JSONRPC_SSL_PORT, streamp);
}

/* This is just the same as pstream_open() except that it uses the default
 * JSONRPC ports if none is specified. */
int
jsonrpc_pstream_open(const char *name, struct pstream **pstreamp)
{
    return pstream_open_with_default_ports(name, JSONRPC_TCP_PORT,
                                           JSONRPC_SSL_PORT, pstreamp);
}

struct jsonrpc *
jsonrpc_open(struct stream *stream)
{
    struct jsonrpc *rpc;

    assert(stream != NULL);

    rpc = xzalloc(sizeof *rpc);
    rpc->name = xstrdup(stream_get_name(stream));
    rpc->stream = stream;
    byteq_init(&rpc->input);
    list_init(&rpc->output);

    return rpc;
}

void
jsonrpc_close(struct jsonrpc *rpc)
{
    if (rpc) {
        jsonrpc_cleanup(rpc);
        free(rpc->name);
        free(rpc);
    }
}

void
jsonrpc_run(struct jsonrpc *rpc)
{
    if (rpc->status) {
        return;
    }

    stream_run(rpc->stream);
    while (!list_is_empty(&rpc->output)) {
        struct ofpbuf *buf = ofpbuf_from_list(rpc->output.next);
        int retval;

        retval = stream_send(rpc->stream, buf->data, buf->size);
        if (retval >= 0) {
            rpc->backlog -= retval;
            ofpbuf_pull(buf, retval);
            if (!buf->size) {
                list_remove(&buf->list_node);
                ofpbuf_delete(buf);
            }
        } else {
            if (retval != -EAGAIN) {
                VLOG_WARN_RL(&rl, "%s: send error: %s",
                             rpc->name, strerror(-retval));
                jsonrpc_error(rpc, -retval);
            }
            break;
        }
    }
}

void
jsonrpc_wait(struct jsonrpc *rpc)
{
    if (!rpc->status) {
        stream_run_wait(rpc->stream);
        if (!list_is_empty(&rpc->output)) {
            stream_send_wait(rpc->stream);
        }
    }
}

/*
 * Possible status values:
 * - 0: no error yet
 * - >0: errno value
 * - EOF: end of file (remote end closed connection; not necessarily an error)
 */
int
jsonrpc_get_status(const struct jsonrpc *rpc)
{
    return rpc->status;
}

size_t
jsonrpc_get_backlog(const struct jsonrpc *rpc)
{
    return rpc->status ? 0 : rpc->backlog;
}

const char *
jsonrpc_get_name(const struct jsonrpc *rpc)
{
    return rpc->name;
}

static void
jsonrpc_log_msg(const struct jsonrpc *rpc, const char *title,
                const struct jsonrpc_msg *msg)
{
    if (VLOG_IS_DBG_ENABLED()) {
        struct ds s = DS_EMPTY_INITIALIZER;
        if (msg->method) {
            ds_put_format(&s, ", method=\"%s\"", msg->method);
        }
        if (msg->params) {
            ds_put_cstr(&s, ", params=");
            json_to_ds(msg->params, 0, &s);
        }
        if (msg->result) {
            ds_put_cstr(&s, ", result=");
            json_to_ds(msg->result, 0, &s);
        }
        if (msg->error) {
            ds_put_cstr(&s, ", error=");
            json_to_ds(msg->error, 0, &s);
        }
        if (msg->id) {
            ds_put_cstr(&s, ", id=");
            json_to_ds(msg->id, 0, &s);
        }
        VLOG_DBG("%s: %s %s%s", rpc->name, title,
                 jsonrpc_msg_type_to_string(msg->type), ds_cstr(&s));
        ds_destroy(&s);
    }
}

/* Always takes ownership of 'msg', regardless of success. */
int
jsonrpc_send(struct jsonrpc *rpc, struct jsonrpc_msg *msg)
{
    struct ofpbuf *buf;
    struct json *json;
    size_t length;
    char *s;

    if (rpc->status) {
        jsonrpc_msg_destroy(msg);
        return rpc->status;
    }

    jsonrpc_log_msg(rpc, "send", msg);

    json = jsonrpc_msg_to_json(msg);
    s = json_to_string(json, 0);
    length = strlen(s);
    json_destroy(json);

    buf = xmalloc(sizeof *buf);
    ofpbuf_use(buf, s, length);
    buf->size = length;
    list_push_back(&rpc->output, &buf->list_node);
    rpc->backlog += length;

    if (rpc->backlog == length) {
        jsonrpc_run(rpc);
    }
    return rpc->status;
}

int
jsonrpc_recv(struct jsonrpc *rpc, struct jsonrpc_msg **msgp)
{
    *msgp = NULL;
    if (rpc->status) {
        return rpc->status;
    }

    while (!rpc->received) {
        if (byteq_is_empty(&rpc->input)) {
            size_t chunk;
            int retval;

            chunk = byteq_headroom(&rpc->input);
            retval = stream_recv(rpc->stream, byteq_head(&rpc->input), chunk);
            if (retval < 0) {
                if (retval == -EAGAIN) {
                    return EAGAIN;
                } else {
                    VLOG_WARN_RL(&rl, "%s: receive error: %s",
                                 rpc->name, strerror(-retval));
                    jsonrpc_error(rpc, -retval);
                    return rpc->status;
                }
            } else if (retval == 0) {
                jsonrpc_error(rpc, EOF);
                return EOF;
            }
            byteq_advance_head(&rpc->input, retval);
        } else {
            size_t n, used;

            if (!rpc->parser) {
                rpc->parser = json_parser_create(0);
            }
            n = byteq_tailroom(&rpc->input);
            used = json_parser_feed(rpc->parser,
                                    (char *) byteq_tail(&rpc->input), n);
            byteq_advance_tail(&rpc->input, used);
            if (json_parser_is_done(rpc->parser)) {
                jsonrpc_received(rpc);
                if (rpc->status) {
                    const struct byteq *q = &rpc->input;
                    if (q->head <= BYTEQ_SIZE) {
                        stream_report_content(q->buffer, q->head,
                                              STREAM_JSONRPC,
                                              THIS_MODULE, rpc->name);
                    }
                    return rpc->status;
                }
            }
        }
    }

    *msgp = rpc->received;
    rpc->received = NULL;
    return 0;
}

void
jsonrpc_recv_wait(struct jsonrpc *rpc)
{
    if (rpc->status || rpc->received || !byteq_is_empty(&rpc->input)) {
        (poll_immediate_wake)(rpc->name);
    } else {
        stream_recv_wait(rpc->stream);
    }
}

/* Always takes ownership of 'msg', regardless of success. */
int
jsonrpc_send_block(struct jsonrpc *rpc, struct jsonrpc_msg *msg)
{
    int error;

    fatal_signal_run();

    error = jsonrpc_send(rpc, msg);
    if (error) {
        return error;
    }

    for (;;) {
        jsonrpc_run(rpc);
        if (list_is_empty(&rpc->output) || rpc->status) {
            return rpc->status;
        }
        jsonrpc_wait(rpc);
        poll_block();
    }
}

int
jsonrpc_recv_block(struct jsonrpc *rpc, struct jsonrpc_msg **msgp)
{
    for (;;) {
        int error = jsonrpc_recv(rpc, msgp);
        if (error != EAGAIN) {
            fatal_signal_run();
            return error;
        }

        jsonrpc_run(rpc);
        jsonrpc_wait(rpc);
        jsonrpc_recv_wait(rpc);
        poll_block();
    }
}

/* Always takes ownership of 'request', regardless of success. */
int
jsonrpc_transact_block(struct jsonrpc *rpc, struct jsonrpc_msg *request,
                       struct jsonrpc_msg **replyp)
{
    struct jsonrpc_msg *reply = NULL;
    struct json *id;
    int error;

    id = json_clone(request->id);
    error = jsonrpc_send_block(rpc, request);
    if (!error) {
        for (;;) {
            error = jsonrpc_recv_block(rpc, &reply);
            if (error
                || (reply->type == JSONRPC_REPLY
                    && json_equal(id, reply->id))) {
                break;
            }
            jsonrpc_msg_destroy(reply);
        }
    }
    *replyp = error ? NULL : reply;
    json_destroy(id);
    return error;
}

static void
jsonrpc_received(struct jsonrpc *rpc)
{
    struct jsonrpc_msg *msg;
    struct json *json;
    char *error;

    json = json_parser_finish(rpc->parser);
    rpc->parser = NULL;
    if (json->type == JSON_STRING) {
        VLOG_WARN_RL(&rl, "%s: error parsing stream: %s",
                     rpc->name, json_string(json));
        jsonrpc_error(rpc, EPROTO);
        json_destroy(json);
        return;
    }

    error = jsonrpc_msg_from_json(json, &msg);
    if (error) {
        VLOG_WARN_RL(&rl, "%s: received bad JSON-RPC message: %s",
                     rpc->name, error);
        free(error);
        jsonrpc_error(rpc, EPROTO);
        return;
    }

    jsonrpc_log_msg(rpc, "received", msg);
    rpc->received = msg;
}

void
jsonrpc_error(struct jsonrpc *rpc, int error)
{
    assert(error);
    if (!rpc->status) {
        rpc->status = error;
        jsonrpc_cleanup(rpc);
    }
}

static void
jsonrpc_cleanup(struct jsonrpc *rpc)
{
    stream_close(rpc->stream);
    rpc->stream = NULL;

    json_parser_abort(rpc->parser);
    rpc->parser = NULL;

    jsonrpc_msg_destroy(rpc->received);
    rpc->received = NULL;

    ofpbuf_list_delete(&rpc->output);
    rpc->backlog = 0;
}

static struct jsonrpc_msg *
jsonrpc_create(enum jsonrpc_msg_type type, const char *method,
                struct json *params, struct json *result, struct json *error,
                struct json *id)
{
    struct jsonrpc_msg *msg = xmalloc(sizeof *msg);
    msg->type = type;
    msg->method = method ? xstrdup(method) : NULL;
    msg->params = params;
    msg->result = result;
    msg->error = error;
    msg->id = id;
    return msg;
}

static struct json *
jsonrpc_create_id(void)
{
    static unsigned int id;
    return json_integer_create(id++);
}

struct jsonrpc_msg *
jsonrpc_create_request(const char *method, struct json *params,
                       struct json **idp)
{
    struct json *id = jsonrpc_create_id();
    if (idp) {
        *idp = json_clone(id);
    }
    return jsonrpc_create(JSONRPC_REQUEST, method, params, NULL, NULL, id);
}

struct jsonrpc_msg *
jsonrpc_create_notify(const char *method, struct json *params)
{
    return jsonrpc_create(JSONRPC_NOTIFY, method, params, NULL, NULL, NULL);
}

struct jsonrpc_msg *
jsonrpc_create_reply(struct json *result, const struct json *id)
{
    return jsonrpc_create(JSONRPC_REPLY, NULL, NULL, result, NULL,
                           json_clone(id));
}

struct jsonrpc_msg *
jsonrpc_create_error(struct json *error, const struct json *id)
{
    return jsonrpc_create(JSONRPC_REPLY, NULL, NULL, NULL, error,
                           json_clone(id));
}

const char *
jsonrpc_msg_type_to_string(enum jsonrpc_msg_type type)
{
    switch (type) {
    case JSONRPC_REQUEST:
        return "request";

    case JSONRPC_NOTIFY:
        return "notification";

    case JSONRPC_REPLY:
        return "reply";

    case JSONRPC_ERROR:
        return "error";
    }
    return "(null)";
}

char *
jsonrpc_msg_is_valid(const struct jsonrpc_msg *m)
{
    const char *type_name;
    unsigned int pattern;

    if (m->params && m->params->type != JSON_ARRAY) {
        return xstrdup("\"params\" must be JSON array");
    }

    switch (m->type) {
    case JSONRPC_REQUEST:
        pattern = 0x11001;
        break;

    case JSONRPC_NOTIFY:
        pattern = 0x11000;
        break;

    case JSONRPC_REPLY:
        pattern = 0x00101;
        break;

    case JSONRPC_ERROR:
        pattern = 0x00011;
        break;

    default:
        return xasprintf("invalid JSON-RPC message type %d", m->type);
    }

    type_name = jsonrpc_msg_type_to_string(m->type);
    if ((m->method != NULL) != ((pattern & 0x10000) != 0)) {
        return xasprintf("%s must%s have \"method\"",
                         type_name, (pattern & 0x10000) ? "" : " not");

    }
    if ((m->params != NULL) != ((pattern & 0x1000) != 0)) {
        return xasprintf("%s must%s have \"params\"",
                         type_name, (pattern & 0x1000) ? "" : " not");

    }
    if ((m->result != NULL) != ((pattern & 0x100) != 0)) {
        return xasprintf("%s must%s have \"result\"",
                         type_name, (pattern & 0x100) ? "" : " not");

    }
    if ((m->error != NULL) != ((pattern & 0x10) != 0)) {
        return xasprintf("%s must%s have \"error\"",
                         type_name, (pattern & 0x10) ? "" : " not");

    }
    if ((m->id != NULL) != ((pattern & 0x1) != 0)) {
        return xasprintf("%s must%s have \"id\"",
                         type_name, (pattern & 0x1) ? "" : " not");

    }
    return NULL;
}

void
jsonrpc_msg_destroy(struct jsonrpc_msg *m)
{
    if (m) {
        free(m->method);
        json_destroy(m->params);
        json_destroy(m->result);
        json_destroy(m->error);
        json_destroy(m->id);
        free(m);
    }
}

static struct json *
null_from_json_null(struct json *json)
{
    if (json && json->type == JSON_NULL) {
        json_destroy(json);
        return NULL;
    }
    return json;
}

char *
jsonrpc_msg_from_json(struct json *json, struct jsonrpc_msg **msgp)
{
    struct json *method = NULL;
    struct jsonrpc_msg *msg = NULL;
    struct shash *object;
    char *error;

    if (json->type != JSON_OBJECT) {
        error = xstrdup("message is not a JSON object");
        goto exit;
    }
    object = json_object(json);

    method = shash_find_and_delete(object, "method");
    if (method && method->type != JSON_STRING) {
        error = xstrdup("method is not a JSON string");
        goto exit;
    }

    msg = xzalloc(sizeof *msg);
    msg->method = method ? xstrdup(method->u.string) : NULL;
    msg->params = null_from_json_null(shash_find_and_delete(object, "params"));
    msg->result = null_from_json_null(shash_find_and_delete(object, "result"));
    msg->error = null_from_json_null(shash_find_and_delete(object, "error"));
    msg->id = null_from_json_null(shash_find_and_delete(object, "id"));
    msg->type = (msg->result ? JSONRPC_REPLY
                 : msg->error ? JSONRPC_ERROR
                 : msg->id ? JSONRPC_REQUEST
                 : JSONRPC_NOTIFY);
    if (!shash_is_empty(object)) {
        error = xasprintf("message has unexpected member \"%s\"",
                          shash_first(object)->name);
        goto exit;
    }
    error = jsonrpc_msg_is_valid(msg);
    if (error) {
        goto exit;
    }

exit:
    json_destroy(method);
    json_destroy(json);
    if (error) {
        jsonrpc_msg_destroy(msg);
        msg = NULL;
    }
    *msgp = msg;
    return error;
}

struct json *
jsonrpc_msg_to_json(struct jsonrpc_msg *m)
{
    struct json *json = json_object_create();

    if (m->method) {
        json_object_put(json, "method", json_string_create_nocopy(m->method));
    }

    if (m->params) {
        json_object_put(json, "params", m->params);
    }

    if (m->result) {
        json_object_put(json, "result", m->result);
    } else if (m->type == JSONRPC_ERROR) {
        json_object_put(json, "result", json_null_create());
    }

    if (m->error) {
        json_object_put(json, "error", m->error);
    } else if (m->type == JSONRPC_REPLY) {
        json_object_put(json, "error", json_null_create());
    }

    if (m->id) {
        json_object_put(json, "id", m->id);
    } else if (m->type == JSONRPC_NOTIFY) {
        json_object_put(json, "id", json_null_create());
    }

    free(m);

    return json;
}

/* A JSON-RPC session with reconnection. */

struct jsonrpc_session {
    struct reconnect *reconnect;
    struct jsonrpc *rpc;
    struct stream *stream;
    struct pstream *pstream;
    unsigned int seqno;
};

/* Creates and returns a jsonrpc_session to 'name', which should be a string
 * acceptable to stream_open() or pstream_open().
 *
 * If 'name' is an active connection method, e.g. "tcp:127.1.2.3", the new
 * jsonrpc_session connects and reconnects, with back-off, to 'name'.
 *
 * If 'name' is a passive connection method, e.g. "ptcp:", the new
 * jsonrpc_session listens for connections to 'name'.  It maintains at most one
 * connection at any given time.  Any new connection causes the previous one
 * (if any) to be dropped. */
struct jsonrpc_session *
jsonrpc_session_open(const char *name)
{
    struct jsonrpc_session *s;

    s = xmalloc(sizeof *s);
    s->reconnect = reconnect_create(time_msec());
    reconnect_set_name(s->reconnect, name);
    reconnect_enable(s->reconnect, time_msec());
    s->rpc = NULL;
    s->stream = NULL;
    s->pstream = NULL;
    s->seqno = 0;

    if (!pstream_verify_name(name)) {
        reconnect_set_passive(s->reconnect, true, time_msec());
    }

    return s;
}

/* Creates and returns a jsonrpc_session that is initially connected to
 * 'jsonrpc'.  If the connection is dropped, it will not be reconnected.
 *
 * On the assumption that such connections are likely to be short-lived
 * (e.g. from ovs-vsctl), informational logging for them is suppressed. */
struct jsonrpc_session *
jsonrpc_session_open_unreliably(struct jsonrpc *jsonrpc)
{
    struct jsonrpc_session *s;

    s = xmalloc(sizeof *s);
    s->reconnect = reconnect_create(time_msec());
    reconnect_set_quiet(s->reconnect, true);
    reconnect_set_name(s->reconnect, jsonrpc_get_name(jsonrpc));
    reconnect_set_max_tries(s->reconnect, 0);
    reconnect_connected(s->reconnect, time_msec());
    s->rpc = jsonrpc;
    s->stream = NULL;
    s->pstream = NULL;
    s->seqno = 0;

    return s;
}

void
jsonrpc_session_close(struct jsonrpc_session *s)
{
    if (s) {
        jsonrpc_close(s->rpc);
        reconnect_destroy(s->reconnect);
        stream_close(s->stream);
        pstream_close(s->pstream);
        free(s);
    }
}

static void
jsonrpc_session_disconnect(struct jsonrpc_session *s)
{
    if (s->rpc) {
        jsonrpc_error(s->rpc, EOF);
        jsonrpc_close(s->rpc);
        s->rpc = NULL;
        s->seqno++;
    } else if (s->stream) {
        stream_close(s->stream);
        s->stream = NULL;
        s->seqno++;
    }
}

static void
jsonrpc_session_connect(struct jsonrpc_session *s)
{
    const char *name = reconnect_get_name(s->reconnect);
    int error;

    jsonrpc_session_disconnect(s);
    if (!reconnect_is_passive(s->reconnect)) {
        error = jsonrpc_stream_open(name, &s->stream);
        if (!error) {
            reconnect_connecting(s->reconnect, time_msec());
        }
    } else {
        error = s->pstream ? 0 : jsonrpc_pstream_open(name, &s->pstream);
        if (!error) {
            reconnect_listening(s->reconnect, time_msec());
        }
    }

    if (error) {
        reconnect_connect_failed(s->reconnect, time_msec(), error);
    }
    s->seqno++;
}

void
jsonrpc_session_run(struct jsonrpc_session *s)
{
    if (s->pstream) {
        struct stream *stream;
        int error;

        error = pstream_accept(s->pstream, &stream);
        if (!error) {
            if (s->rpc || s->stream) {
                VLOG_INFO_RL(&rl,
                             "%s: new connection replacing active connection",
                             reconnect_get_name(s->reconnect));
                jsonrpc_session_disconnect(s);
            }
            reconnect_connected(s->reconnect, time_msec());
            s->rpc = jsonrpc_open(stream);
        } else if (error != EAGAIN) {
            reconnect_listen_error(s->reconnect, time_msec(), error);
            pstream_close(s->pstream);
            s->pstream = NULL;
        }
    }

    if (s->rpc) {
        int error;

        jsonrpc_run(s->rpc);
        error = jsonrpc_get_status(s->rpc);
        if (error) {
            reconnect_disconnected(s->reconnect, time_msec(), error);
            jsonrpc_session_disconnect(s);
        }
    } else if (s->stream) {
        int error;

        stream_run(s->stream);
        error = stream_connect(s->stream);
        if (!error) {
            reconnect_connected(s->reconnect, time_msec());
            s->rpc = jsonrpc_open(s->stream);
            s->stream = NULL;
        } else if (error != EAGAIN) {
            reconnect_connect_failed(s->reconnect, time_msec(), error);
            stream_close(s->stream);
            s->stream = NULL;
        }
    }

    switch (reconnect_run(s->reconnect, time_msec())) {
    case RECONNECT_CONNECT:
        jsonrpc_session_connect(s);
        break;

    case RECONNECT_DISCONNECT:
        reconnect_disconnected(s->reconnect, time_msec(), 0);
        jsonrpc_session_disconnect(s);
        break;

    case RECONNECT_PROBE:
        if (s->rpc) {
            struct json *params;
            struct jsonrpc_msg *request;

            params = json_array_create_empty();
            request = jsonrpc_create_request("echo", params, NULL);
            json_destroy(request->id);
            request->id = json_string_create("echo");
            jsonrpc_send(s->rpc, request);
        }
        break;
    }
}

void
jsonrpc_session_wait(struct jsonrpc_session *s)
{
    if (s->rpc) {
        jsonrpc_wait(s->rpc);
    } else if (s->stream) {
        stream_run_wait(s->stream);
        stream_connect_wait(s->stream);
    }
    if (s->pstream) {
        pstream_wait(s->pstream);
    }
    reconnect_wait(s->reconnect, time_msec());
}

size_t
jsonrpc_session_get_backlog(const struct jsonrpc_session *s)
{
    return s->rpc ? jsonrpc_get_backlog(s->rpc) : 0;
}

/* Always returns a pointer to a valid C string, assuming 's' was initialized
 * correctly. */
const char *
jsonrpc_session_get_name(const struct jsonrpc_session *s)
{
    return reconnect_get_name(s->reconnect);
}

/* Always takes ownership of 'msg', regardless of success. */
int
jsonrpc_session_send(struct jsonrpc_session *s, struct jsonrpc_msg *msg)
{
    if (s->rpc) {
        return jsonrpc_send(s->rpc, msg);
    } else {
        jsonrpc_msg_destroy(msg);
        return ENOTCONN;
    }
}

struct jsonrpc_msg *
jsonrpc_session_recv(struct jsonrpc_session *s)
{
    if (s->rpc) {
        struct jsonrpc_msg *msg;
        jsonrpc_recv(s->rpc, &msg);
        if (msg) {
            reconnect_received(s->reconnect, time_msec());
            if (msg->type == JSONRPC_REQUEST && !strcmp(msg->method, "echo")) {
                /* Echo request.  Send reply. */
                struct jsonrpc_msg *reply;

                reply = jsonrpc_create_reply(json_clone(msg->params), msg->id);
                jsonrpc_session_send(s, reply);
            } else if (msg->type == JSONRPC_REPLY
                       && msg->id && msg->id->type == JSON_STRING
                       && !strcmp(msg->id->u.string, "echo")) {
                /* It's a reply to our echo request.  Suppress it. */
            } else {
                return msg;
            }
            jsonrpc_msg_destroy(msg);
        }
    }
    return NULL;
}

void
jsonrpc_session_recv_wait(struct jsonrpc_session *s)
{
    if (s->rpc) {
        jsonrpc_recv_wait(s->rpc);
    }
}

bool
jsonrpc_session_is_alive(const struct jsonrpc_session *s)
{
    return s->rpc || s->stream || reconnect_get_max_tries(s->reconnect);
}

bool
jsonrpc_session_is_connected(const struct jsonrpc_session *s)
{
    return s->rpc != NULL;
}

unsigned int
jsonrpc_session_get_seqno(const struct jsonrpc_session *s)
{
    return s->seqno;
}

int
jsonrpc_session_get_status(const struct jsonrpc_session *s)
{
    return s && s->rpc ? jsonrpc_get_status(s->rpc) : 0;
}

void
jsonrpc_session_get_reconnect_stats(const struct jsonrpc_session *s,
                                    struct reconnect_stats *stats)
{
    reconnect_get_stats(s->reconnect, time_msec(), stats);
}

void
jsonrpc_session_force_reconnect(struct jsonrpc_session *s)
{
    reconnect_force_reconnect(s->reconnect, time_msec());
}

void
jsonrpc_session_set_max_backoff(struct jsonrpc_session *s, int max_backoff)
{
    reconnect_set_backoff(s->reconnect, 0, max_backoff);
}

void
jsonrpc_session_set_probe_interval(struct jsonrpc_session *s,
                                   int probe_interval)
{
    reconnect_set_probe_interval(s->reconnect, probe_interval);
}
