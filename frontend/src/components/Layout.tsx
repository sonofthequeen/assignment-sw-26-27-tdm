import { NavLink, Outlet } from "react-router";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/runs", label: "Run history", end: false },
  { to: "/tests/new", label: "New test", end: true },
];

export function Layout() {
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="border-b border-slate-800 bg-slate-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <NavLink to="/" className="font-semibold tracking-tight">
            Race UP <span className="text-sky-300">Test Data Manager</span>
          </NavLink>
          <nav aria-label="Main">
            <ul className="flex flex-wrap gap-1 text-sm">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `rounded px-2 py-1 ${isActive ? "bg-white/15 font-medium" : "text-slate-300 hover:text-white"}`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
