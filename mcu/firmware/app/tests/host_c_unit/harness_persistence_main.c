#include <stdio.h>
#include <string.h>

#include "../../src/engine_persistence.h"

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

void persist_io_fake_erase(void);

static void set_bool_ctx(engine_context_t *ctx, const char *name, bool value)
{
    engine_context_entry_t *e = &ctx->entries[ctx->count++];
    e->name = name;
    e->value.kind = VAL_BOOL;
    e->value.b = value;
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
    engine_persistence_save(STATE_S_04, &ctx);

    engine_persisted_snapshot_t snap;
    bool ok = engine_persistence_load(&snap);
    CHECK(ok, "load() succeeds before corruption");
    CHECK(snap.state == STATE_S_04, "pre-corruption load() returns S-04 (bank B, seq 3)");

    bool corrupted = engine_persistence_corrupt(ENGINE_PERSIST_BANK_B);
    CHECK(corrupted, "engine_persistence_corrupt(BANK_B) succeeds");

    memset(&snap, 0, sizeof(snap));
    ok = engine_persistence_load(&snap);
    CHECK(ok, "load() still succeeds after corrupting bank B (bank A still valid)");
    CHECK(snap.state == STATE_S_04, "post-corruption load() returns S-04 (from bank A)");

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

    if (failures == 0) {
        fprintf(stderr, "\nAll persistence host smoke checks passed.\n");
    } else {
        fprintf(stderr, "\n%d check(s) FAILED.\n", failures);
    }
    return failures == 0 ? 0 : 1;
}
