/* Nios V SoC host for Caliptra 2.x (passive / core-only, caliptra-rtl v2.1.2) on Agilex 5 E.
 * Port of quartus_a5e_nios/sw/app/main.c (Caliptra 1.1): same boot sequence, MAGIC/LED codes,
 * TRNG service, error handling and warm/cold reset helpers. 2.x differences:
 *   - PAUSER -> AXI_USER registers (same soc_ifc offsets); Nios AXI user = 1, fuse controller = 2
 *   - window: 1 MiB at CALIPTRA_WIN_BASE (0x0010_0000), decoded in rtl_2x/nios_caliptra2x_top.sv:
 *       +0x00000 soc_fw_store (FW bundle, 253,440 B)  +0x7F000 soc_fuse_ctrl2x  +0x80000 Caliptra AXI
 *       (AXI addr = offset - 0x80000: mbox_csr 0x2xxxx, soc_ifc 0x3xxxx)
 *   - STATUS_PIO bit1 = ready_for_mb_processing (1.x: ready_for_fw_push)
 *   - soc_fuse_ctrl2x writes 104 fuse words + 12 owner PK hash + hash lock + FUSE_WR_DONE (118)
 * Boot:
 *   1. power-good / reset release                         (SoC power sequencer)
 *   2. wait ready_for_fuses; program+lock AXI_USER (fuse, TRNG, mailbox);
 *      program CPTRA_TIMER_CONFIG and CPTRA_WDT_CFG
 *   3. soc_fuse_ctrl2x pushes the OTP fuse image + FUSE_WR_DONE (SoC fuse controller IP)
 *      -- after a warm reset (rst_b only) use START_DONE (CTRL bit2) instead
 *   4. service etrng_req with 12 TRNG words (SoC TRNG)     -- whole boot
 *   5. wait ready_for_mb_processing, mailbox FIRMWARE_LOAD of the FW bundle read from soc_fw_store
 *   6. wait ready_for_runtime, read FW_REV_ID
 * Same register sequence as the known-good sim host model in caliptra2x/sim_2x/tb_nios2x_top_fw.sv.
 * MAGIC_PIO milestones (led = MAGIC[7:0]) are the same as 1.x (README.md). TEST KEYS/ENTROPY ONLY. */
#include <stdint.h>
#include "sys/alt_stdio.h"
#include "system.h"

#ifdef CALIPTRA_WIN_BASE
#define SOC_WIN_BASE        CALIPTRA_WIN_BASE
#else
#define SOC_WIN_BASE        0x00100000u  /* mm_bridge 's0' in nios_caliptra2x_sys (1 MiB) */
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
#define CPTRA_AXI_OFF       0x80000u
#define CPTRA(off)          REG32(SOC_WIN_BASE + CPTRA_AXI_OFF + (off))  /* Caliptra AXI 0x2xxxx/0x3xxxx */
#define FWSTORE(i)          REG32(SOC_WIN_BASE + 0x00000u + 4u * (i))
#define FUSECTL(off)        REG32(SOC_WIN_BASE + 0x7F000u + (off))

