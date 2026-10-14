#ifndef ENGINE_GUARDS_H
#define ENGINE_GUARDS_H

#include <stdbool.h>
#include <stdint.h>

#include "engine_config_table.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    VAL_NONE = 0,
    VAL_BOOL,
    VAL_NUM,
    VAL_STR,
} val_kind_t;

typedef struct {
    val_kind_t kind;
    bool b;
    double num;
    const char *str;
} val_t;

typedef enum {
    GUARD_OK = 0,
    GUARD_ERR_TELEMETRY_MISSING,
} guard_status_t;

typedef struct {

    bool (*get_context_bool)(void *user_data, const char *name, bool *out_value);

    bool (*get_telemetry_num)(void *user_data, const char *name, double *out_value);

    bool (*get_timer_started_at)(void *user_data, int32_t timer_index, double *out_started_at);

    void *user_data;
} guard_env_t;

guard_status_t engine_guard_resolve_operand(const guard_operand_t *operand,
                                             const guard_env_t *env,
                                             double now,
                                             val_t *out_value);

guard_status_t engine_guard_evaluate(const guard_expr_t *guard,
                                      const guard_env_t *env,
                                      double now,
                                      bool *out_result);

#ifdef __cplusplus
}
#endif

#endif
