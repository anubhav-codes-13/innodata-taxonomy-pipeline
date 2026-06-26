import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

function TopBar({ rightSlot }: { rightSlot?: ReactNode }) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between bg-bar px-8">
      <NavLink to="/" className="text-lg font-bold text-white">
        ◧ Insight Engine
      </NavLink>
      <div>{rightSlot}</div>
    </header>
  );
}

const navItemClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-lg px-3 py-2 text-sm ${
    isActive ? "bg-[#E3E7EB] font-semibold text-ink" : "text-mut hover:bg-panel"
  }`;

function Sidebar() {
  return (
    <nav className="w-[200px] shrink-0 space-y-1 border-r border-line bg-panel p-4">
      <NavLink to="/dashboard" className={navItemClass}>
        Dashboard
      </NavLink>
      <NavLink to="/history" className={navItemClass}>
        History
      </NavLink>
      <NavLink to="/" end className={navItemClass}>
        Upload
      </NavLink>
    </nav>
  );
}

export function AppShell({
  sidebar = false,
  rightSlot,
  children,
}: {
  sidebar?: boolean;
  rightSlot?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <TopBar rightSlot={rightSlot} />
      <div className="flex min-h-0 flex-1">
        {sidebar && <Sidebar />}
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-10 py-9 ${className}`}>{children}</div>;
}
