#include "engine_guards.h"

#include <string.h>

guard_status_t engine_guard_resolve_operand(const guard_operand_t *operand,
                                             const guard_env_t *env,
                                             double now,
                                             val_t *out_value)
{
    switch (operand->kind) {
    case OPERAND_NONE:

        *out_value = (val_t){ .kind = VAL_NONE };
        return GUARD_OK;

    case OPERAND_LITERAL_NUM:
        *out_value = (val_t){ .kind = VAL_NUM, .num = operand->num_value };
        return GUARD_OK;

    case OPERAND_LITERAL_BOOL:
        *out_value = (val_t){ .kind = VAL_BOOL, .b = operand->bool_value };
        return GUARD_OK;

    case OPERAND_LITERAL_STR:
        *out_value = (val_t){ .kind = VAL_STR, .str = operand->str_value };
        return GUARD_OK;

    case OPERAND_CONTEXT: {

        bool value = false;
        if (env->get_context_bool != NULL) {
            (void)env->get_context_bool(env->user_data, operand->name, &value);
        }
        *out_value = (val_t){ .kind = VAL_BOOL, .b = value };
        return GUARD_OK;
    }

    case OPERAND_TELEMETRY: {
        double value = 0.0;
        bool found = env->get_telemetry_num != NULL &&
                     env->get_telemetry_num(env->user_data, operand->name, &value);
        if (!found) {

            *out_value = (val_t){ .kind = VAL_NONE };
            return GUARD_ERR_TELEMETRY_MISSING;
        }
        *out_value = (val_t){ .kind = VAL_NUM, .num = value };
        return GUARD_OK;
    }

    case OPERAND_PARAM:

        if (operand->param_index < 0 ||
            (uint32_t)operand->param_index >= g_parameters_count) {
            *out_value = (val_t){ .kind = VAL_NONE };
            return GUARD_OK;
        }
        *out_value = (val_t){ .kind = VAL_NUM, .num = g_parameters[operand->param_index].value };
        return GUARD_OK;

    case OPERAND_ELAPSED:

        if (operand->timer_index < 0 ||
            (uint32_t)operand->timer_index >= g_timers_count) {
            *out_value = (val_t){ .kind = VAL_NONE };
            return GUARD_OK;
        } else {
            double started_at = 0.0;
            bool armed = env->get_timer_started_at != NULL &&
                         env->get_timer_started_at(env->user_data, operand->timer_index, &started_at);
            if (!armed) {

                *out_value = (val_t){ .kind = VAL_NONE };
                return GUARD_OK;
            }
            *out_value = (val_t){ .kind = VAL_NUM, .num = now - started_at };
            return GUARD_OK;
        }
    }

    *out_value = (val_t){ .kind = VAL_NONE };
    return GUARD_OK;
}

static bool as_num(val_t v, double *out)
{
    if (v.kind == VAL_NUM) {
        *out = v.num;
        return true;
    }
    if (v.kind == VAL_BOOL) {
        *out = v.b ? 1.0 : 0.0;
        return true;
    }
    return false;
}

static bool values_equal(val_t a, val_t b)
{
    if (a.kind == VAL_STR || b.kind == VAL_STR) {

        if (a.kind != VAL_STR || b.kind != VAL_STR) {
            return false;
        }
        return strcmp(a.str, b.str) == 0;
    }
    double an, bn;
    if (as_num(a, &an) && as_num(b, &bn)) {
        return an == bn;
    }

    return false;
}

static bool compare_ordered(guard_op_t op, val_t lhs, val_t rhs)
{
    if (lhs.kind == VAL_STR && rhs.kind == VAL_STR) {
        int c = strcmp(lhs.str, rhs.str);
        switch (op) {
        case GUARD_OP_LT: return c < 0;
        case GUARD_OP_LE: return c <= 0;
        case GUARD_OP_GT: return c > 0;
        case GUARD_OP_GE: return c >= 0;
        default: return false;
        }
    }

    double an, bn;
    if (!as_num(lhs, &an) || !as_num(rhs, &bn)) {
        return false;
    }
    switch (op) {
    case GUARD_OP_LT: return an < bn;
    case GUARD_OP_LE: return an <= bn;
    case GUARD_OP_GT: return an > bn;
    case GUARD_OP_GE: return an >= bn;
    default: return false;
    }
}

static bool compare_values(guard_op_t op, val_t lhs, val_t rhs)
{
    switch (op) {
    case GUARD_OP_EQ: return values_equal(lhs, rhs);
    case GUARD_OP_NE: return !values_equal(lhs, rhs);
    case GUARD_OP_GE:
    case GUARD_OP_LE:
    case GUARD_OP_LT:
    case GUARD_OP_GT:
        return compare_ordered(op, lhs, rhs);
    }
    return false;
}

guard_status_t engine_guard_evaluate(const guard_expr_t *guard,
                                      const guard_env_t *env,
                                      double now,
                                      bool *out_result)
{
    if (!guard->has_guard) {

        *out_result = true;
        return GUARD_OK;
    }

    val_t lhs;
    guard_status_t status = engine_guard_resolve_operand(&guard->lhs, env, now, &lhs);
    if (status != GUARD_OK) {
        *out_result = false;
        return status;
    }

    val_t rhs;
    status = engine_guard_resolve_operand(&guard->rhs, env, now, &rhs);
    if (status != GUARD_OK) {
        *out_result = false;
        return status;
    }

    if (lhs.kind == VAL_NONE || rhs.kind == VAL_NONE) {

        *out_result = false;
        return GUARD_OK;
    }

    *out_result = compare_values(guard->op, lhs, rhs);
    return GUARD_OK;
}
