#pragma once

#include <stdint.h>

#define LPF_MAX_HZ 1000
#define DYN_LPF_MAX_HZ 1000

#define GYRO_LPF1_DYN_MIN_HZ_DEFAULT 250
#define GYRO_LPF1_DYN_MAX_HZ_DEFAULT 500
#define GYRO_LPF2_HZ_DEFAULT 500

typedef struct gyroConfig_s {
    uint8_t simplified_gyro_filter;
    uint8_t simplified_gyro_filter_multiplier;
    uint16_t gyro_lpf1_dyn_min_hz;
    uint16_t gyro_lpf1_dyn_max_hz;
    uint16_t gyro_lpf1_static_hz;
    uint16_t gyro_lpf2_static_hz;
} gyroConfig_t;
