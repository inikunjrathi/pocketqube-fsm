#include "engine_persistence.h"
#include "engine_persistence_io.h"
#include "engine_config_table.h"

#include <stddef.h>
#include <string.h>


extern uint32_t crc32_ieee(const uint8_t *data, size_t len);


static bool bank_is_blank(const engine_persist_record_t *record)
{
    return record->sequence == 0xFFFFFFFFu && record->crc32 == 0xFFFFFFFFu;
}

static uint32_t record_crc(const engine_persist_record_t *record)
{
    return crc32_ieee((const uint8_t *)record, offsetof(engine_persist_record_t, crc32));
}

static bool bank_is_valid(const engine_persist_record_t *record)
{
    if (bank_is_blank(record)) {
        return false;
    }
    if (record->body.state_id >= STATE_COUNT) {

        return false;
    }
    return record_crc(record) == record->crc32;
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

    bool valid_a = have_a && bank_is_valid(&record_a);
    bool valid_b = have_b && bank_is_valid(&record_b);

    engine_persist_record_t new_record;
    memset(&new_record, 0, sizeof(new_record));
    encode_body(&new_record.body, state, context);

    bool a_holds = valid_a && memcmp(&record_a.body, &new_record.body, sizeof(new_record.body)) == 0;
    bool b_holds = valid_b && memcmp(&record_b.body, &new_record.body, sizeof(new_record.body)) == 0;


    if (a_holds && b_holds) {
        return;
    }


    const engine_persist_record_t *newest = NULL;
    if (valid_a && valid_b) {
        newest = (record_a.sequence >= record_b.sequence) ? &record_a : &record_b;
    } else if (valid_a) {
        newest = &record_a;
    } else if (valid_b) {
        newest = &record_b;
    }


    engine_persist_bank_t target = (newest == &record_a) ? ENGINE_PERSIST_BANK_B : ENGINE_PERSIST_BANK_A;
    new_record.sequence = (newest != NULL) ? newest->sequence + 1 : 0;
    new_record.crc32 = record_crc(&new_record);


    if (!engine_persist_io_write(target, &new_record)) {
        return;
    }


    if (!((target == ENGINE_PERSIST_BANK_A) ? b_holds : a_holds)) {
        new_record.sequence += 1;
        new_record.crc32 = record_crc(&new_record);
        (void)engine_persist_io_write(other_bank(target), &new_record);
    }
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
