/**
 * Ported from AeroTuner frontend/lib/premium-theme.ts (HEAD cba37df). Only change:
 * eyebrow / microLabel / badge / grade sizes +1px for desktop readability.
 *
 * GyroCore Premium Design System — Central Visual Primitives
 *
 * This is the single source of truth for all GyroCore visual tokens.
 * Future visual changes should start here rather than editing Tailwind
 * classes scattered across individual pages.
 *
 * Rules:
 * - No runtime state.
 * - No React imports.
 * - No external dependencies beyond cn().
 * - Helpers are pure string → string.
 */

import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  1. Page layout                                                     */
/* ------------------------------------------------------------------ */

export const appPage =
  "min-h-screen bg-[var(--gc-bg-base)] text-[var(--gc-text-primary)]";

export const appPageInner =
  "mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8";

export const pageHeader =
  "mb-8 flex flex-col gap-1";

export const pageHeaderTitle =
  "text-2xl font-semibold tracking-tight text-[var(--gc-text-heading)]";

export const pageHeaderSubtitle =
  "text-sm text-[var(--gc-text-secondary)]";

export const pageActions =
  "flex items-center gap-3";

/* ------------------------------------------------------------------ */
/*  2. Surfaces / cards                                                */
/* ------------------------------------------------------------------ */

const surfaceShell = "relative overflow-hidden rounded-xl";
const surfaceTopHighlight =
  "before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.06] before:to-transparent";
const surfaceInsetRing = "ring-1 ring-inset ring-[var(--gc-border-subtle)]";

export const cardBase = cn(
  surfaceShell,
  surfaceTopHighlight,
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-1)] to-[#0a101c]",
  "shadow-[0_1px_2px_rgba(0,0,0,0.35),0_8px_24px_-12px_rgba(0,0,0,0.55)]",
);

export const cardElevated = cn(
  surfaceShell,
  surfaceTopHighlight,
  surfaceInsetRing,
  "border border-[var(--gc-border-default)]",
  "bg-gradient-to-b from-[#111a2e] to-[var(--gc-bg-surface-1)]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03),0_12px_32px_-12px_rgba(0,0,0,0.65)]",
);

export const cardInteractive = cn(
  cardBase,
  "transition-all duration-200",
  "hover:border-[var(--gc-accent-border)]",
  "hover:bg-gradient-to-b hover:from-[var(--gc-bg-surface-2)] hover:to-[#0c1322]",
  "hover:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04),0_16px_40px_-14px_rgba(0,0,0,0.7)]",
);

export const cardMuted = cn(
  surfaceShell,
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-inset)] to-[#070b14]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.02)]",
);

export const sectionPanel = cn(
  cardBase,
  "p-5",
);

export const dataPanel = cn(
  "relative overflow-hidden rounded-lg",
  surfaceTopHighlight,
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-2)] to-[#0a101c]",
  "p-4",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.02)]",
);

export const insetPanel = cn(
  "relative overflow-hidden rounded-lg",
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-inset)] to-[#070b14]",
  "p-4",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.02)]",
);

export const chartPanel = cn(
  cardBase,
  "p-4",
);

export const codePanel = cn(
  insetPanel,
  "font-mono text-xs leading-relaxed text-[var(--gc-text-secondary)]",
);

/* ------------------------------------------------------------------ */
/*  3. Typography                                                      */
/* ------------------------------------------------------------------ */

export const eyebrow =
  "text-[11px] font-semibold uppercase tracking-widest text-[var(--gc-accent)]";

export const sectionTitle =
  "text-lg font-semibold tracking-tight text-[var(--gc-text-heading)]";

export const sectionSubtitle =
  "text-sm text-[var(--gc-text-secondary)]";

export const label =
  "text-xs font-medium text-[var(--gc-text-secondary)]";

export const mutedText =
  "text-sm text-[var(--gc-text-tertiary)]";

export const bodyText =
  "text-sm leading-relaxed text-[var(--gc-text-primary)]";

export const metricValue =
  "text-2xl font-semibold tabular-nums tracking-tight text-[var(--gc-text-heading)]";

export const metadataText =
  "text-xs text-[var(--gc-text-tertiary)]";

export const microLabel =
  "text-[11px] font-medium uppercase tracking-wider text-[var(--gc-text-tertiary)]";

export const sectionDivider = "border-t border-[var(--gc-border-subtle)]";

