/* Nios V SoC host for Caliptra 1.x (passive) on Agilex 5 E.
 * Mimics a real SoC boot of Caliptra 1.x:
 *   1. power-good / reset release                         (SoC power sequencer)
 *   2. wait ready_for_fuses; program+lock PAUSER (fuse, TRNG, mailbox);
 *      program CPTRA_TIMER_CONFIG and CPTRA_WDT_CFG
 *   3. soc_fuse_ctrl pushes the OTP fuse image + FUSE_WR_DONE (SoC fuse controller IP)
 *      -- after a warm reset (rst_b only) use START_DONE (CTRL bit2) instead
 *   4. service etrng_req with 12 TRNG words (SoC TRNG)     -- whole boot
 *   5. wait ready_for_fw_push, mailbox FIRMWARE_LOAD of the FW bundle read from
 *      soc_fw_store (stand-in for SoC boot flash)
 *   6. wait ready_for_runtime, read FW_REV_ID
 * Error handling (polled via STATUS_PIO; no Qsys IRQ in this PD):
 *   cptra_error_non_fatal -> log and RW1C-clear HW/FW_ERROR_NON_FATAL
 *   cptra_error_fatal     -> limited pwrgood (cold) reset recovery, then re-boot
 * MAGIC_PIO milestones (led = MAGIC[7:0]) are listed in README.md.
 * Same sequence as sim/tb_nios_top_fw.sv (passes in Verilator). TEST KEYS/ENTROPY ONLY. */
#include <stdint.h>
#include "sys/alt_stdio.h"
#include "system.h"

#ifdef CALIPTRA_WIN_BASE
#define SOC_WIN_BASE        CALIPTRA_WIN_BASE
#else
#define SOC_WIN_BASE        0x00040000u  /* mm_bridge 's0' in nios_caliptra_sys (256 KiB) */
#endif
#ifndef CTRL_PIO_BASE
#define CTRL_PIO_BASE       0x00080010u
#endif
#ifndef STATUS_PIO_BASE
#define STATUS_PIO_BASE     0x00080020u
#endif
#ifndef MAGIC_PIO_BASE
#define MAGIC_PIO_BASE      0x00080030u
#endif

#define REG32(a)            (*(volatile uint32_t *)(uintptr_t)(a))
#define CPTRA(off)          REG32(SOC_WIN_BASE + (off))      /* Caliptra APB (0x2xxxx/0x3xxxx) */
#define FWSTORE(i)          REG32(SOC_WIN_BASE + 0x00000u + 4u * (i))
#define FUSECTL(off)        REG32(SOC_WIN_BASE + 0x1F000u + (off))

/* ---- Caliptra 1.x APB map (caliptra_reg_defines.svh, minus 0x3003_0000 high bits) ---- */
#define MBOX_LOCK           0x20000u
#define MBOX_USER           0x20004u
#define MBOX_CMD            0x20008u
#define MBOX_DLEN           0x2000Cu
#define MBOX_DATAIN         0x20010u
#define MBOX_DATAOUT        0x20014u
#define MBOX_EXECUTE        0x20018u
#define MBOX_STATUS         0x2001Cu
#define CPTRA_HW_ERROR_FATAL     0x30000u
#define CPTRA_HW_ERROR_NON_FATAL 0x30004u
#define CPTRA_FW_ERROR_FATAL     0x30008u
#define CPTRA_FW_ERROR_NON_FATAL 0x3000Cu
#define CPTRA_FLOW_STATUS   0x3003Cu
#define CPTRA_MBOX_VALID_PAUSER0 0x30048u
#define CPTRA_MBOX_PAUSER_LOCK0  0x3005Cu
#define CPTRA_TRNG_VALID_PAUSER  0x30070u
#define CPTRA_TRNG_PAUSER_LOCK   0x30074u
#define CPTRA_TRNG_DATA0    0x30078u   /* 12 words .. 0x300A4 */
#define CPTRA_TRNG_STATUS   0x300ACu   /* bit1 DATA_WR_DONE */
#define CPTRA_FUSE_WR_DONE  0x300B0u
#define CPTRA_TIMER_CONFIG  0x300B4u
#define CPTRA_HW_REV_ID     0x300D4u
#define CPTRA_FUSE_VALID_PAUSER  0x30108u
#define CPTRA_FUSE_PAUSER_LOCK   0x3010Cu
#define CPTRA_WDT_CFG0      0x30110u   /* ROM starts WDT1 with this timeout when debug_locked=1 */
#define CPTRA_WDT_CFG1      0x30114u
#define WDT_TIMEOUT_CYCLES  100000000u /* hw-model default is 40M; margin for slow APB host */
#define TIMER_PERIOD_PS     20000u     /* clk period in picoseconds at 50 MHz */
#define CPTRA_FW_REV_ID0    0x300D8u
#define CPTRA_FW_REV_ID1    0x300DCu
#define HOST_PAUSER         0x00000001u  /* PAUSER driven by rtl/avmm_to_apb.sv (nios_pauser) */
#define MBOX_CMD_FWLD       0x46574C44u  /* "FWLD" FIRMWARE_LOAD */
#define MBOX_ST_DATA_READY  1u
#define MBOX_ST_CMD_COMPLETE 2u
#define MBOX_ST_CMD_FAILURE 3u