/* ---- Caliptra 2.x AXI map (caliptra_reg_defines.svh, minus 0x3000_0000 high bits) ---- */
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
#define CPTRA_BOOT_STATUS   0x30038u
#define CPTRA_FLOW_STATUS   0x3003Cu
#define CPTRA_SECURITY_STATE 0x30044u
#define CPTRA_MBOX_VALID_AXI_USER0 0x30048u
#define CPTRA_MBOX_AXI_USER_LOCK0  0x3005Cu
#define CPTRA_TRNG_VALID_AXI_USER  0x30070u
#define CPTRA_TRNG_AXI_USER_LOCK   0x30074u
#define CPTRA_TRNG_DATA0    0x30078u   /* 12 words .. 0x300A4 */
#define CPTRA_TRNG_STATUS   0x300ACu   /* bit1 DATA_WR_DONE */
#define CPTRA_FUSE_WR_DONE  0x300B0u
#define CPTRA_TIMER_CONFIG  0x300B4u
#define CPTRA_HW_REV_ID     0x300D4u
#define CPTRA_FW_REV_ID0    0x300D8u
#define CPTRA_FW_REV_ID1    0x300DCu
#define CPTRA_HW_CONFIG     0x300E0u
#define CPTRA_FUSE_VALID_AXI_USER  0x30108u
#define CPTRA_FUSE_AXI_USER_LOCK   0x3010Cu
#define CPTRA_WDT_CFG0      0x30110u   /* ROM starts WDT1 with this timeout when debug_locked=1 */
#define CPTRA_WDT_CFG1      0x30114u
#define CPTRA_OWNER_PK_HASH_LOCK 0x30170u
#define WDT_TIMEOUT_CYCLES  100000000u /* same as 1.x */
#define TIMER_PERIOD_PS     20000u     /* clk period in picoseconds at 50 MHz */
#define HOST_AXI_USER       0x00000001u  /* NIOS_AXI_USER in rtl_2x/nios_caliptra2x_top.sv */
#define FUSE_AXI_USER       0x00000002u  /* FUSE_AXI_USER (soc_fuse_ctrl2x) */
#define MBOX_CMD_FWLD       0x46574C44u  /* "FWLD" FIRMWARE_LOAD */
#define MBOX_ST_DATA_READY  1u
#define MBOX_ST_CMD_COMPLETE 2u
#define MBOX_ST_CMD_FAILURE 3u

/* ---- soc_fuse_ctrl2x (rtl_2x/soc_fuse_ctrl2x.sv), same MMIO map as 1.x soc_fuse_ctrl ---- */
#define FC_ID               0x00u        /* 0x46555345 */
#define FC_CTRL             0x04u        /* bit0 START, bit1 CLEAR, bit2 START_DONE */
#define FC_STATUS           0x08u        /* bit0 BUSY bit1 DONE bit2 ERR bit3 RFF */
#define FC_COUNT            0x0Cu
#define FC_FW_BYTES         0x10u
#define FC_NUM_FUSES        0x14u
#define FC_START            1u
#define FC_CLEAR            2u
#define FC_START_DONE       4u           /* warm-reset: rewrite FUSE_WR_DONE only */

/* ---- CTRL/STATUS_PIO bits (rtl_2x/nios_caliptra2x_top.sv; same positions as 1.x) ---- */
#define CTRL_PWRGOOD        (1u << 0)
#define CTRL_RST_B          (1u << 1)
#define ST_READY_FOR_FUSES  (1u << 0)
#define ST_READY_FOR_MB     (1u << 1)    /* ready_for_mb_processing (1.x ready_for_fw_push) */
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

/* ---- SoC TRNG stand-in: the passive core-only 2.x build has no internal TRNG, so the ROM/FW
 * raise etrng_req and the SoC must supply 12 x 32b. xorshift = TEST ENTROPY ONLY. ---- */
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
        puthex("FATAL BOOT_STATUS=   ", CPTRA(CPTRA_BOOT_STATUS));
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

/* Program AXI_USER valid+lock in the 1.x order, plus timer and WDT.
 * Fuse AXI_USER (= soc_fuse_ctrl2x user 2, not the Nios) is sticky on pwrgood (skip after warm reset).
 * TRNG and mailbox AXI_USER/lock reset on rst_b and must be rewritten after warm reset. */
static void program_axi_user_timer_wdt(int include_fuse_user)
{
    if (include_fuse_user) {
        CPTRA(CPTRA_FUSE_VALID_AXI_USER) = FUSE_AXI_USER;
        CPTRA(CPTRA_FUSE_AXI_USER_LOCK)  = 1u;
    }
    CPTRA(CPTRA_TRNG_VALID_AXI_USER)     = HOST_AXI_USER;
    CPTRA(CPTRA_TRNG_AXI_USER_LOCK)      = 1u;
    CPTRA(CPTRA_MBOX_VALID_AXI_USER0)    = HOST_AXI_USER;
    CPTRA(CPTRA_MBOX_AXI_USER_LOCK0)     = 1u;
    CPTRA(CPTRA_TIMER_CONFIG)            = TIMER_PERIOD_PS;
    /* production (debug locked): ROM arms WDT1 from CPTRA_WDT_CFG; 0 => 1 cycle => fatal NMI */
    CPTRA(CPTRA_WDT_CFG0)                = WDT_TIMEOUT_CYCLES;
    CPTRA(CPTRA_WDT_CFG1)                = 0u;
}