/* ------------------------------------------------------------------ */
/*  4. Buttons                                                         */
/* ------------------------------------------------------------------ */

const buttonShared =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gc-accent)]/35 focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--gc-bg-base)] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40 disabled:saturate-50";

export const primaryButton = cn(
  buttonShared,
  "h-9 px-4 text-sm font-semibold",
  "border border-[var(--gc-accent-border)]",
  "bg-gradient-to-b from-[var(--gc-accent)] to-[#14b8a6]",
  "text-[#031018]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.30),0_2px_12px_-2px_rgba(34,211,238,0.35)]",
  "hover:from-[var(--gc-accent-hover)] hover:to-[#2dd4bf]",
  "hover:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.35),0_4px_16px_-2px_rgba(34,211,238,0.42)]",
  "active:brightness-95",
  "disabled:from-[var(--gc-bg-surface-2)] disabled:to-[var(--gc-bg-surface-1)] disabled:text-[var(--gc-text-tertiary)] disabled:border-[var(--gc-border-subtle)] disabled:shadow-none disabled:saturate-[0.25]",
);

export const secondaryButton = cn(
  buttonShared,
  "h-9 px-4 text-sm font-medium",
  "border border-[var(--gc-border-default)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-2)] to-[var(--gc-bg-surface-1)]",
  "text-[var(--gc-text-primary)]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]",
  "hover:border-[var(--gc-border-strong)]",
  "hover:bg-gradient-to-b hover:from-[var(--gc-bg-surface-3)] hover:to-[var(--gc-bg-surface-2)]",
  "hover:text-[var(--gc-text-heading)]",
  "disabled:bg-[var(--gc-bg-inset)] disabled:text-[var(--gc-text-tertiary)] disabled:border-[var(--gc-border-subtle)] disabled:shadow-none",
);

export const ghostButton = cn(
  buttonShared,
  "h-9 px-4 text-sm",
  "border border-transparent",
  "text-[var(--gc-text-secondary)]",
  "hover:border-[var(--gc-border-subtle)]",
  "hover:bg-[var(--gc-bg-surface-2)]/50",
  "hover:text-[var(--gc-text-primary)]",
  "disabled:bg-transparent disabled:text-[var(--gc-text-tertiary)]",
);

export const dangerButton = cn(
  buttonShared,
  "h-9 px-4 text-sm font-medium",
  "border border-[var(--gc-status-error-border)]",
  "bg-gradient-to-b from-[rgba(239,68,68,0.10)] to-[rgba(239,68,68,0.06)]",
  "text-[#fca5a5]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)]",
  "hover:border-[rgba(239,68,68,0.28)] hover:from-[rgba(239,68,68,0.14)] hover:to-[rgba(239,68,68,0.08)]",
  "disabled:from-[var(--gc-bg-inset)] disabled:to-[var(--gc-bg-inset)] disabled:text-[var(--gc-text-tertiary)] disabled:border-[var(--gc-border-subtle)]",
);

export const smallButton =
  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 h-7 text-xs font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gc-accent)]/35 focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--gc-bg-base)] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40 disabled:saturate-50";

export const iconButton = cn(
  "inline-flex items-center justify-center rounded-lg h-9 w-9",
  "border border-transparent",
  "text-[var(--gc-text-secondary)]",
  "transition-all duration-150",
  "hover:border-[var(--gc-border-subtle)] hover:bg-[var(--gc-bg-surface-2)]/50 hover:text-[var(--gc-text-primary)]",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gc-accent)]/35 focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--gc-bg-base)]",
  "disabled:pointer-events-none disabled:opacity-40 disabled:saturate-50",
);

/* ------------------------------------------------------------------ */
/*  5. Badges / chips                                                  */
/* ------------------------------------------------------------------ */

export const badgeBase =
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-medium leading-tight shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)]";

export const badgeNeutral = cn(
  badgeBase,
  "border border-[var(--gc-border-default)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-3)] to-[var(--gc-bg-surface-2)]",
  "text-[var(--gc-text-secondary)]",
);

export const badgeInfo = cn(
  badgeBase,
  "border border-[var(--gc-accent-border)]",
  "bg-[var(--gc-accent-muted)] text-[var(--gc-accent)]",
);