/* ---- soc_fuse_ctrl (rtl/soc_fuse_ctrl.sv) ---- */
#define FC_ID               0x00u        /* 0x46555345 */
#define FC_CTRL             0x04u        /* bit0 START, bit1 CLEAR, bit2 START_DONE */
#define FC_STATUS           0x08u        /* bit0 BUSY bit1 DONE bit2 ERR bit3 RFF */
#define FC_COUNT            0x0Cu
#define FC_FW_BYTES         0x10u
#define FC_NUM_FUSES        0x14u
#define FC_START            1u
#define FC_CLEAR            2u
#define FC_START_DONE       4u           /* warm-reset: rewrite FUSE_WR_DONE only */

/* ---- STATUS_PIO bits (rtl/nios_caliptra_top.sv) ---- */
#define CTRL_PWRGOOD        (1u << 0)
#define CTRL_RST_B          (1u << 1)
#define ST_READY_FOR_FUSES  (1u << 0)
#define ST_READY_FOR_FW     (1u << 1)
#define ST_READY_FOR_RT     (1u << 2)
#define ST_ERROR_FATAL      (1u << 5)
#define ST_ERROR_NON_FATAL  (1u << 6)
#define ST_ETRNG_REQ        (1u << 7)

#define FATAL_RETRY_LIMIT   3u

#define ERR_OK              0
#define ERR_FATAL           1
#define ERR_TIMEOUT         2
#define ERR_FAIL            3

static inline void magic(uint32_t v) { REG32(MAGIC_PIO_BASE) = v; }
static void fail(uint32_t code) { magic(code); for (;;) ; }
static inline uint32_t status(void) { return REG32(STATUS_PIO_BASE); }

static void puthex(const char *l, uint32_t v)
{
    static const char h[] = "0123456789abcdef";
    char b[11] = "0x";
    for (int i = 0; i < 8; i++) b[2 + i] = h[(v >> (28 - 4 * i)) & 0xF];
    b[10] = 0;
    alt_putstr(l); alt_putstr(b); alt_putstr("\n");
}
static void delay(volatile uint32_t n) { while (n--) ; }

/* ---- SoC TRNG stand-in: 1.x RTL here has no internal TRNG, so the ROM/FW raise
 * etrng_req and the SoC must supply 12 x 32b. xorshift = TEST ENTROPY ONLY. ---- */
static uint32_t rng_state = 0x1234ABCDu;
static uint32_t trng_reqs;
static uint32_t xorshift32(void)
{
    uint32_t x = rng_state; x ^= x << 13; x ^= x >> 17; x ^= x << 5; return rng_state = x;
}
static void trng_service(void)
{
    if (!(status() & ST_ETRNG_REQ)) return;
    for (uint32_t i = 0; i < 12; i++) CPTRA(CPTRA_TRNG_DATA0 + 4u * i) = xorshift32();
    CPTRA(CPTRA_TRNG_STATUS) = 2u;                     /* DATA_WR_DONE */
    trng_reqs++;
    for (uint32_t t = 0; (status() & ST_ETRNG_REQ) && t < 100000u; t++) ;
}

/* Poll non-fatal errors: log and RW1C-clear. Fatal is returned to the caller. */
static int handle_errors(void)
{
    uint32_t st = status();
    if (st & ST_ERROR_NON_FATAL) {
        uint32_t hw = CPTRA(CPTRA_HW_ERROR_NON_FATAL);
        uint32_t fw = CPTRA(CPTRA_FW_ERROR_NON_FATAL);
        puthex("non_fatal HW_ERROR_NON_FATAL=", hw);
        puthex("non_fatal FW_ERROR_NON_FATAL=", fw);
        CPTRA(CPTRA_HW_ERROR_NON_FATAL) = hw;          /* RW1C */
        CPTRA(CPTRA_FW_ERROR_NON_FATAL) = fw;
        alt_putstr("cleared cptra_error_non_fatal\n");
    }
    if (st & ST_ERROR_FATAL) {
        puthex("FATAL HW_ERROR_FATAL=", CPTRA(CPTRA_HW_ERROR_FATAL));
        puthex("FATAL FW_ERROR_FATAL=", CPTRA(CPTRA_FW_ERROR_FATAL));
        return ERR_FATAL;
    }
    return ERR_OK;
}

