#include "engine_arbitration.h"

#include <string.h>

static int compare(const engine_pending_event_t *a, const engine_pending_event_t *b)
{
    const engine_arbitration_key_t *ka = &g_event_arbitration[a->event];
    const engine_arbitration_key_t *kb = &g_event_arbitration[b->event];

    if (ka->rank != kb->rank) {
        return ka->rank < kb->rank ? -1 : 1;
    }
    if (ka->class_key != kb->class_key) {
        return ka->class_key < kb->class_key ? -1 : 1;
    }
    if (a->timestamp != b->timestamp) {
        return a->timestamp < b->timestamp ? -1 : 1;
    }
    if (ka->reset_key != kb->reset_key) {
        return ka->reset_key < kb->reset_key ? -1 : 1;
    }
    return strcmp(g_events[a->event].id, g_events[b->event].id);
}

void engine_arbitrate(const engine_pending_event_t *pending, size_t n, size_t *out_order)
{
    for (size_t i = 0; i < n; i++) {
        size_t j = i;

        while (j > 0 && compare(&pending[i], &pending[out_order[j - 1]]) < 0) {
            out_order[j] = out_order[j - 1];
            j--;
        }
        out_order[j] = i;
    }
}
