/**
 * Decode-only stub for Betaflight FlightLogFieldPresenter.
 * Avoids pulling Pinia/Vue UI stores into the browser decode worker.
 * GPL-3.0 upstream surface remains in third_party/; this is a GyroCore adapter stub.
 */

export function FlightLogFieldPresenter() {
  // intentional no-op constructor (matches upstream shape)
}

FlightLogFieldPresenter.adjustDebugDefsList = function adjustDebugDefsList() {
  // Debug field naming is presentation-only; decode does not require it.
};