export const badgeSuccess = cn(
  badgeBase,
  "border border-[var(--gc-status-good-border)]",
  "bg-[var(--gc-status-good-bg)] text-[#6ee7b7]",
);

export const badgeWarning = cn(
  badgeBase,
  "border border-[var(--gc-status-warn-border)]",
  "bg-[var(--gc-status-warn-bg)] text-[#fcd34d]",
);

export const badgeDanger = cn(
  badgeBase,
  "border border-[var(--gc-status-error-border)]",
  "bg-[var(--gc-status-error-bg)] text-[#fca5a5]",
);

export const badgeMuted = cn(
  badgeBase,
  "border border-[var(--gc-border-subtle)]",
  "bg-[var(--gc-bg-inset)] text-[var(--gc-text-tertiary)]",
);

export const gradeBadge =
  "inline-flex items-center justify-center rounded-full px-2.5 py-0.5 text-[12px] font-semibold uppercase tracking-wider border border-[var(--gc-border-default)] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]";

/* ------------------------------------------------------------------ */
/*  6. Tabs                                                            */
/* ------------------------------------------------------------------ */

export const tabRail =
  "flex items-center gap-1 border-b border-[var(--gc-border-subtle)] pb-px";

export const tabButtonBase =
  "relative px-3 py-2 text-sm font-medium transition-colors rounded-t-md";

export const tabButtonActive = cn(
  tabButtonBase,
  "text-[var(--gc-accent)] after:absolute after:inset-x-0 after:bottom-[-1px] after:h-[2px] after:bg-[var(--gc-accent)] after:rounded-full",
);

export const tabButtonInactive = cn(
  tabButtonBase,
  "text-[var(--gc-text-tertiary)] hover:text-[var(--gc-text-secondary)]",
);

/* ------------------------------------------------------------------ */
/*  7. Forms                                                           */
/* ------------------------------------------------------------------ */

export const inputBase =
  "h-9 w-full rounded-lg border border-[var(--gc-border-default)] bg-[var(--gc-bg-inset)] px-3 text-sm text-[var(--gc-text-primary)] placeholder:text-[var(--gc-text-tertiary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.12)] transition-colors focus:border-[var(--gc-accent-border)] focus:outline-none focus:ring-2 focus:ring-[var(--gc-accent)]/20 disabled:cursor-not-allowed disabled:bg-[var(--gc-bg-surface-1)] disabled:text-[var(--gc-text-tertiary)] disabled:opacity-60";

export const selectBase =
  "h-9 w-full rounded-lg border border-[var(--gc-border-default)] bg-[var(--gc-bg-inset)] px-3 text-sm text-[var(--gc-text-primary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.12)] transition-colors focus:border-[var(--gc-accent-border)] focus:outline-none focus:ring-2 focus:ring-[var(--gc-accent)]/20 disabled:cursor-not-allowed disabled:bg-[var(--gc-bg-surface-1)] disabled:text-[var(--gc-text-tertiary)] disabled:opacity-60";

export const textareaBase =
  "w-full rounded-lg border border-[var(--gc-border-default)] bg-[var(--gc-bg-inset)] px-3 py-2 text-sm text-[var(--gc-text-primary)] placeholder:text-[var(--gc-text-tertiary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.12)] transition-colors focus:border-[var(--gc-accent-border)] focus:outline-none focus:ring-2 focus:ring-[var(--gc-accent)]/20 disabled:cursor-not-allowed disabled:bg-[var(--gc-bg-surface-1)] disabled:text-[var(--gc-text-tertiary)] disabled:opacity-60";

export const fieldLabel =
  "mb-1.5 block text-xs font-medium text-[var(--gc-text-secondary)]";

export const fieldHelp =
  "mt-1.5 text-xs text-[var(--gc-text-tertiary)]";

export const formError =
  "mt-1.5 text-xs text-[var(--gc-status-error)]";

/* ------------------------------------------------------------------ */
/*  8. Semantic state panels                                           */
/* ------------------------------------------------------------------ */

export const stateNeutral =
  "border-l-2 border-l-[var(--gc-border-default)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

export const stateBetter =
  "border-l-2 border-l-[var(--gc-status-good)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

export const stateWorse =
  "border-l-2 border-l-[var(--gc-status-error)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

export const stateWarning =
  "border-l-2 border-l-[var(--gc-status-warn)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

export const stateInfo =
  "border-l-2 border-l-[var(--gc-status-info)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

