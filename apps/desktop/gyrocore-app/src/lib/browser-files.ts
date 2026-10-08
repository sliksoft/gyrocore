/** Browser-native flight file helpers (no OS paths). */

const BLACKBOX_EXT = new Set([".bbl", ".bfl", ".csv"]);
const CLI_EXT = new Set([".txt", ".text", ".cli", ".diff", ".cfg", ".conf"]);

export type SelectedLocalFile = {
  file: File;
  name: string;
  size: number;
};

export function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

export function isSupportedBlackboxName(name: string): boolean {
  return BLACKBOX_EXT.has(extensionOf(name));
}

export function isSupportedCliName(name: string): boolean {
  return CLI_EXT.has(extensionOf(name));
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function toSelectedLocalFile(file: File): SelectedLocalFile {
  return { file, name: file.name, size: file.size };
}

export const BLACKBOX_ACCEPT = ".bbl,.bfl,.csv,.BBL,.BFL,.CSV";
export const CLI_ACCEPT = ".txt,.text,.cli,.diff,.cfg,.conf,.TXT,.TEXT,.CLI,.DIFF,.CFG,.CONF";
