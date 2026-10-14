#include "engine_persistence_io.h"

#include <string.h>

#include <zephyr/storage/flash_map.h>

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
        rc = flash_area_write(fa, 0, record, sizeof(*record));
    }
    flash_area_close(fa);
    return rc == 0;
}