export const stateMissing =
  "border-l-2 border-l-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)] rounded-r-lg p-3 opacity-60";

export const stateDerived =
  "border-l-2 border-l-[var(--gc-teal)] bg-[var(--gc-bg-surface-1)] rounded-r-lg p-3";

/* ------------------------------------------------------------------ */
/*  9. Specialized analysis / result surfaces                          */
/* ------------------------------------------------------------------ */

export const analysisShell =
  "rounded-xl border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-surface-1)] p-6";

export const resultPanel =
  "rounded-xl border border-[var(--gc-border-default)] bg-[var(--gc-bg-surface-1)] p-5";

export const warningPanel =
  "rounded-lg border border-[var(--gc-status-warn-border)] bg-[var(--gc-status-warn-bg)] p-4";

export const lockedPanel =
  "rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)] p-4 opacity-60";

export const cliPanel =
  "rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)] p-4 font-mono text-xs leading-relaxed";

export const comparePanel =
  "rounded-xl border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-surface-1)]";

/** Outer card on compare / decision views — matches Runs manager elevated cards */
export const comparePageCard = cn(cardElevated);

/** Shared outer shell for result cards (Setup summary, Advanced Analysis, Export) */
export const comparePanelShell = comparePageCard;

/** Inner metric / field panel on compare views — matches Runs manager data panels */
export const compareInnerPanel = cn(dataPanel);

/** Marketing / homepage cards — same elevated navy surface as Runs manager */
export const marketingCard = cn(cardElevated, "p-5 sm:p-6");

export const marketingCardInteractive = cn(
  cardInteractive,
  "p-5 sm:p-6",
);

export const marketingPipelineCard = cn(
  cardBase,
  "p-5 transition-all duration-200 hover:border-[var(--gc-accent-border)]",
);

/** App nav bar shell — translucent navy bar over the dark-blue canvas */
export const navBarShell = cn(
  "rounded-xl border border-[var(--gc-border-subtle)]",
  "bg-[var(--gc-bg-surface-1)]/85 backdrop-blur-xl",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03),0_2px_8px_rgba(0,0,0,0.30)]",
);

/** Segmented tab rail (Run detail / compare tab rhythm) */
export const segmentedTabRail = cn(
  "flex flex-wrap gap-1 rounded-xl border border-[var(--gc-border-subtle)]",
  "bg-[var(--gc-bg-surface-1)]/90 p-1.5",
);

export const segmentedTabActive = cn(
  "h-9 rounded-lg px-4 text-sm font-medium transition-all duration-200",
  "border border-[var(--gc-border-default)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-3)] to-[var(--gc-bg-surface-2)]",
  "text-[var(--gc-text-heading)] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]",
);

export const segmentedTabInactive = cn(
  "h-9 rounded-lg px-4 text-sm font-medium transition-all duration-200",
  "border border-transparent text-[var(--gc-text-tertiary)]",
  "hover:bg-[var(--gc-bg-surface-2)]/50 hover:text-[var(--gc-text-secondary)]",
);

/** Run detail underline tabs — matches Tune / Signals premium header rhythm */
export const runDetailTabRail =
  "flex flex-wrap items-end gap-0 border-b border-[var(--gc-border-subtle)]";

export const runDetailTabActive = cn(
  "relative px-4 py-3 text-sm font-medium text-[var(--gc-text-heading)] transition-colors",
  "after:absolute after:inset-x-2 after:bottom-0 after:h-[3px] after:rounded-full after:bg-[var(--gc-accent)]",
);

export const runDetailTabInactive = cn(
  "px-4 py-3 text-sm font-medium text-[var(--gc-text-tertiary)] transition-colors",
  "hover:text-[var(--gc-text-secondary)]",
);

/** Auth card shell — navy premium panel aligned with Runs surfaces */
export const authCardShell = cn(
  cardElevated,
  "overflow-hidden rounded-2xl",
);

export const authFormInput = cn(
  inputBase,
  "mt-1.5 h-auto px-4 py-3.5 text-[15px]",
);

export const authMutedPanel =
  "rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)] px-4 py-3.5";

/** Wizard hardware / option chip buttons */
export const wizardOptionBtn = cn(
  "rounded-2xl border border-[var(--gc-border-default)]",
  "bg-[var(--gc-bg-inset)] text-center transition",
  "hover:border-[var(--gc-border-strong)] hover:bg-[var(--gc-bg-surface-2)]",
);

