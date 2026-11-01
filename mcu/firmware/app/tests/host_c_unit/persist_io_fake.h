#ifndef PERSIST_IO_FAKE_H
#define PERSIST_IO_FAKE_H

#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    PERSIST_FAULT_NONE,
    PERSIST_FAULT_WRITE_ERROR,
    PERSIST_FAULT_TORN_PROGRAM,
    PERSIST_FAULT_TORN_ERASE,
} persist_fault_kind_t;

typedef struct {
    persist_fault_kind_t kind;
    uint32_t skip_writes;
    size_t offset;
    jmp_buf *power_loss;
} persist_fault_t;

void persist_io_fake_erase(void);
void persist_io_fake_arm_fault(persist_fault_t fault);
uint32_t persist_io_fake_write_count(void);

#endif
