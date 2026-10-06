#pragma once

#include <stdint.h>
#include "common/axis.h"

#define PID_GAIN_MAX 250
#define F_GAIN_MAX 1000

#define PID_ROLL_DEFAULT  { 45, 80, 30, 120, 0 }
#define PID_PITCH_DEFAULT { 47, 84, 34, 125, 0 }
#define PID_YAW_DEFAULT   { 45, 80,  0, 120, 0 }
#define D_MAX_DEFAULT     { 40, 46, 0 }

#define DTERM_LPF1_DYN_MIN_HZ_DEFAULT 75
#define DTERM_LPF1_DYN_MAX_HZ_DEFAULT 150
#define DTERM_LPF2_HZ_DEFAULT 150

#define PID_ROLL  0
#define PID_PITCH 1
#define PID_YAW   2

typedef struct pidf_s {
    uint8_t P;
    uint8_t I;
    uint8_t D;
    uint16_t F;
    uint8_t S;
} pidf_t;

typedef struct pidProfile_s {
    pidf_t pid[FLIGHT_DYNAMICS_INDEX_COUNT];
    uint8_t d_max[XYZ_AXIS_COUNT];
    uint8_t simplified_pids_mode;
    uint8_t simplified_master_multiplier;
    uint8_t simplified_roll_pitch_ratio;
    uint8_t simplified_i_gain;
    uint8_t simplified_d_gain;
    uint8_t simplified_pi_gain;
    uint8_t simplified_d_max_gain;
    uint8_t simplified_feedforward_gain;
    uint8_t simplified_dterm_filter;
    uint8_t simplified_dterm_filter_multiplier;
    uint8_t simplified_pitch_pi_gain;
    uint16_t dterm_lpf1_dyn_min_hz;
    uint16_t dterm_lpf1_dyn_max_hz;
    uint16_t dterm_lpf1_static_hz;
    uint16_t dterm_lpf2_static_hz;
} pidProfile_t;
