#include "../../src/engine_persistence_io.h"

#include <string.h>

static engine_persist_record_t g_bank_a;
static engine_persist_record_t g_bank_b;
static bool g_initialized;

static void ensure_initialized(void)
{
    if (!g_initialized) {
        memset(&g_bank_a, 0xFF, sizeof(g_bank_a));
        memset(&g_bank_b, 0xFF, sizeof(g_bank_b));
        g_initialized = true;
    }
}

static engine_persist_record_t *bank_ptr(engine_persist_bank_t bank)
{
    switch (bank) {
    case ENGINE_PERSIST_BANK_A:
        return &g_bank_a;
    case ENGINE_PERSIST_BANK_B:
        return &g_bank_b;
    default:
        return NULL;
    }
}

bool engine_persist_io_read(engine_persist_bank_t bank, engine_persist_record_t *out)
{
    ensure_initialized();
    engine_persist_record_t *src = bank_ptr(bank);
    if (src == NULL) {
        return false;
    }
    memcpy(out, src, sizeof(*out));
    return true;
}

bool engine_persist_io_write(engine_persist_bank_t bank, const engine_persist_record_t *record)
{
    ensure_initialized();
    engine_persist_record_t *dst = bank_ptr(bank);
    if (dst == NULL) {
        return false;
    }
    memcpy(dst, record, sizeof(*dst));
    return true;
}

void persist_io_fake_erase(void)
{
    g_initialized = false;
    ensure_initialized();
}
