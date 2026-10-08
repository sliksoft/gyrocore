/*
 * Reference runner for vendored Betaflight 2026.6.2 simplified_tuning.c.
 *
 * Line protocol (whitespace-separated), one command per line:
 *
 *   PID  mode master pitchD i d pi dmax ff pitchPi
 *   DTERM on multiplier dynMin dynMax static1 static2
 *   GYRO on multiplier dynMin dynMax static1 static2
 *   VALIDATE_PIDS mode master pitchD i d pi dmax ff pitchPi
 *                 pR iR dR fR dmaxR pP iP dP fP dmaxP pY iY dY fY dmaxY
 *   VALIDATE_DTERM on multiplier dynMin dynMax static1 static2
 *   VALIDATE_GYRO on multiplier dynMin dynMax static1 static2
 *
 * PID/DTERM/GYRO print the applied profile. VALIDATE_* print 1 or 0.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "config/simplified_tuning.h"

static void load_pid_defaults(pidProfile_t *p)
{
    const pidf_t defs[3] = { PID_ROLL_DEFAULT, PID_PITCH_DEFAULT, PID_YAW_DEFAULT };
    const int dmax[3] = D_MAX_DEFAULT;
    memset(p, 0, sizeof(*p));
    for (int a = 0; a < 3; a++) {
        p->pid[a] = defs[a];
        p->d_max[a] = (uint8_t)dmax[a];
    }
    p->dterm_lpf1_dyn_min_hz = DTERM_LPF1_DYN_MIN_HZ_DEFAULT;
    p->dterm_lpf1_dyn_max_hz = DTERM_LPF1_DYN_MAX_HZ_DEFAULT;
    p->dterm_lpf1_static_hz = DTERM_LPF1_DYN_MIN_HZ_DEFAULT;
    p->dterm_lpf2_static_hz = DTERM_LPF2_HZ_DEFAULT;
}

static void load_gyro_defaults(gyroConfig_t *g)
{
    memset(g, 0, sizeof(*g));
    g->gyro_lpf1_dyn_min_hz = GYRO_LPF1_DYN_MIN_HZ_DEFAULT;
    g->gyro_lpf1_dyn_max_hz = GYRO_LPF1_DYN_MAX_HZ_DEFAULT;
    g->gyro_lpf1_static_hz = GYRO_LPF1_DYN_MIN_HZ_DEFAULT;
    g->gyro_lpf2_static_hz = GYRO_LPF2_HZ_DEFAULT;
}

static int read_sliders(pidProfile_t *p)
{
    unsigned mode, master, pitchD, i, d, pi, dmax, ff, pitchPi;
    if (scanf("%u %u %u %u %u %u %u %u %u", &mode, &master, &pitchD, &i, &d, &pi, &dmax, &ff, &pitchPi) != 9) {
        return 0;
    }
    p->simplified_pids_mode = (uint8_t)mode;
    p->simplified_master_multiplier = (uint8_t)master;
    p->simplified_roll_pitch_ratio = (uint8_t)pitchD;
    p->simplified_i_gain = (uint8_t)i;
    p->simplified_d_gain = (uint8_t)d;
    p->simplified_pi_gain = (uint8_t)pi;
    p->simplified_d_max_gain = (uint8_t)dmax;
    p->simplified_feedforward_gain = (uint8_t)ff;
    p->simplified_pitch_pi_gain = (uint8_t)pitchPi;
    return 1;
}

static void print_pids(const pidProfile_t *p)
{
    for (int a = 0; a < 3; a++) {
        printf("%u %u %u %u %u%s", p->pid[a].P, p->pid[a].I, p->pid[a].D, p->pid[a].F, p->d_max[a], a == 2 ? "\n" : " ");
    }
}

int main(void)
{
    char cmd[32];
    while (scanf("%31s", cmd) == 1) {
        if (strcmp(cmd, "PID") == 0) {
            pidProfile_t p;
            load_pid_defaults(&p);
            if (!read_sliders(&p)) {
                return 1;
            }
            applySimplifiedTuningPids(&p);
            print_pids(&p);
        } else if (strcmp(cmd, "DTERM") == 0) {
            pidProfile_t p;
            load_pid_defaults(&p);
            unsigned on, mult, dynMin, dynMax, s1, s2;
            if (scanf("%u %u %u %u %u %u", &on, &mult, &dynMin, &dynMax, &s1, &s2) != 6) {
                return 1;
            }
            p.simplified_dterm_filter = (uint8_t)on;
            p.simplified_dterm_filter_multiplier = (uint8_t)mult;
            p.dterm_lpf1_dyn_min_hz = (uint16_t)dynMin;
            p.dterm_lpf1_dyn_max_hz = (uint16_t)dynMax;
            p.dterm_lpf1_static_hz = (uint16_t)s1;
            p.dterm_lpf2_static_hz = (uint16_t)s2;
            applySimplifiedTuningDtermFilters(&p);
            printf("%u %u %u %u\n", p.dterm_lpf1_dyn_min_hz, p.dterm_lpf1_dyn_max_hz, p.dterm_lpf1_static_hz, p.dterm_lpf2_static_hz);
        } else if (strcmp(cmd, "GYRO") == 0) {
            gyroConfig_t g;
            load_gyro_defaults(&g);
            unsigned on, mult, dynMin, dynMax, s1, s2;
            if (scanf("%u %u %u %u %u %u", &on, &mult, &dynMin, &dynMax, &s1, &s2) != 6) {
                return 1;
            }
            g.simplified_gyro_filter = (uint8_t)on;
            g.simplified_gyro_filter_multiplier = (uint8_t)mult;
            g.gyro_lpf1_dyn_min_hz = (uint16_t)dynMin;
            g.gyro_lpf1_dyn_max_hz = (uint16_t)dynMax;
            g.gyro_lpf1_static_hz = (uint16_t)s1;
            g.gyro_lpf2_static_hz = (uint16_t)s2;
            applySimplifiedTuningGyroFilters(&g);
            printf("%u %u %u %u\n", g.gyro_lpf1_dyn_min_hz, g.gyro_lpf1_dyn_max_hz, g.gyro_lpf1_static_hz, g.gyro_lpf2_static_hz);
        } else if (strcmp(cmd, "VALIDATE_PIDS") == 0) {
            pidProfile_t current;
            load_pid_defaults(&current);
            if (!read_sliders(&current)) {
                return 1;
            }
            unsigned vals[15];
            for (int i = 0; i < 15; i++) {
                if (scanf("%u", &vals[i]) != 1) {
                    return 1;
                }
            }
            for (int a = 0; a < 3; a++) {
                current.pid[a].P = (uint8_t)vals[a * 5 + 0];
                current.pid[a].I = (uint8_t)vals[a * 5 + 1];
                current.pid[a].D = (uint8_t)vals[a * 5 + 2];
                current.pid[a].F = (uint16_t)vals[a * 5 + 3];
                current.d_max[a] = (uint8_t)vals[a * 5 + 4];
            }
            pidProfile_t temp = current;
            applySimplifiedTuningPids(&temp);
            int result = 1;
            for (int i = 0; i < 3; i++) {
                result = result && temp.pid[i].P == current.pid[i].P && temp.pid[i].I == current.pid[i].I
                    && temp.pid[i].D == current.pid[i].D && temp.d_max[i] == current.d_max[i]
                    && temp.pid[i].F == current.pid[i].F;
            }
            printf("%d\n", result);
        } else if (strcmp(cmd, "VALIDATE_DTERM") == 0) {
            pidProfile_t current;
            load_pid_defaults(&current);
            unsigned on, mult, dynMin, dynMax, s1, s2;
            if (scanf("%u %u %u %u %u %u", &on, &mult, &dynMin, &dynMax, &s1, &s2) != 6) {
                return 1;
            }
            current.simplified_dterm_filter = (uint8_t)on;
            current.simplified_dterm_filter_multiplier = (uint8_t)mult;
            current.dterm_lpf1_dyn_min_hz = (uint16_t)dynMin;
            current.dterm_lpf1_dyn_max_hz = (uint16_t)dynMax;
            current.dterm_lpf1_static_hz = (uint16_t)s1;
            current.dterm_lpf2_static_hz = (uint16_t)s2;
            pidProfile_t temp = current;
            applySimplifiedTuningDtermFilters(&temp);
            int result = temp.dterm_lpf1_static_hz == current.dterm_lpf1_static_hz
                && temp.dterm_lpf2_static_hz == current.dterm_lpf2_static_hz
                && temp.dterm_lpf1_dyn_min_hz == current.dterm_lpf1_dyn_min_hz
                && temp.dterm_lpf1_dyn_max_hz == current.dterm_lpf1_dyn_max_hz;
            printf("%d\n", result);
        } else if (strcmp(cmd, "VALIDATE_GYRO") == 0) {
            gyroConfig_t current;
            load_gyro_defaults(&current);
            unsigned on, mult, dynMin, dynMax, s1, s2;
            if (scanf("%u %u %u %u %u %u", &on, &mult, &dynMin, &dynMax, &s1, &s2) != 6) {
                return 1;
            }
            current.simplified_gyro_filter = (uint8_t)on;
            current.simplified_gyro_filter_multiplier = (uint8_t)mult;
            current.gyro_lpf1_dyn_min_hz = (uint16_t)dynMin;
            current.gyro_lpf1_dyn_max_hz = (uint16_t)dynMax;
            current.gyro_lpf1_static_hz = (uint16_t)s1;
            current.gyro_lpf2_static_hz = (uint16_t)s2;
            gyroConfig_t temp = current;
            applySimplifiedTuningGyroFilters(&temp);
            int result = temp.gyro_lpf1_static_hz == current.gyro_lpf1_static_hz
                && temp.gyro_lpf2_static_hz == current.gyro_lpf2_static_hz
                && temp.gyro_lpf1_dyn_min_hz == current.gyro_lpf1_dyn_min_hz
                && temp.gyro_lpf1_dyn_max_hz == current.gyro_lpf1_dyn_max_hz;
            printf("%d\n", result);
        } else {
            fprintf(stderr, "unknown command %s\n", cmd);
            return 1;
        }
    }
    return 0;
}
