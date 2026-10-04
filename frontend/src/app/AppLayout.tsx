import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, BarChart3, ChevronRight, Eye, Menu, ScanSearch, Search, Server, ShieldCheck, X } from "lucide-react";
import { useApi, type OpsStatus, type SignalStats } from "./api";
import { timeAgo } from "./format";

const NAV = [
  { to: "/app", label: "Live signals", icon: Activity, end: true },
  { to: "/app/portfolio", label: "Portfolio & stress", icon: BarChart3 },
  { to: "/app/watchlist", label: "Watchlist", icon: Eye },
  { to: "/app/analyze", label: "Analyse your text", icon: ScanSearch },
  { to: "/app/model-trust", label: "Model trust", icon: ShieldCheck },
  { to: "/app/status", label: "Data sources", icon: Server },
];

export default function AppLayout() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    setOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);

  return (
    <div className="min-h-screen bg-[#0e0e0e] text-bone">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-line bg-ink transition-transform lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar />
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="lg:pl-[248px]">
        <TopBar onMenu={() => setOpen((o) => !o)} open={open} />
        <AnimatePresence mode="wait">
          <motion.main
            key={pathname}
            className="mx-auto max-w-[1400px] px-4 py-8 sm:px-8"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <Outlet />
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  );
}

function Sidebar() {
  const stats = useApi<SignalStats>("/signals/stats?days=1", 60_000);
  const ops = useApi<OpsStatus>("/ops/status", 60_000);
  const high = stats.data ? (stats.data.by_risk.High ?? 0) + (stats.data.by_risk.Critical ?? 0) : null;
  const sources = Object.values(ops.data?.collectors?.sources ?? {});
  const failing = sources.filter((s) => s.last_status !== "ok" || s.consecutive_failures > 0).length;
  const live = !ops.error && sources.length > 0;

  return (
    <>
      <Link to="/" className="flex items-center gap-2.5 px-6 py-6">
        <svg viewBox="0 0 32 20" className="h-5 w-8" aria-hidden>
          <path d="M1 11h7l3-8 5 15 3-7h12" fill="none" stroke="var(--color-gold)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="text-lg font-semibold tracking-tight">tripwire</span>
      </Link>
      <p className="eyebrow px-6 pt-4 pb-3 text-mute/70">Risk intelligence</p>
      <nav className="flex flex-col gap-1 px-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className="relative">
            {({ isActive }) => (
              <span
                className={`relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors ${
                  isActive ? "text-bone" : "text-mute hover:bg-ink-3 hover:text-bone"
                }`}
              >
                {isActive && (
                  <motion.span
                    layoutId="side-active"
                    className="absolute inset-0 rounded-md border-l-2 border-gold bg-gold/[0.08]"
                    transition={{ type: "spring", stiffness: 400, damping: 34 }}
                  />
                )}
                <Icon className="relative h-4 w-4" strokeWidth={1.6} />
                <span className="relative">{label}</span>
                {to === "/app" && high !== null && high > 0 && (
                  <span className="relative ml-auto rounded-full bg-gold/15 px-2 py-0.5 font-mono text-[10px] text-gold">{high}</span>
                )}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto border-t border-line p-4">
        <Link to="/" className="flex items-center justify-between rounded-md px-2 py-2 text-sm text-mute hover:text-bone">
          Product site <ChevronRight className="h-4 w-4" />
        </Link>
        <div className="mt-3 rounded-lg border border-line bg-ink-2 px-3 py-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-bone">
              <span className="relative flex h-2 w-2">
                {live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sage opacity-60" />}
                <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-sage" : "bg-ember-bright"}`} />
              </span>
              {live ? "Live" : "Offline"}
            </span>
            <span className="text-mute">
              {live ? (failing ? `${failing} source${failing > 1 ? "s" : ""} failing` : `${sources.length} sources ok`) : "API unreachable"}
            </span>
          </div>
          {ops.data?.collectors && (
            <p className="mt-2 text-mute">Collected {timeAgo(ops.data.collectors.updated_at)}</p>
          )}
        </div>
      </div>
    </>
  );
}

function TopBar({ onMenu, open }: { onMenu: () => void; open: boolean }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-[#0e0e0e]/85 px-4 backdrop-blur sm:px-8">
      <button className="lg:hidden" onClick={onMenu} aria-label="Menu">
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>
      <form
        className="flex flex-1 items-center gap-2 rounded-lg border border-line bg-ink-2 px-3 py-2 focus-within:border-gold/50"
        onSubmit={(e) => {
          e.preventDefault();
          navigate(q.trim() ? `/app?q=${encodeURIComponent(q.trim())}` : "/app");
        }}
      >
        <Search className="h-4 w-4 text-mute" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a ticker (e.g. WAL) or words in a headline"
          className="w-full bg-transparent text-sm text-bone placeholder:text-mute/70 focus:outline-none"
        />
      </form>
      <Link
        to="/app/portfolio#what-if"
        className="hidden shrink-0 rounded-md bg-ember px-4 py-2 text-sm font-medium text-cream transition-colors hover:bg-ember-bright sm:block"
      >
        Run stress test
      </Link>
    </header>
  );
}
