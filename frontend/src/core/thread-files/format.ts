const BINARY_UNITS = ["KiB", "MiB", "GiB", "TiB"] as const;

/** Bytes in the binary units the artifact preview uses: `1.5 KiB`. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  let value = bytes;
  let unit = -1;
  // Step up while the rounded value would read 1024 of the current unit.
  do {
    value /= 1024;
    unit += 1;
  } while (
    Math.round(value * 10) / 10 >= 1024 &&
    unit < BINARY_UNITS.length - 1
  );
  return `${value.toFixed(1)} ${BINARY_UNITS[unit]}`;
}
