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
    CHECK(snap.state == STATE_S_04, "pre-corruption load() returns S-04 (bank A, seq 2)");

    bool corrupted = engine_persistence_corrupt(ENGINE_PERSIST_BANK_A);
    CHECK(corrupted, "engine_persistence_corrupt(BANK_A) succeeds");

    memset(&snap, 0, sizeof(snap));
    ok = engine_persistence_load(&snap);
    CHECK(ok, "load() still succeeds after corrupting bank A (bank B still valid)");
    CHECK(snap.state == STATE_S_04, "post-corruption load() returns S-04 (from bank B)");

    bool found_flag = false;
    bool flag_value = false;
    for (uint32_t i = 0; i < snap.context.count; i++) {
        if (strcmp(snap.context.entries[i].name, "deployment_confirmed") == 0) {
            found_flag = true;
            flag_value = snap.context.entries[i].value.kind == VAL_BOOL && snap.context.entries[i].value.b;
        }
    }
    CHECK(found_flag, "post-corruption load()'s context has deployment_confirmed");
    CHECK(flag_value, "post-corruption load(): deployment_confirmed == true (bank B's value, the R-29 latch)");

    bool corrupt_blank_result = engine_persistence_corrupt((engine_persist_bank_t)99);
    CHECK(!corrupt_blank_result, "corrupt() with an invalid bank id is a documented no-op (false)");

    if (failures == 0) {
        fprintf(stderr, "\nAll persistence host smoke checks passed.\n");
    } else {
        fprintf(stderr, "\n%d check(s) FAILED.\n", failures);
    }
    return failures == 0 ? 0 : 1;
}
