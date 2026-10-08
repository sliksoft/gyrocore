/*
 * This file is part of Cleanflight and Betaflight.
 *
 * Cleanflight and Betaflight are free software. You can redistribute
 * this software and/or modify this software under the terms of the
 * GNU General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option)
 * any later version.
 *
 * Cleanflight and Betaflight are distributed in the hope that they
 * will be useful, but WITHOUT ANY WARRANTY; without even the implied
 * warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this software.
 *
 * If not, see <http://www.gnu.org/licenses/>.
 */

/* Extract of simplified-tuning MSP helpers/cases from src/main/msp/msp.c
 * at Betaflight 2026.6.2. Parent file is not copied in full.
 */


/* msp.c:2308-2325 */
RAM_CODE static void readSimplifiedPids(pidProfile_t* pidProfile, sbuf_t *src)
{
    pidProfile->simplified_pids_mode = sbufReadU8(src);
    pidProfile->simplified_master_multiplier = sbufReadU8(src);
    pidProfile->simplified_roll_pitch_ratio = sbufReadU8(src);
    pidProfile->simplified_i_gain = sbufReadU8(src);
    pidProfile->simplified_d_gain = sbufReadU8(src);
    pidProfile->simplified_pi_gain = sbufReadU8(src);
#ifdef USE_D_MAX
    pidProfile->simplified_d_max_gain = sbufReadU8(src);
#else
    sbufReadU8(src);
#endif
    pidProfile->simplified_feedforward_gain = sbufReadU8(src);
    pidProfile->simplified_pitch_pi_gain = sbufReadU8(src);
    sbufReadU32(src); // reserved for future use
    sbufReadU32(src); // reserved for future use
}


/* msp.c:2328-2345 */
RAM_CODE static void writeSimplifiedPids(const pidProfile_t *pidProfile, sbuf_t *dst)
{
    sbufWriteU8(dst, pidProfile->simplified_pids_mode);
    sbufWriteU8(dst, pidProfile->simplified_master_multiplier);
    sbufWriteU8(dst, pidProfile->simplified_roll_pitch_ratio);
    sbufWriteU8(dst, pidProfile->simplified_i_gain);
    sbufWriteU8(dst, pidProfile->simplified_d_gain);
    sbufWriteU8(dst, pidProfile->simplified_pi_gain);
#ifdef USE_D_MAX
    sbufWriteU8(dst, pidProfile->simplified_d_max_gain);
#else
    sbufWriteU8(dst, 0);
#endif
    sbufWriteU8(dst, pidProfile->simplified_feedforward_gain);
    sbufWriteU8(dst, pidProfile->simplified_pitch_pi_gain);
    sbufWriteU32(dst, 0); // reserved for future use
    sbufWriteU32(dst, 0); // reserved for future use
}


/* msp.c:2348-2363 */
RAM_CODE static void readSimplifiedDtermFilters(pidProfile_t* pidProfile, sbuf_t *src)
{
    pidProfile->simplified_dterm_filter = sbufReadU8(src);
    pidProfile->simplified_dterm_filter_multiplier = sbufReadU8(src);
    pidProfile->dterm_lpf1_static_hz = sbufReadU16(src);
    pidProfile->dterm_lpf2_static_hz = sbufReadU16(src);
#if defined(USE_DYN_LPF)
    pidProfile->dterm_lpf1_dyn_min_hz = sbufReadU16(src);
    pidProfile->dterm_lpf1_dyn_max_hz = sbufReadU16(src);
#else
    sbufReadU16(src);
    sbufReadU16(src);
#endif
    sbufReadU32(src); // reserved for future use
    sbufReadU32(src); // reserved for future use
}


/* msp.c:2366-2381 */
RAM_CODE static void writeSimplifiedDtermFilters(const pidProfile_t* pidProfile, sbuf_t *dst)
{
    sbufWriteU8(dst, pidProfile->simplified_dterm_filter);
    sbufWriteU8(dst, pidProfile->simplified_dterm_filter_multiplier);
    sbufWriteU16(dst, pidProfile->dterm_lpf1_static_hz);
    sbufWriteU16(dst, pidProfile->dterm_lpf2_static_hz);
#if defined(USE_DYN_LPF)
    sbufWriteU16(dst, pidProfile->dterm_lpf1_dyn_min_hz);
    sbufWriteU16(dst, pidProfile->dterm_lpf1_dyn_max_hz);
#else
    sbufWriteU16(dst, 0);
    sbufWriteU16(dst, 0);
#endif
    sbufWriteU32(dst, 0); // reserved for future use
    sbufWriteU32(dst, 0); // reserved for future use
}


/* msp.c:2384-2399 */
RAM_CODE static void readSimplifiedGyroFilters(gyroConfig_t *gyroConfig, sbuf_t *src)
{
    gyroConfig->simplified_gyro_filter = sbufReadU8(src);
    gyroConfig->simplified_gyro_filter_multiplier = sbufReadU8(src);
    gyroConfig->gyro_lpf1_static_hz = sbufReadU16(src);
    gyroConfig->gyro_lpf2_static_hz = sbufReadU16(src);
#if defined(USE_DYN_LPF)
    gyroConfig->gyro_lpf1_dyn_min_hz = sbufReadU16(src);
    gyroConfig->gyro_lpf1_dyn_max_hz = sbufReadU16(src);
#else
    sbufReadU16(src);
    sbufReadU16(src);
#endif
    sbufReadU32(src); // reserved for future use
    sbufReadU32(src); // reserved for future use
}


