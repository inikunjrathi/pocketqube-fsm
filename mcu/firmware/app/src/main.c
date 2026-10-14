/* SPDX-License-Identifier: Apache-2.0 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "engine_fsm.h"
#include "engine_persistence.h"
#include "engine_auth.h"
#include "engine_scheduler.h"

#define UART_DEVICE_NODE DT_CHOSEN(zephyr_console)

static const struct device *const uart_dev = DEVICE_DT_GET(UART_DEVICE_NODE);

#define LINE_BUF_SIZE 512

static char line_buf[LINE_BUF_SIZE];
static size_t line_len;
static bool line_overflowed;

static void uart_write_str(const char *s)
{
    while (*s != '\0') {
        uart_poll_out(uart_dev, (uint8_t)*s);
        s++;
    }
}

static void uart_write_line_end(void)
{
    uart_poll_out(uart_dev, '\n');
}

static void reply_error(const char *reason)
{
    uart_write_str("ERROR ");
    uart_write_str(reason);
    uart_write_line_end();
}

static void reply_error_detail(const char *reason, const char *detail)
{
    uart_write_str("ERROR ");
    uart_write_str(reason);
    uart_write_str(" ");
    uart_write_str(detail);
    uart_write_line_end();
}

#if ENGINE_PERSIST_TESTHOOKS_ENABLED || ENGINE_SCHED_TESTHOOKS_ENABLED

static void reply_ok(void)
{
    uart_write_str("OK");
    uart_write_line_end();
}
#endif

static void format_double(double value, char *out, size_t out_size)
{
    bool negative = value < 0.0;
    if (negative) {
        value = -value;
    }
    long int_part = (long)value;
    double frac = value - (double)int_part;
    long frac_scaled = (long)(frac * 1000000.0 + 0.5);
    if (frac_scaled >= 1000000L) {
        int_part += 1;
        frac_scaled -= 1000000L;
    }
    if (frac_scaled == 0) {
        snprintf(out, out_size, "%s%ld", negative ? "-" : "", int_part);
        return;
    }

    char frac_buf[16];
    snprintf(frac_buf, sizeof(frac_buf), "%06ld", frac_scaled);
    size_t frac_len = strlen(frac_buf);
    while (frac_len > 1 && frac_buf[frac_len - 1] == '0') {
        frac_len--;
    }
    frac_buf[frac_len] = '\0';
    snprintf(out, out_size, "%s%ld.%s", negative ? "-" : "", int_part, frac_buf);
}

static void send_decision_line(double now, const char *from_state, const char *event_id,
                                const char *to_state, const char *transition_id, bool legal,
                                const action_t *actions, uint8_t actions_count)
{
    char now_buf[32];

    format_double(now, now_buf, sizeof(now_buf));

    uart_write_str("DECISION ");
    uart_write_str(now_buf);
    uart_write_str(" ");
    uart_write_str(from_state);
    uart_write_str(" ");
    uart_write_str(event_id);
    uart_write_str(" -> ");
    uart_write_str(to_state);
    uart_write_str(" transition=");
    uart_write_str(transition_id != NULL ? transition_id : "NONE");
    uart_write_str(" legal=");
    uart_write_str(legal ? "1" : "0");
    uart_write_str(" actions=");
    if (actions_count == 0) {
        uart_write_str("NONE");
    } else {
        for (uint8_t i = 0; i < actions_count; i++) {
            if (i > 0) {
                uart_write_str(",");
            }
            uart_write_str(actions[i].raw);
        }
    }
    uart_write_line_end();
}

static char *next_token(char **cursor)
{
    char *p = *cursor;

    while (*p == ' ') {
        p++;
    }
    if (*p == '\0') {
        *cursor = p;
        return NULL;
    }
    char *start = p;

    while (*p != '\0' && *p != ' ') {
        p++;
    }
    if (*p != '\0') {
        *p = '\0';
        p++;
    }
    *cursor = p;
    return start;
}

static bool looks_like_number(const char *s)
{
    const char *p = s;

    if (*p == '-') {
        p++;
    }
    if (*p < '0' || *p > '9') {
        return false;
    }
    while (*p >= '0' && *p <= '9') {
        p++;
    }
    if (*p == '.') {
        p++;
        if (*p < '0' || *p > '9') {
            return false;
        }
        while (*p >= '0' && *p <= '9') {
            p++;
        }
    }
    return *p == '\0';
}

static val_t parse_wire_value(const char *token)
{
    if (strcmp(token, "true") == 0) {
        return (val_t){ .kind = VAL_BOOL, .b = true };
    }
    if (strcmp(token, "false") == 0) {
        return (val_t){ .kind = VAL_BOOL, .b = false };
    }
    if (looks_like_number(token)) {
        return (val_t){ .kind = VAL_NUM, .num = strtod(token, NULL) };
    }
    return (val_t){ .kind = VAL_STR, .str = token };
}

static bool parse_kv(char *token, const char **out_key, val_t *out_value)
{
    char *eq = strchr(token, '=');

    if (eq == NULL || eq == token) {
        return false;
    }
    *eq = '\0';
    *out_key = token;
    *out_value = parse_wire_value(eq + 1);
    return true;
}

static bool is_valid_hex64(const char *s)
{
    size_t n = strlen(s);

    if (n != 64) {
        return false;
    }
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        bool is_hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
        if (!is_hex) {
            return false;
        }
    }
    return true;
}

static void handle_inject(char *args)
{
    char *cursor = args;
    char *event_tok = next_token(&cursor);
    char *state_tok = next_token(&cursor);
    char *now_tok = next_token(&cursor);

    if (event_tok == NULL || state_tok == NULL || now_tok == NULL) {
        reply_error("missing_fields");
        return;
    }

    event_id_t event;
    if (!engine_lookup_event(event_tok, &event)) {
        reply_error_detail("unknown_event", event_tok);
        return;
    }
    state_id_t state;
    if (!engine_lookup_state(state_tok, &state)) {
        reply_error_detail("unknown_state", state_tok);
        return;
    }

    char *now_endptr = NULL;
    double now = strtod(now_tok, &now_endptr);
    if (now_endptr == now_tok || *now_endptr != '\0') {
        reply_error_detail("bad_now", now_tok);
        return;
    }

    engine_context_t ctx;
    engine_context_init(&ctx);
    engine_telemetry_t tlm;
    engine_telemetry_init(&tlm);

    bool saw_semicolon = false;
    char *tok;
    while ((tok = next_token(&cursor)) != NULL) {
        if (strcmp(tok, ";") == 0) {
            saw_semicolon = true;
            break;
        }
        const char *key;
        val_t value;
        if (!parse_kv(tok, &key, &value)) {
            reply_error_detail("bad_context_kv", tok);
            return;
        }
        if (!engine_context_set(&ctx, key, value)) {
            reply_error_detail("context_overflow", key);
            return;
        }
    }
    if (!saw_semicolon) {
        reply_error("missing_semicolon_separator");
        return;
    }

    const char *signature = NULL;
    while ((tok = next_token(&cursor)) != NULL) {
        if (strcmp(tok, "SIG") == 0) {
            char *sig_tok = next_token(&cursor);
            if (sig_tok == NULL || !is_valid_hex64(sig_tok)) {
                reply_error("bad_signature");
                return;
            }
            signature = sig_tok;
            if (next_token(&cursor) != NULL) {
                reply_error("trailing_tokens_after_sig");
                return;
            }
            break;
        }
        const char *key;
        val_t value;
        if (!parse_kv(tok, &key, &value)) {
            reply_error_detail("bad_telemetry_kv", tok);
            return;
        }
        if (value.kind != VAL_NUM) {
            reply_error_detail("telemetry_value_not_numeric", key);
            return;
        }
        if (!engine_telemetry_set(&tlm, key, value.num)) {
            reply_error_detail("telemetry_overflow", key);
            return;
        }
    }

    engine_persisted_snapshot_t persisted;
    bool has_persisted = engine_persistence_load(&persisted);

    engine_step_result_t result;
    engine_context_t out_ctx;
    const char *error_field = NULL;
    engine_step_status_t status = engine_fsm_step(
        state, event, &ctx, &tlm, now,
        has_persisted ? &persisted : NULL,
        signature,
        &result, &out_ctx, &error_field);

    if (status == ENGINE_STEP_ERR_GUARD_TELEMETRY_MISSING) {

        reply_error_detail("guard_telemetry_missing", error_field != NULL ? error_field : "(unknown)");
        return;
    }

    if (result.legal) {

        engine_persistence_save(result.new_state, &out_ctx);
    }

    send_decision_line(now, g_states[state].id, g_events[event].id,
                        g_states[result.new_state].id, result.transition_id,
                        result.legal, result.actions, result.actions_count);
}

#if ENGINE_PERSIST_TESTHOOKS_ENABLED

static bool handle_testhook_load(void)
{
    engine_persisted_snapshot_t snap;

    if (!engine_persistence_load(&snap)) {
        reply_error("testhook_load_no_record");
        return true;
    }

    val_t latch_value;
    bool has_latch = engine_context_get(&snap.context, "deployment_confirmed", &latch_value);

    bool latch_true = has_latch && latch_value.kind == VAL_BOOL && latch_value.b;

    uart_write_str("OK state=");
    uart_write_str(g_states[snap.state].id);
    uart_write_str(" deployment_confirmed=");
    uart_write_str(latch_true ? "1" : "0");
    uart_write_line_end();
    return true;
}

static bool handle_testhook_corrupt(char *cursor)
{
    char *bank_tok = next_token(&cursor);
    if (bank_tok == NULL || bank_tok[1] != '\0') {
        reply_error("bad_testhook_bank");
        return true;
    }

    engine_persist_bank_t bank;
    if (bank_tok[0] == 'A') {
        bank = ENGINE_PERSIST_BANK_A;
    } else if (bank_tok[0] == 'B') {
        bank = ENGINE_PERSIST_BANK_B;
    } else {
        reply_error("bad_testhook_bank");
        return true;
    }

    if (!engine_persistence_corrupt(bank)) {
        reply_error("testhook_corrupt_failed");
        return true;
    }

    reply_ok();
    return true;
}
#endif

#if ENGINE_SCHED_TESTHOOKS_ENABLED

static engine_scheduler_t g_test_scheduler;

static void reply_sched_item(const engine_sched_item_t *item)
{
    char size_buf[16];
    char deadline_buf[32];

    snprintf(size_buf, sizeof(size_buf), "%lu", (unsigned long)item->size_bytes);
    if (item->has_deadline) {
        format_double(item->deadline, deadline_buf, sizeof(deadline_buf));
    }

    uart_write_str("OK id=");
    uart_write_str(item->id);
    uart_write_str(" data_class=");
    uart_write_str(item->data_class);
    uart_write_str(" size_bytes=");
    uart_write_str(size_buf);
    uart_write_str(" deadline=");
    uart_write_str(item->has_deadline ? deadline_buf : "NONE");
    uart_write_line_end();
}

static bool handle_testhook_sched_reset(char *cursor)
{
    char *classes_tok = next_token(&cursor);
    if (classes_tok == NULL || next_token(&cursor) != NULL) {
        reply_error("bad_sched_reset_classes");
        return true;
    }

    if (strcmp(classes_tok, "NONE") == 0) {
        engine_scheduler_init(&g_test_scheduler, NULL, 0);
        reply_ok();
        return true;
    }

    const char *classes[ENGINE_SCHED_MAX_CLASSES];
    uint8_t n = 0;
    char *p = classes_tok;
    while (p != NULL) {
        if (n >= ENGINE_SCHED_MAX_CLASSES) {
            reply_error("bad_sched_reset_classes");
            return true;
        }
        char *comma = strchr(p, ',');
        if (comma != NULL) {
            *comma = '\0';
        }
        if (*p == '\0' || strlen(p) >= ENGINE_SCHED_CLASS_NAME_MAX) {
            reply_error("bad_sched_reset_classes");
            return true;
        }
        classes[n++] = p;
        p = (comma != NULL) ? comma + 1 : NULL;
    }

    engine_scheduler_init(&g_test_scheduler, classes, n);
    reply_ok();
    return true;
}

static bool handle_testhook_sched_insert(char *cursor)
{
    char *id_tok = next_token(&cursor);
    char *class_tok = next_token(&cursor);
    char *size_tok = next_token(&cursor);
    char *deadline_tok = next_token(&cursor);

    if (id_tok == NULL || class_tok == NULL || size_tok == NULL || deadline_tok == NULL ||
        next_token(&cursor) != NULL) {
        reply_error("bad_sched_insert_args");
        return true;
    }

    engine_sched_item_t item;
    memset(&item, 0, sizeof(item));

    if (strlen(id_tok) >= ENGINE_SCHED_ITEM_ID_MAX || strlen(class_tok) >= ENGINE_SCHED_CLASS_NAME_MAX) {
        reply_error("bad_sched_insert_args");
        return true;
    }
    strcpy(item.id, id_tok);
    strcpy(item.data_class, class_tok);

    char *size_endptr = NULL;
    unsigned long size_val = strtoul(size_tok, &size_endptr, 10);
    if (size_endptr == size_tok || *size_endptr != '\0') {
        reply_error("bad_sched_size_bytes");
        return true;
    }
    item.size_bytes = (uint32_t)size_val;

    if (strcmp(deadline_tok, "NONE") == 0) {
        item.has_deadline = false;
    } else {
        char *deadline_endptr = NULL;
        double deadline_val = strtod(deadline_tok, &deadline_endptr);
        if (deadline_endptr == deadline_tok || *deadline_endptr != '\0') {
            reply_error("bad_sched_deadline");
            return true;
        }
        item.has_deadline = true;
        item.deadline = deadline_val;
    }

    engine_sched_status_t status = engine_scheduler_insert(&g_test_scheduler, &item);
    if (status == ENGINE_SCHED_ERR_UNKNOWN_CLASS) {
        reply_error_detail("sched_unknown_class", item.data_class);
        return true;
    }
    if (status == ENGINE_SCHED_ERR_QUEUE_FULL) {
        reply_error("sched_queue_full");
        return true;
    }

    reply_ok();
    return true;
}

static bool handle_testhook_sched(char *args)
{
    char *cursor = args;
    char *op_tok = next_token(&cursor);

    if (op_tok == NULL) {
        return false;
    }

    if (strcmp(op_tok, "RESET") == 0) {
        return handle_testhook_sched_reset(cursor);
    }
    if (strcmp(op_tok, "INSERT") == 0) {
        return handle_testhook_sched_insert(cursor);
    }
    if (strcmp(op_tok, "SELECT") == 0 || strcmp(op_tok, "SELECT_EDF") == 0) {
        engine_sched_key_fn key = (strcmp(op_tok, "SELECT_EDF") == 0) ? engine_scheduler_edf_key : NULL;
        engine_sched_item_t out;
        if (engine_scheduler_select_next(&g_test_scheduler, key, &out)) {
            reply_sched_item(&out);
        } else {
            uart_write_str("OK NONE");
            uart_write_line_end();
        }
        return true;
    }
    if (strcmp(op_tok, "PEEK_CLASS") == 0) {
        char class_buf[ENGINE_SCHED_CLASS_NAME_MAX];
        if (engine_scheduler_peek_next_class(&g_test_scheduler, class_buf, sizeof(class_buf))) {
            uart_write_str("OK data_class=");
            uart_write_str(class_buf);
            uart_write_line_end();
        } else {
            uart_write_str("OK NONE");
            uart_write_line_end();
        }
        return true;
    }
    if (strcmp(op_tok, "CANDIDATES") == 0) {
        char classes[ENGINE_SCHED_QUEUE_CAPACITY][ENGINE_SCHED_CLASS_NAME_MAX];
        uint8_t n = engine_scheduler_candidate_classes(&g_test_scheduler, classes, ENGINE_SCHED_QUEUE_CAPACITY);
        if (n == 0) {
            uart_write_str("OK classes=NONE");
        } else {
            uart_write_str("OK classes=");
            for (uint8_t i = 0; i < n; i++) {
                if (i > 0) {
                    uart_write_str(",");
                }
                uart_write_str(classes[i]);
            }
        }
        uart_write_line_end();
        return true;
    }
    if (strcmp(op_tok, "IS_EMPTY") == 0) {
        uart_write_str("OK empty=");
        uart_write_str(engine_scheduler_is_empty(&g_test_scheduler) ? "1" : "0");
        uart_write_line_end();
        return true;
    }
    if (strcmp(op_tok, "ALL_ITEMS") == 0) {
        engine_sched_item_t items[ENGINE_SCHED_QUEUE_CAPACITY];
        uint8_t n = engine_scheduler_all_items(&g_test_scheduler, items, ENGINE_SCHED_QUEUE_CAPACITY);
        if (n == 0) {
            uart_write_str("OK ids=NONE");
        } else {
            uart_write_str("OK ids=");
            for (uint8_t i = 0; i < n; i++) {
                if (i > 0) {
                    uart_write_str(",");
                }
                uart_write_str(items[i].id);
            }
        }
        uart_write_line_end();
        return true;
    }

    return false;
}
#endif

#if ENGINE_PERSIST_TESTHOOKS_ENABLED || ENGINE_SCHED_TESTHOOKS_ENABLED

static bool handle_testhook(char *args)
{
    char *cursor = args;
    char *name_tok = next_token(&cursor);

    if (name_tok == NULL) {
        return false;
    }

#if ENGINE_PERSIST_TESTHOOKS_ENABLED
    if (strcmp(name_tok, "LOAD") == 0) {
        return handle_testhook_load();
    }
    if (strcmp(name_tok, "CORRUPT") == 0) {
        return handle_testhook_corrupt(cursor);
    }
#endif
#if ENGINE_SCHED_TESTHOOKS_ENABLED
    if (strcmp(name_tok, "SCHED") == 0) {
        return handle_testhook_sched(cursor);
    }
#endif

    return false;
}
#endif

static void handle_line(char *line)
{
    size_t n = strlen(line);

    if (n > 0 && line[n - 1] == '\r') {
        line[n - 1] = '\0';
        n--;
    }
    if (n == 0) {
        return;
    }

    if (strncmp(line, "INJECT ", 7) == 0) {
        handle_inject(line + 7);
    } else if (strcmp(line, "INJECT") == 0) {
        reply_error("missing_fields");
    } else if (strncmp(line, "TESTHOOK ", 9) == 0) {
#if ENGINE_PERSIST_TESTHOOKS_ENABLED || ENGINE_SCHED_TESTHOOKS_ENABLED
        if (!handle_testhook(line + 9)) {
            reply_error("testhook_not_implemented");
        }
#else
        reply_error("testhook_not_implemented");
#endif
    } else if (strcmp(line, "TESTHOOK") == 0) {
        reply_error("testhook_not_implemented");
    } else {
        reply_error_detail("unknown_command", line);
    }
}

static void uart_dispatch_isr(const struct device *dev, void *user_data)
{
    ARG_UNUSED(user_data);
    uint8_t c;

    if (!uart_irq_update(dev)) {
        return;
    }
    if (!uart_irq_rx_ready(dev)) {
        return;
    }

    while (uart_fifo_read(dev, &c, 1) == 1) {
        if (c == '\n') {
            if (line_overflowed) {
                reply_error("line_too_long");
            } else {
                line_buf[line_len] = '\0';
                handle_line(line_buf);
            }
            line_len = 0;
            line_overflowed = false;
        } else if (c == '\r') {

        } else if (line_len < LINE_BUF_SIZE - 1) {
            line_buf[line_len++] = (char)c;
        } else {
            line_overflowed = true;
        }
    }
}

#if ENGINE_GROUND_AUTH_ENABLED

static const uint8_t TASK5_TEST_HARNESS_GROUND_AUTH_SECRET[] =
    "phase8-task5-test-harness-secret-do-not-use-in-flight";
#endif

int main(void)
{
    int ret;

    if (!device_is_ready(uart_dev)) {
        return 0;
    }

    ret = uart_irq_callback_user_data_set(uart_dev, uart_dispatch_isr, NULL);
    if (ret < 0) {
        return 0;
    }

#if ENGINE_GROUND_AUTH_ENABLED
    engine_auth_set_secret(TASK5_TEST_HARNESS_GROUND_AUTH_SECRET,
                            sizeof(TASK5_TEST_HARNESS_GROUND_AUTH_SECRET) - 1);
#endif

    uart_irq_rx_enable(uart_dev);

    uart_write_str("READY");
    uart_write_line_end();

    return 0;
}
