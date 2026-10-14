#include "engine_config_table.h"
#include "engine_guards.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ENV_ENTRIES 8
#define LINE_MAX_LEN 1024
#define NAME_MAX_LEN 63

typedef struct {
    char name[NAME_MAX_LEN + 1];
    bool is_bool;
    bool bool_value;
    double num_value;
} kv_entry_t;

typedef struct {
    kv_entry_t context[MAX_ENV_ENTRIES];
    size_t context_count;
    kv_entry_t telemetry[MAX_ENV_ENTRIES];
    size_t telemetry_count;
} test_env_t;

static bool parse_value(const char *token, bool *is_bool, bool *bool_value, double *num_value)
{
    if (strcmp(token, "true") == 0) {
        *is_bool = true;
        *bool_value = true;
        return true;
    }
    if (strcmp(token, "false") == 0) {
        *is_bool = true;
        *bool_value = false;
        return true;
    }
    char *end = NULL;
    double value = strtod(token, &end);
    if (end == token) {
        return false;
    }
    *is_bool = false;
    *num_value = value;
    return true;
}

static size_t parse_kv_list(char *str, kv_entry_t *out, size_t max_entries)
{
    size_t count = 0;
    if (str == NULL || *str == '\0') {
        return 0;
    }
    char *cursor = str;
    while (cursor != NULL && count < max_entries) {
        char *comma = strchr(cursor, ',');
        if (comma != NULL) {
            *comma = '\0';
        }
        char *eq = strchr(cursor, '=');
        if (eq != NULL) {
            *eq = '\0';
            const char *name = cursor;
            const char *value_token = eq + 1;
            bool is_bool = false;
            bool bool_value = false;
            double num_value = 0.0;
            if (parse_value(value_token, &is_bool, &bool_value, &num_value)) {
                strncpy(out[count].name, name, NAME_MAX_LEN);
                out[count].name[NAME_MAX_LEN] = '\0';
                out[count].is_bool = is_bool;
                out[count].bool_value = bool_value;
                out[count].num_value = num_value;
                count++;
            }
        }
        cursor = (comma != NULL) ? comma + 1 : NULL;
    }
    return count;
}

static bool env_get_context_bool(void *user_data, const char *name, bool *out_value)
{
    const test_env_t *env = (const test_env_t *)user_data;
    for (size_t i = 0; i < env->context_count; i++) {
        if (strcmp(env->context[i].name, name) == 0) {
            *out_value = env->context[i].is_bool ? env->context[i].bool_value
                                                  : (env->context[i].num_value != 0.0);
            return true;
        }
    }
    return false;
}

static bool env_get_telemetry_num(void *user_data, const char *name, double *out_value)
{
    const test_env_t *env = (const test_env_t *)user_data;
    for (size_t i = 0; i < env->telemetry_count; i++) {
        if (strcmp(env->telemetry[i].name, name) == 0) {
            *out_value = env->telemetry[i].is_bool ? (env->telemetry[i].bool_value ? 1.0 : 0.0)
                                                    : env->telemetry[i].num_value;
            return true;
        }
    }
    return false;
}

static bool env_get_timer_started_at(void *user_data, int32_t timer_index, double *out_started_at)
{
    const test_env_t *env = (const test_env_t *)user_data;
    if (timer_index < 0 || (uint32_t)timer_index >= g_timers_count) {
        return false;
    }
    const char *name = g_timers[timer_index].id;
    for (size_t i = 0; i < env->context_count; i++) {
        if (strcmp(env->context[i].name, name) == 0) {
            *out_started_at = env->context[i].is_bool ? (env->context[i].bool_value ? 1.0 : 0.0)
                                                        : env->context[i].num_value;
            return true;
        }
    }
    return false;
}

static const transition_t *find_transition(const char *id)
{
    for (uint32_t i = 0; i < g_transitions_count; i++) {
        if (strcmp(g_transitions[i].id, id) == 0) {
            return &g_transitions[i];
        }
    }
    return NULL;
}

static int split_fields(char *line, char *fields[4])
{
    int count = 0;
    char *cursor = line;
    while (count < 4) {
        fields[count] = cursor;
        count++;
        char *bar = strchr(cursor, '|');
        if (bar == NULL) {
            break;
        }
        *bar = '\0';
        cursor = bar + 1;
    }
    return count;
}

int main(void)
{
    char line[LINE_MAX_LEN];
    while (fgets(line, sizeof(line), stdin) != NULL) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) {
            continue;
        }

        char *fields[4];
        int nfields = split_fields(line, fields);
        if (nfields != 4) {
            printf("? ERROR malformed_line\n");
            continue;
        }

        const char *transition_id = fields[0];
        char *end = NULL;
        double now = strtod(fields[1], &end);
        if (end == fields[1]) {
            printf("%s ERROR malformed_now\n", transition_id);
            continue;
        }

        test_env_t env;
        env.context_count = parse_kv_list(fields[2], env.context, MAX_ENV_ENTRIES);
        env.telemetry_count = parse_kv_list(fields[3], env.telemetry, MAX_ENV_ENTRIES);

        const transition_t *t = find_transition(transition_id);
        if (t == NULL) {
            printf("%s ERROR unknown_transition\n", transition_id);
            continue;
        }

        guard_env_t genv = {
            .get_context_bool = env_get_context_bool,
            .get_telemetry_num = env_get_telemetry_num,
            .get_timer_started_at = env_get_timer_started_at,
            .user_data = &env,
        };

        bool result = false;
        guard_status_t status = engine_guard_evaluate(&t->guard, &genv, now, &result);
        if (status == GUARD_ERR_TELEMETRY_MISSING) {
            printf("%s ERROR telemetry_missing\n", transition_id);
            continue;
        }
        printf("%s RESULT %s\n", transition_id, result ? "true" : "false");
    }
    return 0;
}