/* Kick soc_fuse_ctrl2x: full image (START) or FUSE_WR_DONE only (START_DONE). */
static int start_fuses(int done_only)
{
    uint32_t fs;
    if (FUSECTL(FC_ID) != 0x46555345u) return ERR_FAIL;
    FUSECTL(FC_CTRL) = done_only ? FC_START_DONE : FC_START;
    for (uint32_t t = 0; ((fs = FUSECTL(FC_STATUS)) & 1u) || !(fs & 6u); t++)
        if (t > 1000000u) return ERR_TIMEOUT;
    if (fs & 4u) return ERR_FAIL;                       /* SLVERR or not ready_for_fuses */
    puthex("FUSE words written= ", FUSECTL(FC_COUNT));  /* 118 cold, 1 warm */
    if (!(CPTRA(CPTRA_FUSE_WR_DONE) & 1u)) return ERR_FAIL;
    if (!done_only && !(CPTRA(CPTRA_OWNER_PK_HASH_LOCK) & 1u)) return ERR_FAIL;
    puthex("CPTRA_FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
    return ERR_OK;
}

static int load_firmware(void)
{
    uint32_t fw_bytes = FUSECTL(FC_FW_BYTES);           /* 253,440 for fw-2.1.4 bundle */
    uint32_t t = 0, mst;
    while (CPTRA(MBOX_LOCK) & 1u) {
        trng_service();
        if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        if (++t > 10000000u) return ERR_TIMEOUT;
    }
    if (CPTRA(MBOX_USER) != HOST_AXI_USER) return ERR_FAIL;
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
    if ((mst & 0xFu) != MBOX_ST_CMD_COMPLETE) return ERR_FAIL;
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

/* Warm reset: hold pwrgood, pulse rst_b, wait ready_for_fuses, re-lock rst_b-domain AXI_USER
 * (TRNG + mailbox), write FUSE_WR_DONE only. After a completed cold boot the 2.x ROM warm-reset
 * flow resumes the existing firmware (no FIRMWARE_LOAD). If ready_for_mb_processing asserts
 * instead (previous cold boot did not complete) the bundle is loaded again. */
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
    program_axi_user_timer_wdt(0);                       /* skip fuse AXI_USER (pwrgood-sticky) */
    magic(0x00000013u);
    FUSECTL(FC_CTRL) = FC_CLEAR;
    rc = start_fuses(1);                                 /* START_DONE only */
    if (rc) return rc;
    magic(0x00000014u);
    for (uint32_t t = 0; t <= 200000000u; t++) {
        trng_service();
        if (handle_errors() == ERR_FATAL) return ERR_FATAL;
        if (status() & ST_READY_FOR_RT) {
            puthex("warm ready_for_runtime FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
            return ERR_OK;
        }
        if (status() & ST_READY_FOR_MB) {
            magic(0x00000015u);
            rc = load_firmware();
            if (rc) return rc;
            magic(0x00000017u);
            rc = wait_status(ST_READY_FOR_RT, 200000000u);
            if (rc) return rc;
            puthex("warm ready_for_runtime FLOW_STATUS = ", CPTRA(CPTRA_FLOW_STATUS));
            return rc;
        }
    }
    return ERR_TIMEOUT;
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
    puthex("CPTRA_HW_CONFIG   = ", CPTRA(CPTRA_HW_CONFIG));
    puthex("CPTRA_SECURITY_STATE = ", CPTRA(CPTRA_SECURITY_STATE));

    program_axi_user_timer_wdt(1);
    magic(0x00000003u);

    rc = start_fuses(0);
    if (rc) return rc;
    magic(0x00000004u);

    rc = wait_status(ST_READY_FOR_MB, 200000000u);
    if (rc) return rc;
    magic(0x00000005u);
    puthex("ready_for_mb_processing, trng_reqs = ", trng_reqs);

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
    /* caliptra_warm_reset() is available for a host-initiated warm reset. Not called automatically. */

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
