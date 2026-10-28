import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { marked } from "marked";
import { getAuthInfo } from "../lib/api";
import microsoft from "../guides/microsoft-oauth.md?raw";
import imap from "../guides/gmail-and-imap.md?raw";
import llm from "../guides/llm-providers.md?raw";

export const GUIDES = [
  { id: "microsoft", title: "Outlook / Hotmail / Microsoft 365", body: microsoft },
  { id: "imap", title: "Gmail, iCloud, Yahoo, other IMAP", body: imap },
  { id: "llm", title: "Choosing and connecting an LLM", body: llm },
];

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export default function Guides({ initial = "microsoft" }: { initial?: string }) {
  const [id, setId] = useState(GUIDES.some(g => g.id === initial) ? initial : "microsoft");
  const { data } = useQuery({ queryKey: ["auth-info"], queryFn: getAuthInfo });
  const guide = GUIDES.find(g => g.id === id)!;
  // Guides are bundled static text; the only injected value (the redirect URI) is escaped.
  const html = marked.parse(guide.body.replace(/\{\{REDIRECT_URI\}\}/g, esc(data?.redirect_uri ?? "http://localhost:3000/api/auth/microsoft/callback")), { async: false }) as string;
  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-4">Setup guides</h2>
      <div className="flex flex-wrap gap-2 mb-6">
        {GUIDES.map(g => (
          <button key={g.id} onClick={() => setId(g.id)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border ${g.id === id ? "bg-blue-50 border-blue-200 text-blue-700" : "border-gray-200 text-gray-600 hover:bg-gray-100"}`}>
            {g.title}</button>
        ))}
      </div>
      <article className="guide bg-white border border-gray-200 rounded-xl p-6" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
