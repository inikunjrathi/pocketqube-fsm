#include "engine_scheduler.h"

#include <string.h>

static void copy_truncated(char *dst, size_t dst_size, const char *src)
{
    if (dst_size == 0) {
        return;
    }
    size_t n = strlen(src);
    if (n >= dst_size) {
        n = dst_size - 1;
    }
    memcpy(dst, src, n);
    dst[n] = '\0';
}

void engine_scheduler_init(engine_scheduler_t *sched, const char *const *priority_order, uint8_t n_classes)
{
    memset(sched, 0, sizeof(*sched));

    uint8_t n = n_classes;
    if (n > ENGINE_SCHED_MAX_CLASSES) {
        n = ENGINE_SCHED_MAX_CLASSES;
    }
    for (uint8_t i = 0; i < n; i++) {
        copy_truncated(sched->priority_order[i], ENGINE_SCHED_CLASS_NAME_MAX, priority_order[i]);
    }
    sched->n_classes = n;

}

static bool lookup_rank(const engine_scheduler_t *sched, const char *data_class, int16_t *out_rank)
{
    for (uint8_t i = 0; i < sched->n_classes; i++) {
        if (strcmp(sched->priority_order[i], data_class) == 0) {
            *out_rank = (int16_t)i;
            return true;
        }
    }
    return false;
}

engine_sched_status_t engine_scheduler_insert(engine_scheduler_t *sched, const engine_sched_item_t *item)
{
    int16_t rank;

    if (!lookup_rank(sched, item->data_class, &rank)) {
        return ENGINE_SCHED_ERR_UNKNOWN_CLASS;
    }
    if (sched->count >= ENGINE_SCHED_QUEUE_CAPACITY) {
        return ENGINE_SCHED_ERR_QUEUE_FULL;
    }

    engine_sched_entry_t *entry = &sched->entries[sched->count];
    entry->rank = rank;
    entry->seq = sched->next_seq++;
    entry->item = *item;
    sched->count++;
    return ENGINE_SCHED_OK;
}

static int find_min_entry(const engine_scheduler_t *sched)
{
    if (sched->count == 0) {
        return -1;
    }
    int best = 0;
    for (uint8_t i = 1; i < sched->count; i++) {
        const engine_sched_entry_t *cand = &sched->entries[i];
        const engine_sched_entry_t *cur = &sched->entries[best];
        if (cand->rank < cur->rank || (cand->rank == cur->rank && cand->seq < cur->seq)) {
            best = i;
        }
    }
    return best;
}

static bool find_top_rank(const engine_scheduler_t *sched, int16_t *out_rank)
{
    if (sched->count == 0) {
        return false;
    }
    int16_t top = sched->entries[0].rank;
    for (uint8_t i = 1; i < sched->count; i++) {
        if (sched->entries[i].rank < top) {
            top = sched->entries[i].rank;
        }
    }
    *out_rank = top;
    return true;
}

static void remove_entry_at(engine_scheduler_t *sched, int index)
{
    sched->count--;
    if ((uint8_t)index != sched->count) {
        sched->entries[index] = sched->entries[sched->count];
    }
}

double engine_scheduler_edf_key(const engine_sched_item_t *item)
{

    if (item->has_deadline) {
        return item->deadline;
    }

    return __builtin_inf();
}

bool engine_scheduler_select_next(engine_scheduler_t *sched, engine_sched_key_fn key, engine_sched_item_t *out)
{
    if (sched->count == 0) {
        return false;
    }

    if (key == NULL) {

        int idx = find_min_entry(sched);
        *out = sched->entries[idx].item;
        remove_entry_at(sched, idx);
        return true;
    }

    int16_t top_rank;
    find_top_rank(sched, &top_rank);

    int chosen = -1;
    double chosen_key_value = 0.0;
    for (uint8_t i = 0; i < sched->count; i++) {
        const engine_sched_entry_t *e = &sched->entries[i];
        if (e->rank != top_rank) {
            continue;
        }
        double kv = key(&e->item);
        if (chosen == -1 || kv < chosen_key_value ||
            (kv == chosen_key_value && e->seq < sched->entries[chosen].seq)) {
            chosen = i;
            chosen_key_value = kv;
        }
    }

    *out = sched->entries[chosen].item;
    remove_entry_at(sched, chosen);
    return true;
}

bool engine_scheduler_peek_next_class(const engine_scheduler_t *sched, char *out_class, size_t out_size)
{
    int idx = find_min_entry(sched);
    if (idx < 0) {
        return false;
    }
    copy_truncated(out_class, out_size, sched->entries[idx].item.data_class);
    return true;
}

uint8_t engine_scheduler_candidate_classes(
    const engine_scheduler_t *sched,
    char out_classes[][ENGINE_SCHED_CLASS_NAME_MAX],
    uint8_t max_out)
{

    uint8_t order[ENGINE_SCHED_QUEUE_CAPACITY];
    uint8_t n = sched->count;
    for (uint8_t i = 0; i < n; i++) {
        order[i] = i;
    }
    for (uint8_t i = 0; i < n; i++) {
        uint8_t best = i;
        for (uint8_t j = i + 1; j < n; j++) {
            const engine_sched_entry_t *a = &sched->entries[order[j]];
            const engine_sched_entry_t *b = &sched->entries[order[best]];
            if (a->rank < b->rank || (a->rank == b->rank && a->seq < b->seq)) {
                best = j;
            }
        }
        uint8_t tmp = order[i];
        order[i] = order[best];
        order[best] = tmp;
    }

    uint8_t written = 0;
    uint8_t limit = n < max_out ? n : max_out;
    for (uint8_t i = 0; i < limit; i++) {
        copy_truncated(out_classes[written], ENGINE_SCHED_CLASS_NAME_MAX, sched->entries[order[i]].item.data_class);
        written++;
    }
    return written;
}

bool engine_scheduler_is_empty(const engine_scheduler_t *sched)
{
    return sched->count == 0;
}

uint8_t engine_scheduler_all_items(const engine_scheduler_t *sched, engine_sched_item_t out_items[], uint8_t max_out)
{

    uint8_t n = sched->count < max_out ? sched->count : max_out;
    for (uint8_t i = 0; i < n; i++) {
        out_items[i] = sched->entries[i].item;
    }
    return n;
}
