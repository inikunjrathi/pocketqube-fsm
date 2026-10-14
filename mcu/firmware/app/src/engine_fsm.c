#include "engine_fsm.h"

#include <string.h>

#include "engine_auth.h"

void engine_context_init(engine_context_t *ctx)
{
    ctx->count = 0;
}

bool engine_context_get(const engine_context_t *ctx, const char *name, val_t *out_value)
{
    for (uint32_t i = 0; i < ctx->count; i++) {
        if (strcmp(ctx->entries[i].name, name) == 0) {
            *out_value = ctx->entries[i].value;
            return true;
        }
    }
    return false;
}

bool engine_context_set(engine_context_t *ctx, const char *name, val_t value)
{
    for (uint32_t i = 0; i < ctx->count; i++) {
        if (strcmp(ctx->entries[i].name, name) == 0) {
            ctx->entries[i].value = value;
            return true;
        }
    }
    if (ctx->count >= ENGINE_CONTEXT_MAX_ENTRIES) {
        return false;
    }
    ctx->entries[ctx->count].name = name;
    ctx->entries[ctx->count].value = value;
    ctx->count++;
    return true;
}

void engine_context_copy(engine_context_t *dst, const engine_context_t *src)
{
    *dst = *src;
}

void engine_telemetry_init(engine_telemetry_t *tlm)
{
    tlm->count = 0;
}

bool engine_telemetry_set(engine_telemetry_t *tlm, const char *name, double value)
{
    for (uint32_t i = 0; i < tlm->count; i++) {
        if (strcmp(tlm->entries[i].name, name) == 0) {
            tlm->entries[i].value = value;
            return true;
        }
    }
    if (tlm->count >= ENGINE_TELEMETRY_MAX_ENTRIES) {
        return false;
    }
    tlm->entries[tlm->count].name = name;
    tlm->entries[tlm->count].value = value;
    tlm->count++;
    return true;
}

bool engine_telemetry_get(const engine_telemetry_t *tlm, const char *name, double *out_value)
{
    for (uint32_t i = 0; i < tlm->count; i++) {
        if (strcmp(tlm->entries[i].name, name) == 0) {
            *out_value = tlm->entries[i].value;
            return true;
        }
    }
    return false;
}

bool engine_lookup_state(const char *id, state_id_t *out_state)
{
    for (uint32_t i = 0; i < STATE_COUNT; i++) {
        if (strcmp(g_states[i].id, id) == 0) {
            *out_state = (state_id_t)i;
            return true;
        }
    }
    return false;
}

bool engine_lookup_event(const char *id, event_id_t *out_event)
{
    for (uint32_t i = 0; i < EVENT_COUNT; i++) {
        if (strcmp(g_events[i].id, id) == 0) {
            *out_event = (event_id_t)i;
            return true;
        }
    }
    return false;
}

typedef struct {
    const engine_context_t *context;
    const engine_telemetry_t *telemetry;
} guard_bridge_t;

static bool bridge_get_context_bool(void *user_data, const char *name, bool *out_value)
{
    const guard_bridge_t *bridge = (const guard_bridge_t *)user_data;
    val_t value;
    if (!engine_context_get(bridge->context, name, &value)) {
        return false;
    }
    if (value.kind != VAL_BOOL) {

        return false;
    }
    *out_value = value.b;
    return true;
}

static bool bridge_get_telemetry_num(void *user_data, const char *name, double *out_value)
{
    const guard_bridge_t *bridge = (const guard_bridge_t *)user_data;
    return engine_telemetry_get(bridge->telemetry, name, out_value);
}

static bool bridge_get_timer_started_at(void *user_data, int32_t timer_index, double *out_started_at)
{
    const guard_bridge_t *bridge = (const guard_bridge_t *)user_data;
    if (timer_index < 0 || (uint32_t)timer_index >= g_timers_count) {
        return false;
    }

    val_t value;
    if (!engine_context_get(bridge->context, g_timers[timer_index].id, &value)) {
        return false;
    }
    if (value.kind != VAL_NUM) {
        return false;
    }
    *out_started_at = value.num;
    return true;
}

static bool transition_applies_from(const transition_t *t, state_id_t state)
{

    return (t->from_mask & (1u << (uint32_t)state)) != 0;
}

static const char *missing_telemetry_field_name(const guard_expr_t *guard)
{
    if (guard->lhs.kind == OPERAND_TELEMETRY) {
        return guard->lhs.name;
    }
    if (guard->rhs.kind == OPERAND_TELEMETRY) {
        return guard->rhs.name;
    }
    return "(unknown)";
}

static bool select_transition(state_id_t state,
                               event_id_t event,
                               const engine_context_t *context,
                               const engine_telemetry_t *telemetry,
                               double now,
                               const transition_t **out_chosen,
                               uint32_t *out_chosen_index,
                               engine_step_status_t *out_status,
                               const char **out_error_field)
{
    guard_bridge_t bridge = { .context = context, .telemetry = telemetry };
    guard_env_t env = {
        .get_context_bool = bridge_get_context_bool,
        .get_telemetry_num = bridge_get_telemetry_num,
        .get_timer_started_at = bridge_get_timer_started_at,
        .user_data = &bridge,
    };

    for (uint32_t i = 0; i < g_transitions_count; i++) {
        const transition_t *t = &g_transitions[i];
        if (t->event != event) {
            continue;
        }
        if (!transition_applies_from(t, state)) {
            continue;
        }
        if (!t->guard.has_guard) {
            *out_chosen = t;
            *out_chosen_index = i;
            *out_status = ENGINE_STEP_OK;
            return true;
        }
        bool result = false;
        guard_status_t status = engine_guard_evaluate(&t->guard, &env, now, &result);
        if (status != GUARD_OK) {
            *out_status = ENGINE_STEP_ERR_GUARD_TELEMETRY_MISSING;
            *out_error_field = missing_telemetry_field_name(&t->guard);
            *out_chosen = NULL;
            return false;
        }
        if (result) {
            *out_chosen = t;
            *out_chosen_index = i;
            *out_status = ENGINE_STEP_OK;
            return true;
        }
    }

    *out_chosen = NULL;
    *out_status = ENGINE_STEP_OK;
    return false;
}