/* wait for STATUS_PIO bit while servicing TRNG and non-fatal errors */
static int wait_status(uint32_t bit, uint32_t timeout_iters)
{
    for (uint32_t t = 0; !(status() & bit); t++) {
        trng_service();
        if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        if (t > timeout_iters) return ERR_TIMEOUT;
    }
    return ERR_OK;
}

/* Program PAUSER valid+lock in 1.x order, plus timer and WDT.
 * Fuse PAUSER is sticky on pwrgood (skip after a warm reset).
 * TRNG and mailbox PAUSER/lock reset on rst_b and must be rewritten after warm reset.
 * TIMER_CONFIG and WDT_CFG are pwrgood-sticky but are rewritten anyway (harmless). */
static void program_pauser_timer_wdt(int include_fuse_pauser)
{
    if (include_fuse_pauser) {
        CPTRA(CPTRA_FUSE_VALID_PAUSER) = HOST_PAUSER;
        CPTRA(CPTRA_FUSE_PAUSER_LOCK)  = 1u;
    }
    CPTRA(CPTRA_TRNG_VALID_PAUSER)     = HOST_PAUSER;
    CPTRA(CPTRA_TRNG_PAUSER_LOCK)      = 1u;
    CPTRA(CPTRA_MBOX_VALID_PAUSER0)    = HOST_PAUSER;
    CPTRA(CPTRA_MBOX_PAUSER_LOCK0)     = 1u;
    CPTRA(CPTRA_TIMER_CONFIG)          = TIMER_PERIOD_PS;
    /* production (debug locked): ROM arms WDT1 from CPTRA_WDT_CFG; 0 => 1 cycle => fatal NMI */
    CPTRA(CPTRA_WDT_CFG0)              = WDT_TIMEOUT_CYCLES;
    CPTRA(CPTRA_WDT_CFG1)              = 0u;
}

