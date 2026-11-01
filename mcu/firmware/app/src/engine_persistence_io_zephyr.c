#include "engine_persistence_io.h"

#include <string.h>

#include <zephyr/devicetree.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/util.h>
#include <zephyr/toolchain.h>

#define FLASH_WRITE_BLOCK DT_PROP(DT_CHOSEN(zephyr_flash), write_block_size)
#define RECORD_WRITE_SIZE ROUND_UP(sizeof(engine_persist_record_t), FLASH_WRITE_BLOCK)

BUILD_ASSERT(RECORD_WRITE_SIZE <= DT_REG_SIZE(DT_NODELABEL(slot0_partition)));
BUILD_ASSERT(RECORD_WRITE_SIZE <= DT_REG_SIZE(DT_NODELABEL(slot1_partition)));

static bool open_bank(engine_persist_bank_t bank, const struct flash_area **out_fa)
{
    uint8_t id;

    switch (bank) {
    case ENGINE_PERSIST_BANK_A:
        id = FIXED_PARTITION_ID(slot0_partition);
        break;
    case ENGINE_PERSIST_BANK_B:
        id = FIXED_PARTITION_ID(slot1_partition);
        break;
    default:
        return false;
    }
    return flash_area_open(id, out_fa) == 0;
}

bool engine_persist_io_read(engine_persist_bank_t bank, engine_persist_record_t *out)
{
    const struct flash_area *fa;

    if (!open_bank(bank, &fa)) {
        return false;
    }
    int rc = flash_area_read(fa, 0, out, sizeof(*out));
    flash_area_close(fa);
    return rc == 0;
}

bool engine_persist_io_write(engine_persist_bank_t bank, const engine_persist_record_t *record)
{
    const struct flash_area *fa;

    if (!open_bank(bank, &fa)) {
        return false;
    }

    int rc = flash_area_erase(fa, 0, fa->fa_size);
    if (rc == 0) {
        if (RECORD_WRITE_SIZE == sizeof(*record)) {
            rc = flash_area_write(fa, 0, record, sizeof(*record));
        } else {
            static uint8_t padded[RECORD_WRITE_SIZE];

            memset(padded, 0xFF, sizeof(padded));
            memcpy(padded, record, sizeof(*record));
            rc = flash_area_write(fa, 0, padded, sizeof(padded));
        }
    }
    flash_area_close(fa);
    return rc == 0;
}
