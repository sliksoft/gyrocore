/** Decode-only stub — FlightLog must not pull real Pinia into the worker. */
export function defineStore() {
  return () => ({});
}
export function createPinia() {
  return {};
}
export function setActivePinia() {}
export function getActivePinia() {
  return null;
}
export default { defineStore, createPinia, setActivePinia, getActivePinia };
