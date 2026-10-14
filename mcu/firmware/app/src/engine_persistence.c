#include "engine_persistence.h"
#include "engine_persistence_io.h"

#include <string.h>

extern uint32_t crc32_ieee(const uint8_t *data, size_t len);

static bool bank_is_blank(const engine_persist_record_t *record)
{
    return record->sequence == 0xFFFFFFFFu && record->crc32 == 0xFFFFFFFFu;
}

static bool bank_is_valid(const engine_persist_record_t *record)
{
    if (bank_is_blank(record)) {
        return false;
    }
    if (record->body.state_id >= STATE_COUNT) {

        return false;
    }
    uint32_t computed = crc32_ieee((const uint8_t *)&record->body, sizeof(record->body));
    return computed == record->crc32;
}

static engine_persist_bank_t other_bank(engine_persist_bank_t bank)
{
    return (bank == ENGINE_PERSIST_BANK_A) ? ENGINE_PERSIST_BANK_B : ENGINE_PERSIST_BANK_A;
}

static void encode_entry(engine_persist_entry_t *dst, const engine_context_entry_t *src)
{
    memset(dst, 0, sizeof(*dst));
    dst->kind = (uint8_t)src->value.kind;
    switch (src->value.kind) {
    case VAL_BOOL:
        dst->bool_value = src->value.b ? 1 : 0;
        break;
    case VAL_NUM:
        dst->num_value = src->value.num;
        break;
    case VAL_STR:

        if (src->value.str != NULL) {
            strncpy(dst->str_value, src->value.str, ENGINE_PERSIST_STR_MAX - 1);
        }
        break;
    case VAL_NONE:
    default:
        break;
    }
    if (src->name != NULL) {
        strncpy(dst->name, src->name, ENGINE_PERSIST_NAME_MAX - 1);
    }
}

static void encode_body(engine_persist_body_t *body, state_id_t state, const engine_context_t *context)
{
    memset(body, 0, sizeof(*body));
    body->state_id = (uint8_t)state;
    uint32_t count = context->count;
    if (count > ENGINE_CONTEXT_MAX_ENTRIES) {
        count = ENGINE_CONTEXT_MAX_ENTRIES;
    }
    body->context_count = (uint8_t)count;
    for (uint32_t i = 0; i < count; i++) {
        encode_entry(&body->entries[i], &context->entries[i]);
    }
}

static char g_decoded_names[ENGINE_CONTEXT_MAX_ENTRIES][ENGINE_PERSIST_NAME_MAX];
static char g_decoded_strs[ENGINE_CONTEXT_MAX_ENTRIES][ENGINE_PERSIST_STR_MAX];

static void decode_body(const engine_persist_body_t *body, state_id_t *out_state, engine_context_t *out_context)
{
    *out_state = (state_id_t)body->state_id;
    engine_context_init(out_context);
    uint32_t count = body->context_count;
    if (count > ENGINE_CONTEXT_MAX_ENTRIES) {
        count = ENGINE_CONTEXT_MAX_ENTRIES;
    }
    for (uint32_t i = 0; i < count; i++) {
        const engine_persist_entry_t *src = &body->entries[i];

        memcpy(g_decoded_names[i], src->name, ENGINE_PERSIST_NAME_MAX);
        g_decoded_names[i][ENGINE_PERSIST_NAME_MAX - 1] = '\0';

        val_t value;
        memset(&value, 0, sizeof(value));
        value.kind = (val_kind_t)src->kind;
        switch (value.kind) {
        case VAL_BOOL:
            value.b = src->bool_value != 0;
            break;
        case VAL_NUM:
            value.num = src->num_value;
            break;
        case VAL_STR:
            memcpy(g_decoded_strs[i], src->str_value, ENGINE_PERSIST_STR_MAX);
            g_decoded_strs[i][ENGINE_PERSIST_STR_MAX - 1] = '\0';
            value.str = g_decoded_strs[i];
            break;
        case VAL_NONE:
        default:
            break;
        }

        out_context->entries[i].name = g_decoded_names[i];
        out_context->entries[i].value = value;
    }
    out_context->count = count;
}

bool engine_persistence_load(engine_persisted_snapshot_t *out)
{
    engine_persist_record_t record_a;
    engine_persist_record_t record_b;
    bool have_a = engine_persist_io_read(ENGINE_PERSIST_BANK_A, &record_a);
    bool have_b = engine_persist_io_read(ENGINE_PERSIST_BANK_B, &record_b);

    bool valid_a = have_a && bank_is_valid(&record_a);
    bool valid_b = have_b && bank_is_valid(&record_b);

    if (!valid_a && !valid_b) {
        return false;
    }

    const engine_persist_record_t *winner;
    if (valid_a && valid_b) {
        winner = (record_a.sequence >= record_b.sequence) ? &record_a : &record_b;
    } else if (valid_a) {
        winner = &record_a;
    } else {
        winner = &record_b;
    }

    decode_body(&winner->body, &out->state, &out->context);
    return true;
}

void engine_persistence_save(state_id_t state, const engine_context_t *context)
{
    engine_persist_record_t record_a;
    engine_persist_record_t record_b;
    bool have_a = engine_persist_io_read(ENGINE_PERSIST_BANK_A, &record_a);
    bool have_b = engine_persist_io_read(ENGINE_PERSIST_BANK_B, &record_b);

    bool blank_a = !have_a || bank_is_blank(&record_a);
    bool blank_b = !have_b || bank_is_blank(&record_b);

    engine_persist_bank_t target;
    if (blank_a && blank_b) {
        target = ENGINE_PERSIST_BANK_A;
    } else if (blank_a) {
        target = ENGINE_PERSIST_BANK_A;
    } else if (blank_b) {
        target = ENGINE_PERSIST_BANK_B;
    } else {
        engine_persist_bank_t last_written =
            (record_a.sequence >= record_b.sequence) ? ENGINE_PERSIST_BANK_A : ENGINE_PERSIST_BANK_B;
        target = other_bank(last_written);
    }

    uint32_t next_sequence = 0;
    bool have_known = false;
    if (!blank_a) {
        next_sequence = record_a.sequence;
        have_known = true;
    }
    if (!blank_b) {
        if (!have_known || record_b.sequence > next_sequence) {
            next_sequence = record_b.sequence;
        }
        have_known = true;
    }
    if (have_known) {
        next_sequence += 1;
    }

    engine_persist_record_t new_record;
    memset(&new_record, 0, sizeof(new_record));
    new_record.sequence = next_sequence;
    encode_body(&new_record.body, state, context);
    new_record.crc32 = crc32_ieee((const uint8_t *)&new_record.body, sizeof(new_record.body));

    (void)engine_persist_io_write(target, &new_record);
}

bool engine_persistence_corrupt(engine_persist_bank_t bank)
{
    engine_persist_record_t record;
    if (!engine_persist_io_read(bank, &record)) {
        return false;
    }
    if (bank_is_blank(&record)) {

        return false;
    }

    uint8_t *first_byte = (uint8_t *)&record.body;
    *first_byte ^= 0xFFu;
    return engine_persist_io_write(bank, &record);
}
