#ifndef ENGINE_ARBITRATION_H
#define ENGINE_ARBITRATION_H

#include <stddef.h>
#include <stdint.h>

#include "engine_config_table.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t rank;
    uint8_t class_key;
    uint8_t reset_key;
} engine_arbitration_key_t;

extern const engine_arbitration_key_t g_event_arbitration[EVENT_COUNT];

typedef struct {
    event_id_t event;
    double timestamp;
} engine_pending_event_t;

void engine_arbitrate(const engine_pending_event_t *pending, size_t n, size_t *out_order);

#ifdef __cplusplus
}
#endif

#endif