/* msp.c:2402-2417 */
RAM_CODE static void writeSimplifiedGyroFilters(const gyroConfig_t *gyroConfig, sbuf_t *dst)
{
    sbufWriteU8(dst, gyroConfig->simplified_gyro_filter);
    sbufWriteU8(dst, gyroConfig->simplified_gyro_filter_multiplier);
    sbufWriteU16(dst, gyroConfig->gyro_lpf1_static_hz);
    sbufWriteU16(dst, gyroConfig->gyro_lpf2_static_hz);
#if defined(USE_DYN_LPF)
    sbufWriteU16(dst, gyroConfig->gyro_lpf1_dyn_min_hz);
    sbufWriteU16(dst, gyroConfig->gyro_lpf1_dyn_max_hz);
#else
    sbufWriteU16(dst, 0);
    sbufWriteU16(dst, 0);
#endif
    sbufWriteU32(dst, 0); // reserved for future use
    sbufWriteU32(dst, 0); // reserved for future use
}


/* ---- command cases ---- */

/* msp.c:2571-2576 */
    case MSP_SIMPLIFIED_TUNING:
        {
            writeSimplifiedPids(currentPidProfile, dst);
            writeSimplifiedDtermFilters(currentPidProfile, dst);
            writeSimplifiedGyroFilters(gyroConfig(), dst);
        }


/* msp.c:2579-2585 */
    case MSP_CALCULATE_SIMPLIFIED_PID:
        {
            pidProfile_t tempPidProfile = *currentPidProfile;
            readSimplifiedPids(&tempPidProfile, src);
            applySimplifiedTuningPids(&tempPidProfile);
            writePidfs(&tempPidProfile, dst);
        }


/* msp.c:2588-2594 */
    case MSP_CALCULATE_SIMPLIFIED_DTERM:
        {
            pidProfile_t tempPidProfile = *currentPidProfile;
            readSimplifiedDtermFilters(&tempPidProfile, src);
            applySimplifiedTuningDtermFilters(&tempPidProfile);
            writeSimplifiedDtermFilters(&tempPidProfile, dst);
        }


/* msp.c:2597-2603 */
    case MSP_CALCULATE_SIMPLIFIED_GYRO:
        {
            gyroConfig_t tempGyroConfig = *gyroConfig();
            readSimplifiedGyroFilters(&tempGyroConfig, src);
            applySimplifiedTuningGyroFilters(&tempGyroConfig);
            writeSimplifiedGyroFilters(&tempGyroConfig, dst);
        }


/* msp.c:2606-2649 */
    case MSP_VALIDATE_SIMPLIFIED_TUNING:
        {
            pidProfile_t tempPidProfile = *currentPidProfile;
            applySimplifiedTuningPids(&tempPidProfile);
            bool result = true;

            for (int i = 0; i < XYZ_AXIS_COUNT; i++) {
                result = result &&
                    tempPidProfile.pid[i].P == currentPidProfile->pid[i].P &&
                    tempPidProfile.pid[i].I == currentPidProfile->pid[i].I &&
                    tempPidProfile.pid[i].D == currentPidProfile->pid[i].D &&
                    tempPidProfile.d_max[i] == currentPidProfile->d_max[i] &&
                    tempPidProfile.pid[i].F == currentPidProfile->pid[i].F;
            }

            sbufWriteU8(dst, result);

            gyroConfig_t tempGyroConfig = *gyroConfig();
            applySimplifiedTuningGyroFilters(&tempGyroConfig);
            result =
                tempGyroConfig.gyro_lpf1_static_hz == gyroConfig()->gyro_lpf1_static_hz &&
                tempGyroConfig.gyro_lpf2_static_hz == gyroConfig()->gyro_lpf2_static_hz;

#if defined(USE_DYN_LPF)
            result = result &&
                tempGyroConfig.gyro_lpf1_dyn_min_hz == gyroConfig()->gyro_lpf1_dyn_min_hz &&
                tempGyroConfig.gyro_lpf1_dyn_max_hz == gyroConfig()->gyro_lpf1_dyn_max_hz;
#endif

            sbufWriteU8(dst, result);

            applySimplifiedTuningDtermFilters(&tempPidProfile);
            result =
                tempPidProfile.dterm_lpf1_static_hz == currentPidProfile->dterm_lpf1_static_hz &&
                tempPidProfile.dterm_lpf2_static_hz == currentPidProfile->dterm_lpf2_static_hz;

#if defined(USE_DYN_LPF)
            result = result &&
                tempPidProfile.dterm_lpf1_dyn_min_hz == currentPidProfile->dterm_lpf1_dyn_min_hz &&
                tempPidProfile.dterm_lpf1_dyn_max_hz == currentPidProfile->dterm_lpf1_dyn_max_hz;
#endif

            sbufWriteU8(dst, result);
        }


/* msp.c:3912-3918 */
    case MSP_SET_SIMPLIFIED_TUNING:
        {
            readSimplifiedPids(currentPidProfile, src);
            readSimplifiedDtermFilters(currentPidProfile, src);
            readSimplifiedGyroFilters(gyroConfigMutable(), src);
            applySimplifiedTuning(currentPidProfile, gyroConfigMutable());
        }

