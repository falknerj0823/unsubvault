import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { login } from "../lib/api";

export default function Login() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const m = useMutation({
    mutationFn: () => login(password),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session"] }),
  });
  const error = m.error as { response?: { data?: { detail?: string } } } | null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={e => { e.preventDefault(); m.mutate(); }}
        className="w-80 bg-white border border-gray-200 rounded-xl p-6 space-y-4 shadow-sm">
        <div>
          <h1 className="text-lg font-bold text-blue-600">🔐 UnsubVault</h1>
          <p className="text-xs text-gray-400 mt-0.5">Enter the admin password</p>
        </div>
        <input type="password" autoFocus value={password} onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        {m.isError && <p className="text-sm text-red-600">{error?.response?.data?.detail ?? "Login failed"}</p>}
        <button type="submit" disabled={!password || m.isPending}
          className="w-full bg-blue-600 text-white rounded-lg py-2 text-sm font-medium disabled:opacity-50">
          {m.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
