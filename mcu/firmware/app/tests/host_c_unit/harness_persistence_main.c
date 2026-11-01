#include <stdio.h>
#include <string.h>

#include <setjmp.h>

#include "../../src/engine_persistence.h"
#include "../../src/engine_persistence_io.h"
#include "persist_io_fake.h"

static void run_power_cut_sweep(void);
static void run_write_count_checks(void);


void engine_context_init(engine_context_t *ctx)
{
    ctx->count = 0;
}

static int failures;

#define CHECK(cond, msg)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                      \
            fprintf(stderr, "FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__); \
            failures++;                                                     \
        } else {                                                            \
            fprintf(stderr, "  ok: %s\n", (msg));                           \
        }                                                                   \
    } while (0)


static void set_bool_ctx(engine_context_t *ctx, const char *name, bool value)
{
    engine_context_entry_t *e = &ctx->entries[ctx->count++];
    e->name = name;
    e->value.kind = VAL_BOOL;
    e->value.b = value;
}


#define HISTORY_LEN 4

typedef struct {
    state_id_t state;
    bool latch;
} history_step_t;

static const history_step_t g_history[HISTORY_LEN] = {
    {STATE_S_03, false},
    {STATE_S_04, true},
    {STATE_S_05, true},
    {STATE_S_06, true},
};

static void save_step(const history_step_t *step)
{
    engine_context_t ctx;

    memset(&ctx, 0, sizeof(ctx));
    set_bool_ctx(&ctx, "deployment_confirmed", step->latch);
    engine_persistence_save(step->state, &ctx);
}


static void save_step_with_fault(const history_step_t *step, persist_fault_t fault)
{
    jmp_buf power_loss;

    fault.power_loss = &power_loss;
    persist_io_fake_arm_fault(fault);
    if (setjmp(power_loss) == 0) {
        save_step(step);
    }
    fault.kind = PERSIST_FAULT_NONE;
    persist_io_fake_arm_fault(fault);
}

static bool loaded_latch(const engine_persisted_snapshot_t *snap)
{
    for (uint32_t i = 0; i < snap->context.count; i++) {
        if (strcmp(snap->context.entries[i].name, "deployment_confirmed") == 0) {
            return snap->context.entries[i].value.kind == VAL_BOOL && snap->context.entries[i].value.b;
        }
    }
    return false;
}


static bool load_is_acceptable(int k)
{
    engine_persisted_snapshot_t snap;

    if (!engine_persistence_load(&snap)) {
        return k == 0;
    }
    bool is_new = snap.state == g_history[k].state && loaded_latch(&snap) == g_history[k].latch;
    bool is_old = k > 0 && snap.state == g_history[k - 1].state &&
                  loaded_latch(&snap) == g_history[k - 1].latch;
    return is_new || is_old;
}

static void run_write_count_checks(void)
{
    persist_io_fake_erase();
    uint32_t before = persist_io_fake_write_count();
    save_step(&g_history[0]);
    CHECK(persist_io_fake_write_count() - before == 2, "a change writes both banks");

    before = persist_io_fake_write_count();
    save_step(&g_history[0]);
    save_step(&g_history[0]);
    CHECK(persist_io_fake_write_count() == before, "an unchanged save writes nothing");

    engine_persistence_corrupt(ENGINE_PERSIST_BANK_A);
    before = persist_io_fake_write_count();
    save_step(&g_history[0]);
    CHECK(persist_io_fake_write_count() - before == 1, "an unchanged save repairs a damaged bank");
    before = persist_io_fake_write_count();
    save_step(&g_history[0]);
    CHECK(persist_io_fake_write_count() == before, "repaired banks need no further write");

    persist_io_fake_erase();
    save_step(&g_history[0]);
    persist_fault_t error = {PERSIST_FAULT_WRITE_ERROR, 0, 0, NULL};
    save_step_with_fault(&g_history[1], error);
    engine_persisted_snapshot_t snap;
    CHECK(engine_persistence_load(&snap) && snap.state == g_history[0].state,
          "a failed first write leaves the good copy untouched");
}

static void run_power_cut_sweep(void)
{
    static const persist_fault_kind_t kinds[2] = {PERSIST_FAULT_TORN_PROGRAM, PERSIST_FAULT_TORN_ERASE};
    uint32_t cuts = 0;
    uint32_t bad = 0;

    for (int k = 0; k < HISTORY_LEN; k++) {
        for (uint32_t skip = 0; skip < 2; skip++) {
            for (int kind = 0; kind < 2; kind++) {
                for (size_t offset = 0; offset <= sizeof(engine_persist_record_t); offset++) {
                    persist_io_fake_erase();
                    for (int i = 0; i < k; i++) {
                        save_step(&g_history[i]);
                    }
                    persist_fault_t fault = {kinds[kind], skip, offset, NULL};
                    save_step_with_fault(&g_history[k], fault);
                    cuts++;
                    bool ok = load_is_acceptable(k);


                    persist_fault_t second = {PERSIST_FAULT_TORN_PROGRAM, 0, offset, NULL};
                    save_step_with_fault(&g_history[k], second);
                    ok = ok && load_is_acceptable(k);


                    save_step(&g_history[k]);
                    engine_persist_record_t bank_a;
                    engine_persist_record_t bank_b;
                    engine_persist_io_read(ENGINE_PERSIST_BANK_A, &bank_a);
                    engine_persist_io_read(ENGINE_PERSIST_BANK_B, &bank_b);

                    ok = ok && bank_a.sequence < 64u && bank_b.sequence < 64u;

                    engine_persisted_snapshot_t snap;
                    engine_persistence_corrupt(ENGINE_PERSIST_BANK_A);
                    ok = ok && engine_persistence_load(&snap) && snap.state == g_history[k].state &&
                         loaded_latch(&snap) == g_history[k].latch;
                    bad += ok ? 0u : 1u;
                }
            }
        }
    }
    fprintf(stderr, "  power cuts injected: %u, unacceptable outcomes: %u\n", cuts, bad);
    CHECK(cuts > 0 && bad == 0, "every power cut, then a second one, loses nothing committed");
}

int main(void)
{
    engine_context_t ctx;


    memset(&ctx, 0, sizeof(ctx));
    set_bool_ctx(&ctx, "deployment_confirmed", false);
    engine_persistence_save(STATE_S_03, &ctx);


    memset(&ctx, 0, sizeof(ctx));
    set_bool_ctx(&ctx, "deployment_confirmed", true);
    engine_persistence_save(STATE_S_04, &ctx);


    memset(&ctx, 0, sizeof(ctx));
    set_bool_ctx(&ctx, "deployment_confirmed", true);
    engine_persistence_save(STATE_S_05, &ctx);


    engine_persisted_snapshot_t snap;
    bool ok = engine_persistence_load(&snap);
    CHECK(ok, "load() succeeds before corruption");
    CHECK(snap.state == STATE_S_05, "pre-corruption load() returns S-05 (bank B, seq 5)");


    bool corrupted = engine_persistence_corrupt(ENGINE_PERSIST_BANK_B);
    CHECK(corrupted, "engine_persistence_corrupt(BANK_B) succeeds");


    memset(&snap, 0, sizeof(snap));
    ok = engine_persistence_load(&snap);
    CHECK(ok, "load() still succeeds after corrupting bank B (bank A still valid)");
    CHECK(snap.state == STATE_S_05, "post-corruption load() returns S-05 (from bank A)");

    bool found_flag = false;
    bool flag_value = false;
    for (uint32_t i = 0; i < snap.context.count; i++) {
        if (strcmp(snap.context.entries[i].name, "deployment_confirmed") == 0) {
            found_flag = true;
            flag_value = snap.context.entries[i].value.kind == VAL_BOOL && snap.context.entries[i].value.b;
        }
    }
    CHECK(found_flag, "post-corruption load()'s context has deployment_confirmed");
    CHECK(flag_value, "post-corruption load(): deployment_confirmed == true (bank A's value, the R-29 latch)");


    const engine_persist_bank_t victims[2] = {ENGINE_PERSIST_BANK_A, ENGINE_PERSIST_BANK_B};
    for (int v = 0; v < 2; v++) {
        persist_io_fake_erase();
        memset(&ctx, 0, sizeof(ctx));
        set_bool_ctx(&ctx, "deployment_confirmed", false);
        engine_persistence_save(STATE_S_03, &ctx);
        memset(&ctx, 0, sizeof(ctx));
        set_bool_ctx(&ctx, "deployment_confirmed", true);
        engine_persistence_save(STATE_S_04, &ctx);
        engine_persistence_corrupt(victims[v]);

        memset(&snap, 0, sizeof(snap));
        ok = engine_persistence_load(&snap);
        bool latched = false;
        for (uint32_t i = 0; ok && i < snap.context.count; i++) {
            if (strcmp(snap.context.entries[i].name, "deployment_confirmed") == 0) {
                latched = snap.context.entries[i].value.kind == VAL_BOOL && snap.context.entries[i].value.b;
            }
        }
        CHECK(ok && snap.state == STATE_S_04 && latched,
              v == 0 ? "first latched save, bank A corrupted: latch still loads"
                     : "first latched save, bank B corrupted: latch still loads");
    }


    bool corrupt_blank_result = engine_persistence_corrupt((engine_persist_bank_t)99);
    CHECK(!corrupt_blank_result, "corrupt() with an invalid bank id is a documented no-op (false)");

    run_write_count_checks();
    run_power_cut_sweep();

    if (failures == 0) {
        fprintf(stderr, "\nAll persistence host smoke checks passed.\n");
    } else {
        fprintf(stderr, "\n%d check(s) FAILED.\n", failures);
    }
    return failures == 0 ? 0 : 1;
}
