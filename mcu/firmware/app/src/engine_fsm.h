#ifndef ENGINE_FSM_H
#define ENGINE_FSM_H

#include <stdbool.h>
#include <stdint.h>

#include "engine_config_table.h"
#include "engine_guards.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ENGINE_CONTEXT_MAX_ENTRIES 8

#define ENGINE_TELEMETRY_MAX_ENTRIES 6

typedef struct {
    const char *name;
    val_t value;
} engine_context_entry_t;

typedef struct {
    engine_context_entry_t entries[ENGINE_CONTEXT_MAX_ENTRIES];
    uint32_t count;
} engine_context_t;

typedef struct {
    const char *name;
    double value;
} engine_telemetry_entry_t;

typedef struct {
    engine_telemetry_entry_t entries[ENGINE_TELEMETRY_MAX_ENTRIES];
    uint32_t count;
} engine_telemetry_t;

void engine_context_init(engine_context_t *ctx);

bool engine_context_set(engine_context_t *ctx, const char *name, val_t value);

bool engine_context_get(const engine_context_t *ctx, const char *name, val_t *out_value);

void engine_context_copy(engine_context_t *dst, const engine_context_t *src);

void engine_telemetry_init(engine_telemetry_t *tlm);

bool engine_telemetry_set(engine_telemetry_t *tlm, const char *name, double value);

bool engine_telemetry_get(const engine_telemetry_t *tlm, const char *name, double *out_value);

bool engine_lookup_state(const char *id, state_id_t *out_state);
bool engine_lookup_event(const char *id, event_id_t *out_event);

typedef struct {
    state_id_t new_state;
    const char *transition_id;
    const action_t *actions;
    uint8_t actions_count;
    bool legal;
} engine_step_result_t;

typedef enum {
    ENGINE_STEP_OK = 0,

    ENGINE_STEP_ERR_GUARD_TELEMETRY_MISSING,
} engine_step_status_t;

typedef struct {
    state_id_t state;
    engine_context_t context;
} engine_persisted_snapshot_t;

#ifndef ENGINE_GROUND_AUTH_ENABLED
#define ENGINE_GROUND_AUTH_ENABLED 0
#endif

engine_step_status_t engine_fsm_step(state_id_t state,
                                      event_id_t event,
                                      const engine_context_t *context,
                                      const engine_telemetry_t *telemetry,
                                      double now,
                                      const engine_persisted_snapshot_t *persisted,
                                      const char *ground_command_signature,
                                      engine_step_result_t *out_result,
                                      engine_context_t *out_context,
                                      const char **out_error_field);

#ifdef __cplusplus
}
#endif

#endif
