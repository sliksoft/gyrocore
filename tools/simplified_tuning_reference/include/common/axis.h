#pragma once

typedef enum {
    FD_ROLL = 0,
    FD_PITCH,
    FD_YAW
} flight_dynamics_index_t;

#define FLIGHT_DYNAMICS_INDEX_COUNT 3
#define XYZ_AXIS_COUNT 3
#define X 0
#define Y 1
#define Z 2
