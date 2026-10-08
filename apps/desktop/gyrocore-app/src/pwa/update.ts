/**
 * Prompt-based PWA update abstraction.
 * Never force-reloads during an active analysis session.
 */

export type PwaUpdateState = {
  needRefresh: boolean;
  offlineReady: boolean;
};

export type PwaUpdateController = {
  getState: () => PwaUpdateState;
  /** Apply waiting SW when the user opts in and no session is busy. */
  applyUpdate: () => Promise<boolean>;
  /** Call when analysis/tuning work starts or ends. */
  setSessionBusy: (busy: boolean) => void;
  subscribe: (listener: (state: PwaUpdateState) => void) => () => void;
};

type RegisterSW = (options: {
  immediate?: boolean;
  onNeedRefresh?: () => void;
  onOfflineReady?: () => void;
  onRegisteredSW?: (swUrl: string, registration?: ServiceWorkerRegistration) => void;
}) => (reloadPage?: boolean) => Promise<void>;

export function createPwaUpdateController(deps?: {
  registerSW?: RegisterSW;
  isBrowserPwaContext?: () => boolean;
}): PwaUpdateController {
  let needRefresh = false;
  let offlineReady = false;
  let sessionBusy = false;
  let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null;
  const listeners = new Set<(state: PwaUpdateState) => void>();

  const emit = () => {
    const state = { needRefresh, offlineReady };
    for (const l of listeners) l(state);
  };

  const isBrowserPwaContext =
    deps?.isBrowserPwaContext ??
    (() => typeof window !== "undefined" && typeof navigator !== "undefined" && "serviceWorker" in navigator);

  const attach = (register: RegisterSW) => {
    updateSW = register({
      immediate: true,
      onNeedRefresh() {
        needRefresh = true;
        emit();
      },
      onOfflineReady() {
        offlineReady = true;
        emit();
      },
    });
  };

  if (isBrowserPwaContext() && typeof window !== "undefined") {
    if (deps?.registerSW) {
      attach(deps.registerSW);
    } else {
      void import("virtual:pwa-register")
        .then((mod) => attach(mod.registerSW as RegisterSW))
        .catch(() => {
          // Dev / non-PWA builds may not expose virtual:pwa-register.
        });
    }
  }

  return {
    getState: () => ({ needRefresh, offlineReady }),
    setSessionBusy: (busy: boolean) => {
      sessionBusy = busy;
    },
    applyUpdate: async () => {
      if (!needRefresh || sessionBusy || !updateSW) return false;
      await updateSW(true);
      return true;
    },
    subscribe: (listener) => {
      listeners.add(listener);
      listener({ needRefresh, offlineReady });
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** Singleton used by the app shell. */
export const pwaUpdates = createPwaUpdateController();
