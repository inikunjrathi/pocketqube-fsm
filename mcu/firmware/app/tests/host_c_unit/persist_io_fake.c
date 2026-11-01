#include "../../src/engine_persistence_io.h"

#include <setjmp.h>
#include <string.h>

#include "persist_io_fake.h"

static engine_persist_record_t g_bank_a;
static engine_persist_record_t g_bank_b;
static bool g_initialized;
static persist_fault_t g_fault;
static uint32_t g_writes;

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
    g_writes++;
    if (g_fault.kind != PERSIST_FAULT_NONE && g_fault.skip_writes-- == 0) {
        persist_fault_kind_t kind = g_fault.kind;

        g_fault.kind = PERSIST_FAULT_NONE;
        if (kind == PERSIST_FAULT_WRITE_ERROR) {
            memset(dst, 0xFF, sizeof(*dst));
            return false;
        }
        if (kind == PERSIST_FAULT_TORN_PROGRAM) {
            memset(dst, 0xFF, sizeof(*dst));
            memcpy(dst, record, g_fault.offset);
        } else {

            memset(dst, 0xFF, g_fault.offset);
            dst->sequence = 0xFFFFFFFEu;
        }
        longjmp(*g_fault.power_loss, 1);
    }
    memcpy(dst, record, sizeof(*dst));
    return true;
}

void persist_io_fake_arm_fault(persist_fault_t fault)
{
    g_fault = fault;
}

uint32_t persist_io_fake_write_count(void)
{
    return g_writes;
}


void persist_io_fake_erase(void)
{
    g_initialized = false;
    ensure_initialized();
}
