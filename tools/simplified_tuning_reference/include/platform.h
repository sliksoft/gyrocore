/* Minimal stubs so vendored simplified_tuning.c can be compiled as a
 * reference harness. Defaults and constrain() match Betaflight 2026.6.2
 * headers (pid.h / gyro.h / maths.h). Tests hash those vendored headers
 * against the numbers compiled here.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <string.h>