/* Kick soc_fuse_ctrl: full image (START) or FUSE_WR_DONE only (START_DONE). */
static int start_fuses(int done_only)
{
    uint32_t fs;
    if (FUSECTL(FC_ID) != 0x46555345u) return ERR_FAIL;
    FUSECTL(FC_CTRL) = done_only ? FC_START_DONE : FC_START;
    for (uint32_t t = 0; ((fs = FUSECTL(FC_STATUS)) & 1u) || !(fs & 6u); t++)
        if (t > 1000000u) return ERR_TIMEOUT;
    if (fs & 4u) return ERR_FAIL;                       /* PSLVERR or not ready_for_fuses */
    puthex("FUSE words written= ", FUSECTL(FC_COUNT));  /* 84 cold, 1 warm */
    if (!(CPTRA(CPTRA_FUSE_WR_DONE) & 1u)) return ERR_FAIL;
    puthex("CPTRA_FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
    return ERR_OK;
}

static int load_firmware(void)
{
    uint32_t fw_bytes = FUSECTL(FC_FW_BYTES);
    uint32_t t = 0, mst;
    while (CPTRA(MBOX_LOCK) & 1u) {
        trng_service();
        if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        if (++t > 10000000u) return ERR_TIMEOUT;
    }
    if (CPTRA(MBOX_USER) != HOST_PAUSER) return ERR_FAIL;
    CPTRA(MBOX_CMD)  = MBOX_CMD_FWLD;
    CPTRA(MBOX_DLEN) = fw_bytes;
    uint32_t words = (fw_bytes + 3u) / 4u;
    for (uint32_t i = 0; i < words; i++) {
        CPTRA(MBOX_DATAIN) = FWSTORE(i);
        if ((i & 0xFFu) == 0) {
            trng_service();
            if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        }
    }
    CPTRA(MBOX_EXECUTE) = 1u;
    magic(0x00000006u);
    puthex("FIRMWARE_LOAD bytes= ", fw_bytes);

    t = 0;
    while (((mst = CPTRA(MBOX_STATUS)) & 0xFu) == 0) {
        trng_service();
        if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        if (++t > 200000000u) return ERR_TIMEOUT;
    }
    puthex("MBOX_STATUS       = ", mst);
    CPTRA(MBOX_EXECUTE) = 0u;                            /* release mailbox */
    if ((mst & 0xFu) == MBOX_ST_CMD_FAILURE) return ERR_FAIL;
    return ERR_OK;
}

/* Release pwrgood then rst_b, with delay so the 2FF sync-deassert can complete. */
static void caliptra_cold_release(void)
{
    REG32(CTRL_PIO_BASE) = CTRL_PWRGOOD;
    delay(1000);
    REG32(CTRL_PIO_BASE) = CTRL_PWRGOOD | CTRL_RST_B;
    delay(100);
}

/* Full pwrgood cycle (cold reset) used to recover from cptra_error_fatal. */
void caliptra_pwrgood_cycle(void)
{
    alt_putstr("fatal: pwrgood cycle recovery\n");
    REG32(CTRL_PIO_BASE) = 0;
    delay(2000);                                         /* cover 2FF sync deassert of pwrgood + hold */
    caliptra_cold_release();
}

/* Warm reset: hold pwrgood, pulse rst_b, wait ready_for_fuses, re-lock
 * rst_b-domain PAUSER (TRNG + mailbox), write FUSE_WR_DONE only, then
 * FIRMWARE_LOAD through ready_for_runtime. Fuse PAUSER, WDT, TIMER persist. */
int caliptra_warm_reset(void)
{
    int rc;
    alt_putstr("warm reset: rst_b only (pwrgood held)\n");
    REG32(CTRL_PIO_BASE) = CTRL_PWRGOOD;                 /* drop rst_b, hold pwrgood */
    delay(2000);
    REG32(CTRL_PIO_BASE) = CTRL_PWRGOOD | CTRL_RST_B;
    delay(100);
    rc = wait_status(ST_READY_FOR_FUSES, 200000000u);
    if (rc) return rc;
    program_pauser_timer_wdt(0);                         /* skip fuse PAUSER (pwrgood-sticky) */
    magic(0x00000013u);
    FUSECTL(FC_CTRL) = FC_CLEAR;
    rc = start_fuses(1);                                 /* START_DONE only */
    if (rc) return rc;
    magic(0x00000014u);
    rc = wait_status(ST_READY_FOR_FW, 200000000u);
    if (rc) return rc;
    magic(0x00000015u);
    rc = load_firmware();
    if (rc) return rc;
    magic(0x00000017u);
    rc = wait_status(ST_READY_FOR_RT, 200000000u);
    if (rc) return rc;
    puthex("warm ready_for_runtime FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
    return ERR_OK;
}

/* Cold boot from a state where Caliptra is (or will be) out of reset. */
static int caliptra_cold_boot(void)
{
    int rc;
    rc = wait_status(ST_READY_FOR_FUSES, 200000000u);
    if (rc) return rc;
    magic(0x00000002u);
    uint32_t hw_rev = CPTRA(CPTRA_HW_REV_ID);
    puthex("CPTRA_HW_REV_ID   = ", hw_rev);
    if (hw_rev == 0 || hw_rev == 0xFFFFFFFFu) return ERR_FAIL;

    program_pauser_timer_wdt(1);
    magic(0x00000003u);

    rc = start_fuses(0);
    if (rc) return rc;
    magic(0x00000004u);

    rc = wait_status(ST_READY_FOR_FW, 200000000u);
    if (rc) return rc;
    magic(0x00000005u);
    puthex("ready_for_fw_push, trng_reqs = ", trng_reqs);

    rc = load_firmware();
    if (rc) return rc;
    magic(0x00000007u);

    rc = wait_status(ST_READY_FOR_RT, 200000000u);
    if (rc) return rc;
    puthex("ready_for_runtime FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
    puthex("CPTRA_FW_REV_ID0  = ", CPTRA(CPTRA_FW_REV_ID0));
    puthex("CPTRA_FW_REV_ID1  = ", CPTRA(CPTRA_FW_REV_ID1));
    return ERR_OK;
}

int main(void)
{
    uint32_t attempts = 0;
    int rc;

    magic(0x00000001u);                                  /* M1 alive */

    caliptra_cold_release();

    for (;;) {
        rc = caliptra_cold_boot();
        if (rc == ERR_OK) break;
        if (rc == ERR_FATAL) {
            if (++attempts > FATAL_RETRY_LIMIT) fail(0xDEAD00FFu);
            caliptra_pwrgood_cycle();
            continue;
        }
        fail(rc == ERR_TIMEOUT ? 0xDEAD000Eu : 0xDEAD000Fu);
    }
    magic(0xCA11F00Du);                                  /* success; led = 0x0D */
    /* caliptra_warm_reset() is available for a host-initiated warm reset
     * (hold pwrgood, pulse rst_b, START_DONE, FIRMWARE_LOAD). Not called
     * automatically after a successful cold boot. */

    /* Keep serving runtime TRNG and poll for errors (no IRQ wired in this PD). */
    for (;;) {
        trng_service();
        if (handle_errors() == ERR_FATAL) {
            if (++attempts > FATAL_RETRY_LIMIT) fail(0xDEAD00FFu);
            caliptra_pwrgood_cycle();
            rc = caliptra_cold_boot();
            if (rc == ERR_OK) {
                magic(0xCA11F00Du);
                continue;
            }
            if (rc == ERR_FATAL) continue;
            fail(0xDEAD0010u);
        }
    }
    return 0;
}
