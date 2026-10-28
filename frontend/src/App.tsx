import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard, Mail, ScanLine, Inbox, LogOut, Settings as SettingsIcon, BookOpen, ScrollText, MailMinus, ShieldCheck as ShieldIcon } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import Accounts from "./pages/Accounts";
import Scan from "./pages/Scan";
import Emails from "./pages/Emails";
import Settings from "./pages/Settings";
import Unsubscribe from "./pages/Unsubscribe";
import Privacy from "./pages/Privacy";
import Activity from "./pages/Activity";
import Guides from "./pages/Guides";
import Login from "./pages/Login";
import { getSession, logout } from "./lib/api";
import clsx from "clsx";

const qc = new QueryClient();
const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/accounts", label: "Accounts", icon: Mail },
  { to: "/scan", label: "Scan", icon: ScanLine },
  { to: "/emails", label: "Emails", icon: Inbox },
  { to: "/unsubscribe", label: "Review", icon: MailMinus },
  { to: "/privacy", label: "Privacy", icon: ShieldIcon },
  { to: "/activity", label: "Activity", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
  { to: "/guides", label: "Guides", icon: BookOpen },
];

function Shell() {
  const client = useQueryClient();
  const { data: authed, isLoading } = useQuery({ queryKey: ["session"], queryFn: getSession, retry: false });
  if (isLoading) return null;
  if (!authed) return <Login />;
  return (
      <BrowserRouter>
        <div className="flex min-h-screen bg-gray-50">
          <aside className="w-56 bg-white border-r border-gray-200 flex flex-col">
            <div className="px-5 py-5 border-b border-gray-100">
              <h1 className="text-lg font-bold text-blue-600">🔐 UnsubVault</h1>
              <p className="text-xs text-gray-400 mt-0.5">Email Unsubscribe Manager</p>
            </div>
            <nav className="flex-1 py-4 px-2 space-y-1">
              {NAV.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) =>
                  clsx("flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    isActive ? "bg-blue-50 text-blue-700" : "text-gray-600 hover:bg-gray-100")}>
                  <Icon size={17} />{label}
                </NavLink>
              ))}
            </nav>
            <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400 space-y-2">
              <button onClick={async () => { await logout(); client.invalidateQueries({ queryKey: ["session"] }); }}
                className="flex items-center gap-2 text-gray-500 hover:text-gray-800"><LogOut size={14} />Sign out</button>
              <div>UnsubVault v0.1.0 · MIT</div>
            </div>
          </aside>
          <main className="flex-1 p-8 max-w-5xl">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/accounts" element={<Accounts />} />
              <Route path="/scan" element={<Scan />} />
              <Route path="/emails" element={<Emails />} />
              <Route path="/unsubscribe" element={<Unsubscribe />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/guides" element={<Guides />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
  );
}

export default function App() {
  return <QueryClientProvider client={qc}><Shell /></QueryClientProvider>;
}
