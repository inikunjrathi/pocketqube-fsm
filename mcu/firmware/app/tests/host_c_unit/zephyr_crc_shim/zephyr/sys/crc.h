#ifndef ZEPHYR_SYS_CRC_H_SHIM
#define ZEPHYR_SYS_CRC_H_SHIM
#include <stdint.h>
#include <stddef.h>
uint32_t crc32_ieee(const uint8_t *data, size_t len);
uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len);
#endif