static void resolve_target(const transition_t *chosen,
                            state_id_t state,
                            const engine_context_t *context,
                            const engine_persisted_snapshot_t *persisted,
                            state_id_t *out_state,
                            engine_context_t *out_base_context)
{
    switch (chosen->target_kind) {
    case TARGET_SELF:
        *out_state = state;
        engine_context_copy(out_base_context, context);
        return;
    case TARGET_RELOAD_PERSISTENCE:
        if (persisted != NULL) {
            *out_state = persisted->state;
            engine_context_copy(out_base_context, &persisted->context);
        } else {
            *out_state = ENGINE_CONFIG_INITIAL_STATE;
            engine_context_init(out_base_context);
        }
        return;
    case TARGET_STATE:
    default:
        *out_state = chosen->to_state;
        engine_context_copy(out_base_context, context);
        return;
    }
}

static bool is_latch_name(const char *name)
{
    for (uint32_t i = 0; i < g_latches_count; i++) {
        if (strcmp(g_latches[i].name, name) == 0) {
            return true;
        }
    }
    return false;
}

static val_t literal_operand_to_val(const guard_operand_t *op)
{
    switch (op->kind) {
    case OPERAND_LITERAL_BOOL:
        return (val_t){ .kind = VAL_BOOL, .b = op->bool_value };
    case OPERAND_LITERAL_NUM:
        return (val_t){ .kind = VAL_NUM, .num = op->num_value };
    case OPERAND_LITERAL_STR:
        return (val_t){ .kind = VAL_STR, .str = op->str_value };
    default:

        return (val_t){ .kind = VAL_NONE };
    }
}

static void apply_actions(engine_context_t *ctx, const action_t *actions, uint8_t actions_count, double now)
{
    for (uint8_t i = 0; i < actions_count; i++) {
        const action_t *a = &actions[i];
        switch (a->kind) {
        case ACTION_SET_CONTEXT: {
            val_t value = literal_operand_to_val(&a->value);
            if (is_latch_name(a->context_name)) {
                val_t current;
                bool found = engine_context_get(ctx, a->context_name, &current);
                if (found && current.kind == VAL_BOOL && current.b == true &&
                    value.kind == VAL_BOOL && value.b == false) {

                    continue;
                }
            }
            (void)engine_context_set(ctx, a->context_name, value);
            break;
        }
        case ACTION_START_TIMER:
            (void)engine_context_set(ctx, a->timer_name, (val_t){ .kind = VAL_NUM, .num = now });
            break;
        case ACTION_OPAQUE:
        default:

            break;
        }
    }
}

static void apply_latch_sets(engine_context_t *ctx, uint32_t chosen_transition_index)
{
    for (uint32_t i = 0; i < g_latches_count; i++) {
        const latch_def_t *latch = &g_latches[i];
        for (uint32_t j = 0; j < latch->set_by_count; j++) {
            if (latch->set_by[j] == chosen_transition_index) {
                (void)engine_context_set(ctx, latch->name, (val_t){ .kind = VAL_BOOL, .b = true });
                break;
            }
        }
    }
}

engine_step_status_t engine_fsm_step(state_id_t state,
                                      event_id_t event,
                                      const engine_context_t *context,
                                      const engine_telemetry_t *telemetry,
                                      double now,
                                      const engine_persisted_snapshot_t *persisted,
                                      const char *ground_command_signature,
                                      engine_step_result_t *out_result,
                                      engine_context_t *out_context,
                                      const char **out_error_field)
{
    *out_error_field = NULL;

    if (ENGINE_GROUND_AUTH_ENABLED && strcmp(g_events[event].source, "ground") == 0) {
        if (!engine_auth_verify_command(g_events[event].id, now, ground_command_signature)) {
            out_result->new_state = state;
            out_result->transition_id = NULL;
            out_result->actions = NULL;
            out_result->actions_count = 0;
            out_result->legal = false;
            engine_context_copy(out_context, context);
            return ENGINE_STEP_OK;
        }
    }

    const transition_t *chosen = NULL;
    uint32_t chosen_index = 0;
    engine_step_status_t status = ENGINE_STEP_OK;
    bool matched = select_transition(state, event, context, telemetry, now,
                                      &chosen, &chosen_index, &status, out_error_field);
    if (status != ENGINE_STEP_OK) {
        return status;
    }

    if (!matched) {
        out_result->new_state = state;
        out_result->transition_id = NULL;
        out_result->actions = NULL;
        out_result->actions_count = 0;
        out_result->legal = false;
        engine_context_copy(out_context, context);
        return ENGINE_STEP_OK;
    }

    state_id_t new_state;
    engine_context_t base_context;
    resolve_target(chosen, state, context, persisted, &new_state, &base_context);

    engine_context_t new_context;
    engine_context_copy(&new_context, &base_context);
    apply_actions(&new_context, chosen->actions, chosen->actions_count, now);
    apply_latch_sets(&new_context, chosen_index);

    engine_context_copy(out_context, &new_context);
    out_result->new_state = new_state;
    out_result->transition_id = chosen->id;
    out_result->actions = chosen->actions;
    out_result->actions_count = chosen->actions_count;
    out_result->legal = true;
    return ENGINE_STEP_OK;
}