export const wizardOptionBtnActive = cn(
  "rounded-2xl border border-[var(--gc-accent-border)]",
  "bg-[var(--gc-accent-muted)] text-center transition",
);

export const compareRow =
  "grid grid-cols-[1fr_1fr] gap-px border-b border-[var(--gc-border-subtle)] last:border-b-0";

export const metricTile = cn(
  surfaceShell,
  surfaceTopHighlight,
  surfaceInsetRing,
  "flex flex-col gap-1.5",
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-surface-2)] to-[#0a101c]",
  "p-4",
  "shadow-[0_1px_2px_rgba(0,0,0,0.35),0_8px_24px_-12px_rgba(0,0,0,0.55)]",
);

export const signalControl =
  "flex items-center gap-2 rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-surface-2)] px-3 py-2";

export const signalToggle =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors";

/** Chart well — inset navy panel for uPlot trace area */
export const chartWellPanel = cn(
  "relative overflow-hidden rounded-xl",
  surfaceTopHighlight,
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-inset)] to-[#0a101c]",
  "shadow-[inset_0_1px_0_0_rgba(255,255,255,0.02),0_0_34px_rgba(59,130,246,0.06)]",
);

/** Navigator overview track below main chart */
export const chartOverviewTrack = cn(
  "relative overflow-hidden rounded-lg",
  surfaceInsetRing,
  "border border-[var(--gc-border-subtle)]",
  "bg-gradient-to-b from-[var(--gc-bg-inset)] to-[#070b14]",
  "px-0 py-0.5",
);

/** Compact segmented control rail on signal toolbar */
export const signalControlPanel = cn(
  "inline-flex rounded-lg border border-[var(--gc-border-subtle)]",
  "bg-[var(--gc-bg-surface-1)]/90 p-1",
);

/** Run legend chip on signal views */
export const chipLabel = cn(
  badgeNeutral,
  "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs",
);

/** Modal backdrop overlay */
export const dialogOverlay =
  "absolute inset-0 bg-[var(--gc-bg-base)]/75 backdrop-blur-[2px]";

/** Modal content shell */
export const dialogShell = cn(
  cardElevated,
  "flex max-h-[min(85vh,26rem)] w-full max-w-md flex-col overflow-hidden rounded-xl",
  "text-[var(--gc-text-primary)]",
);

/* ------------------------------------------------------------------ */
/*  Helper functions                                                   */
/* ------------------------------------------------------------------ */

type SurfaceVariant = "base" | "elevated" | "interactive" | "muted" | "inset" | "data" | "chart" | "code";

const surfaceMap: Record<SurfaceVariant, string> = {
  base: cardBase,
  elevated: cardElevated,
  interactive: cardInteractive,
  muted: cardMuted,
  inset: insetPanel,
  data: dataPanel,
  chart: chartPanel,
  code: codePanel,
};

export function surfaceCard(variant: SurfaceVariant, className?: string): string {
  return cn(surfaceMap[variant], className);
}

type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

const badgeToneMap: Record<StatusTone, string> = {
  neutral: badgeNeutral,
  info: badgeInfo,
  success: badgeSuccess,
  warning: badgeWarning,
  danger: badgeDanger,
  muted: badgeMuted,
};

export function statusBadge(tone: StatusTone, className?: string): string {
  return cn(badgeToneMap[tone], className);
}

type PanelTone = "neutral" | "better" | "worse" | "warning" | "info" | "missing" | "derived";

const panelToneMap: Record<PanelTone, string> = {
  neutral: stateNeutral,
  better: stateBetter,
  worse: stateWorse,
  warning: stateWarning,
  info: stateInfo,
  missing: stateMissing,
  derived: stateDerived,
};

export function statusPanel(tone: PanelTone, className?: string): string {
  return cn(panelToneMap[tone], className);
}

export function tabButton(active: boolean, className?: string): string {
  return cn(active ? tabButtonActive : tabButtonInactive, className);
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const buttonVariantMap: Record<ButtonVariant, string> = {
  primary: primaryButton,
  secondary: secondaryButton,
  ghost: ghostButton,
  danger: dangerButton,
};

export function actionButton(variant: ButtonVariant, className?: string): string {
  return cn(buttonVariantMap[variant], className);
}
