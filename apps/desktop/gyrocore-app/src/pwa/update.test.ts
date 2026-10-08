import { describe, expect, it, vi } from "vitest";
import { createPwaUpdateController } from "./update";

describe("pwa update controller", () => {
  it("tracks needRefresh and refuses apply while session busy", async () => {
    let onNeedRefresh: (() => void) | undefined;
    const updateSW = vi.fn(async () => undefined);
    const registerSW = vi.fn((opts: { onNeedRefresh?: () => void }) => {
      onNeedRefresh = opts.onNeedRefresh;
      return updateSW;
    });

    const ctrl = createPwaUpdateController({
      registerSW: registerSW as never,
      isBrowserPwaContext: () => true,
    });

    expect(registerSW).toHaveBeenCalled();
    onNeedRefresh?.();
    expect(ctrl.getState().needRefresh).toBe(true);

    ctrl.setSessionBusy(true);
    expect(await ctrl.applyUpdate()).toBe(false);
    expect(updateSW).not.toHaveBeenCalled();

    ctrl.setSessionBusy(false);
    expect(await ctrl.applyUpdate()).toBe(true);
    expect(updateSW).toHaveBeenCalledWith(true);
  });
});
