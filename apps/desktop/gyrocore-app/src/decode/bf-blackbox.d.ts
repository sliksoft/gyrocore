declare module "@bf-blackbox/flightlog.js" {
  export type FlightLogEventRecord = {
    event: number;
    data: Record<string, unknown>;
    /** Absent for trailing events after the last main frame. */
    time?: number;
  };
  export class FlightLog {
    constructor(logData: ArrayBuffer | Uint8Array);
    getLogCount(): number;
    getLogError(index: number): unknown;
    openLog(index: number): boolean;
    getMainFieldNames(): string[];
    getMainFieldIndexByName(name: string): number | undefined;
    getMinTime(index?: number): number;
    getMaxTime(index?: number): number;
    getSysConfig(): Record<string, unknown>;
    getChunksInTimeRange(
      start: number,
      end: number,
    ): Array<{ frames: number[][]; events?: FlightLogEventRecord[] }>;
  }
}

declare module "@bf-blackbox/flightlog_fielddefs.js" {
  export const FIRMWARE_TYPE_BASEFLIGHT: number;
  export const FIRMWARE_TYPE_CLEANFLIGHT: number;
  export const FIRMWARE_TYPE_BETAFLIGHT: number;
  export const FIRMWARE_TYPE_INAV: number;
  export const FlightLogEvent: Readonly<Record<string, number>>;
}
