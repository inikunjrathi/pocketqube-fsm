#ifndef ENGINE_PERSISTENCE_IO_H
#define ENGINE_PERSISTENCE_IO_H

#include <stdbool.h>
#include <stdint.h>

#include "engine_persistence.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ENGINE_PERSIST_NAME_MAX 24

#define ENGINE_PERSIST_STR_MAX 32

typedef struct {
    uint8_t kind;
    uint8_t bool_value;
    uint8_t _reserved[2];
    double num_value;
    char name[ENGINE_PERSIST_NAME_MAX];
    char str_value[ENGINE_PERSIST_STR_MAX];
} __attribute__((packed)) engine_persist_entry_t;

typedef struct {
    uint8_t state_id;
    uint8_t context_count;
    uint8_t _reserved[2];
    engine_persist_entry_t entries[ENGINE_CONTEXT_MAX_ENTRIES];
} __attribute__((packed)) engine_persist_body_t;

typedef struct {
    uint32_t sequence;
    engine_persist_body_t body;
    uint32_t crc32;
} __attribute__((packed)) engine_persist_record_t;

bool engine_persist_io_read(engine_persist_bank_t bank, engine_persist_record_t *out);
bool engine_persist_io_write(engine_persist_bank_t bank, const engine_persist_record_t *record);

#ifdef __cplusplus
}
#endif

#endif
