#include <zephyr/arch/arm/nmi.h>
#include <zephyr/init.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/barrier.h>

#include <soc.h>

#define FLASH_BANK2_OFFSET 0x80000U
#define FLASH_PAGE_BYTES   2048U
#define FLASH_UNLOCK_KEY1  0x45670123U
#define FLASH_UNLOCK_KEY2  0xCDEF89ABU
#define FLASH_SR_ERRORS                                                                            \
    (FLASH_SR_OPERR | FLASH_SR_PROGERR | FLASH_SR_WRPERR | FLASH_SR_PGAERR | FLASH_SR_SIZERR |     \
     FLASH_SR_PGSERR | FLASH_SR_MISERR | FLASH_SR_FASTERR | FLASH_SR_RDERR | FLASH_SR_OPTVERR)

extern void z_SysNmiOnReset(void);

static bool in_persistence_bank(uint32_t offset)
{
    return (offset >= FIXED_PARTITION_OFFSET(slot0_partition) &&
            offset - FIXED_PARTITION_OFFSET(slot0_partition) < FIXED_PARTITION_SIZE(slot0_partition)) ||
           (offset >= FIXED_PARTITION_OFFSET(slot1_partition) &&
            offset - FIXED_PARTITION_OFFSET(slot1_partition) < FIXED_PARTITION_SIZE(slot1_partition));
}

static void wait_not_busy(void)
{
    while (FLASH->SR & FLASH_SR_BSY) {
    }
}

static void reset_data_cache(void)
{
    if (FLASH->ACR & FLASH_ACR_DCEN) {
        FLASH->ACR &= ~FLASH_ACR_DCEN;
        FLASH->ACR |= FLASH_ACR_DCRST;
        FLASH->ACR &= ~FLASH_ACR_DCRST;
        FLASH->ACR |= FLASH_ACR_DCEN;
    }
}


static bool erase_page(uint32_t offset)
{
    bool was_locked = (FLASH->CR & FLASH_CR_LOCK) != 0U;
    uint32_t page = (offset % FLASH_BANK2_OFFSET) / FLASH_PAGE_BYTES;

    wait_not_busy();
    FLASH->SR = FLASH->SR & FLASH_SR_ERRORS;
    if (was_locked) {
        FLASH->KEYR = FLASH_UNLOCK_KEY1;
        FLASH->KEYR = FLASH_UNLOCK_KEY2;
    }

    FLASH->CR &= ~(FLASH_CR_PNB | FLASH_CR_BKER);
    FLASH->CR |= FLASH_CR_PER | (page << FLASH_CR_PNB_Pos) |
                 (offset >= FLASH_BANK2_OFFSET ? FLASH_CR_BKER : 0U);
    FLASH->CR |= FLASH_CR_STRT;
    barrier_dsync_fence_full();
    wait_not_busy();
    FLASH->CR &= ~(FLASH_CR_PER | FLASH_CR_PNB | FLASH_CR_BKER);

    if (was_locked) {
        FLASH->CR |= FLASH_CR_LOCK;
    }
    reset_data_cache();
    return (FLASH->SR & FLASH_SR_ERRORS) == 0U;
}

static void ecc_nmi_handler(void)
{
    uint32_t eccr = FLASH->ECCR;
    uint32_t offset = (eccr & FLASH_ECCR_ADDR_ECC) + ((eccr & FLASH_ECCR_BK_ECC) ? FLASH_BANK2_OFFSET : 0U);

    if ((eccr & FLASH_ECCR_ECCD) == 0U || (eccr & FLASH_ECCR_SYSF_ECC) != 0U ||
        !in_persistence_bank(offset) || !erase_page(offset)) {
        z_SysNmiOnReset();
    }
    FLASH->ECCR = eccr;
}

static int install_ecc_nmi_handler(void)
{
    z_arm_nmi_set_handler(ecc_nmi_handler);
    return 0;
}

SYS_INIT(install_ecc_nmi_handler, PRE_KERNEL_1, CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);
