"use client";

import { useState } from "react";
import { LayoutDashboard, Activity, Mail, Settings, ChevronLeft, ChevronRight } from "lucide-react";
import styles from "./Sidebar.module.css";

export const TABS = [
  { label: "Plan", icon: LayoutDashboard },
  { label: "Trace", icon: Activity },
  { label: "Messages", icon: Mail },
  { label: "Setup", icon: Settings },
] as const;

export default function Sidebar({ tab, onTab }: { tab: string; onTab: (t: string) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.top}>
        <div className={styles.logo}>{!collapsed && <span className={styles.logoText}>Planner</span>}</div>
        <button className={styles.collapseBtn} onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar">
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
      <nav className={styles.nav}>
        {TABS.map(({ label, icon: Icon }) => (
          <button key={label} className={`${styles.navItem} ${tab === label ? styles.active : ""}`}
            onClick={() => onTab(label)} title={collapsed ? label : undefined}>
            <Icon size={18} />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </nav>
    </aside>
  );
}
