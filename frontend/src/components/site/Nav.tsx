import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ArrowRight, Menu, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Logo } from "./Logo";

export const NAV = [
  { to: "/product", label: "Product" },
  { to: "/how-it-works", label: "How it works" },
  { to: "/model-trust", label: "Model trust" },
  { to: "/resources", label: "Resources" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
        scrolled || open ? "border-b border-line/70 bg-ink/85 backdrop-blur-md" : "bg-transparent"
      }`}
    >
      <nav className="container-x flex h-16 items-center justify-between">
        <Link to="/" aria-label="Tripwire home">
          <Logo />
        </Link>
        <ul className="hidden h-full items-center gap-9 md:flex">
          {NAV.map((l) => (
            <li key={l.to} className="h-full">
              <NavLink to={l.to} className="group relative flex h-full items-center text-sm">
                {({ isActive }) => (
                  <>
                    <span className={`transition-colors ${isActive ? "text-bone" : "text-mute group-hover:text-bone"}`}>
                      {l.label}
                    </span>
                    {isActive && (
                      <motion.span
                        layoutId="nav-underline"
                        className="absolute inset-x-0 bottom-0 h-px bg-gold"
                        transition={{ type: "spring", stiffness: 380, damping: 32 }}
                      />
                    )}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="hidden md:block">
          <Link
            to="/app"
            className="group inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-bone"
          >
            View live demo
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
        <button className="md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu">
          {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </nav>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line bg-ink md:hidden"
          >
            <div className="container-x flex flex-col gap-4 py-6">
              {NAV.map((l) => (
                <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? "text-gold" : "text-bone")}>
                  {l.label}
                </NavLink>
              ))}
              <Link to="/app" className="text-gold">
                View live demo →
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
