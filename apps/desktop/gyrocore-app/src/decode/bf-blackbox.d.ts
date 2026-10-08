declare module "@bf-blackbox/flightlog.js" {
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
    getChunksInTimeRange(start: number, end: number): Array<{ frames: number[][] }>;
  }
}
