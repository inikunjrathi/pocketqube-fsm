#ifndef ENGINE_PERSISTENCE_H
#define ENGINE_PERSISTENCE_H

#include <stdbool.h>
#include <stdint.h>

#include "engine_fsm.h"

#ifdef __cplusplus
extern "C" {
#endif

bool engine_persistence_load(engine_persisted_snapshot_t *out);

void engine_persistence_save(state_id_t state, const engine_context_t *context);

typedef enum {
    ENGINE_PERSIST_BANK_A = 0,
    ENGINE_PERSIST_BANK_B = 1,
} engine_persist_bank_t;

#ifndef ENGINE_PERSIST_TESTHOOKS_ENABLED
#define ENGINE_PERSIST_TESTHOOKS_ENABLED 0
#endif

bool engine_persistence_corrupt(engine_persist_bank_t bank);

#ifdef __cplusplus
}
#endif

#endif
