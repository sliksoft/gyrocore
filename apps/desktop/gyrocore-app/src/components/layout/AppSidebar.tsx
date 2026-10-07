import {
  Activity,
  BarChart3,
  FolderOpen,
  GitCompareArrows,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  SlidersHorizontal,
  Stethoscope,
  Terminal,
  Waves,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { NavId } from "@/bridge/types";
import { RedlineBrand } from "@/components/branding/RedlineBrand";
import {
  sidebarBrandClass,
  sidebarCollapseToggleBtn,
  sidebarNavLinkClass,
  sidebarShell,
  sidebarWaveDecoration,
  sidebarWidthClass,
} from "@/lib/sidebar-theme";
import { cn } from "@/lib/utils";

export const NAV: Array<{ id: NavId; label: string; icon: LucideIcon }> = [
  { id: "open", label: "Open", icon: FolderOpen },
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "blackbox", label: "Blackbox", icon: Activity },
  { id: "analysis", label: "Analysis", icon: BarChart3 },
  { id: "chirp", label: "CHIRP", icon: Waves },
  { id: "tune", label: "Tune", icon: SlidersHorizontal },
  { id: "safety", label: "Safety", icon: ShieldCheck },
  { id: "compare", label: "Compare", icon: GitCompareArrows },
  { id: "cli", label: "CLI", icon: Terminal },
  { id: "diagnostics", label: "Diagnostics", icon: Stethoscope },
];

export function AppSidebar({
  nav,
  onNav,
  collapsed,
  onToggleCollapsed,
}: {
  nav: NavId;
  onNav: (id: NavId) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  return (
    <aside
      className={cn(sidebarShell, sidebarWidthClass(collapsed))}
      aria-label="GyroCore"
      data-collapsed={collapsed ? "true" : "false"}
    >
      <div
        className={cn(
          "flex shrink-0 items-start gap-3 border-b border-white/10 pb-4 pt-5",
          collapsed ? "flex-col items-center px-2" : "justify-between px-5",
        )}
      >
        {collapsed ? (
          <span className={cn(sidebarBrandClass, "text-base")} title="GyroCore">
            G
          </span>
        ) : (
          <div className="min-w-0 flex-1">
            <span className={sidebarBrandClass}>GyroCore</span>
            <p className="m-0 mt-1 text-[13px] leading-snug text-[var(--gc-text-tertiary)]">
              local · offline · no FC write
            </p>
          </div>
        )}
        <button
          type="button"
          className={sidebarCollapseToggleBtn}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          onClick={onToggleCollapsed}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" aria-hidden /> : <PanelLeftClose className="h-4 w-4" aria-hidden />}
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden">
        <nav className={cn("py-4", collapsed ? "px-2" : "px-3")} aria-label="Workspace">
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = nav === item.id;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={cn(sidebarNavLinkClass(active), collapsed && "justify-center gap-0 px-2.5")}
                    data-testid={`nav-${item.id}`}
                    aria-current={active ? "page" : undefined}
                    title={item.label}
                    onClick={() => onNav(item.id)}
                  >
                    <Icon className="h-[18px] w-[18px] shrink-0 opacity-90" aria-hidden />
                    <span className={cn(collapsed && "sr-only")}>{item.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className={cn("relative z-10 mt-auto shrink-0 border-t border-white/10 py-4", collapsed ? "px-2" : "px-4")}>
          {collapsed ? (
            <div className="flex flex-col items-center gap-3">
              <RedlineBrand collapsed />
              <div className="grid place-items-center text-[var(--gc-text-tertiary)]" title="Engine: Python Core · authorize_cli only · No MSP / serial / apply-to-FC">
                <WifiOff className="h-4 w-4" aria-hidden />
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <RedlineBrand />
              <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-[12.5px] leading-relaxed text-[var(--gc-text-tertiary)]">
                <p className="m-0 flex items-center gap-1.5 font-medium text-[var(--gc-text-secondary)]">
                  <WifiOff className="h-3.5 w-3.5" aria-hidden /> Offline workspace
                </p>
                <p className="m-0 mt-1">Engine: Python Core</p>
                <p className="m-0">CLI: authorize_cli only</p>
                <p className="m-0">No MSP / serial / apply-to-FC</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={sidebarWaveDecoration} aria-hidden />
    </aside>
  );
}
