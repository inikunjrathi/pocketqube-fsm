#ifndef ENGINE_SCHEDULER_H
#define ENGINE_SCHEDULER_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ENGINE_SCHED_QUEUE_CAPACITY 16

#define ENGINE_SCHED_MAX_CLASSES 8

#define ENGINE_SCHED_CLASS_NAME_MAX 24

#define ENGINE_SCHED_ITEM_ID_MAX 32

typedef struct {
    char id[ENGINE_SCHED_ITEM_ID_MAX];
    char data_class[ENGINE_SCHED_CLASS_NAME_MAX];
    uint32_t size_bytes;
    bool has_deadline;
    double deadline;
} engine_sched_item_t;

typedef struct {
    int16_t rank;
    uint32_t seq;
    engine_sched_item_t item;
} engine_sched_entry_t;

typedef struct {
    char priority_order[ENGINE_SCHED_MAX_CLASSES][ENGINE_SCHED_CLASS_NAME_MAX];
    uint8_t n_classes;
    engine_sched_entry_t entries[ENGINE_SCHED_QUEUE_CAPACITY];
    uint8_t count;
    uint32_t next_seq;
} engine_scheduler_t;

typedef enum {
    ENGINE_SCHED_OK = 0,

    ENGINE_SCHED_ERR_UNKNOWN_CLASS,

    ENGINE_SCHED_ERR_QUEUE_FULL,
} engine_sched_status_t;

void engine_scheduler_init(engine_scheduler_t *sched, const char *const *priority_order, uint8_t n_classes);

engine_sched_status_t engine_scheduler_insert(engine_scheduler_t *sched, const engine_sched_item_t *item);

typedef double (*engine_sched_key_fn)(const engine_sched_item_t *item);

bool engine_scheduler_select_next(engine_scheduler_t *sched, engine_sched_key_fn key, engine_sched_item_t *out);

double engine_scheduler_edf_key(const engine_sched_item_t *item);

bool engine_scheduler_peek_next_class(const engine_scheduler_t *sched, char *out_class, size_t out_size);

uint8_t engine_scheduler_candidate_classes(
    const engine_scheduler_t *sched,
    char out_classes[][ENGINE_SCHED_CLASS_NAME_MAX],
    uint8_t max_out);

bool engine_scheduler_is_empty(const engine_scheduler_t *sched);

uint8_t engine_scheduler_all_items(const engine_scheduler_t *sched, engine_sched_item_t out_items[], uint8_t max_out);

#ifdef __cplusplus
}
#endif

#endif
