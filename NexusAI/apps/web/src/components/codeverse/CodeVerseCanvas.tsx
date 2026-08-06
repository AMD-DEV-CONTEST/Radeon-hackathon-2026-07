"use client";

import { useState } from "react";

const files = [
  {
    path: "src/api/users.ts",
    code: `export async function getUsers() {
  return db.user.findMany();
}`,
  },
  {
    path: "src/services/auth.ts",
    code: `export class AuthService {
  login() {}
  logout() {}
}`,
  },
  {
    path: "src/models/user.ts",
    code: `export interface User {
  id: string;
  name: string;
}`,
  },
  {
    path: "src/utils/logger.ts",
    code: `export function logger(message:string){
  console.log(message);
}`,
  },
];

export default function CodeVerseCanvas() {
  const [selected, setSelected] = useState(files[0]);
  const [search, setSearch] = useState("");

  const filtered = files.filter((f) =>
    f.path.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <main className="min-h-screen bg-gradient-to-br from-black via-[#070b14] to-black text-white">
      <div className="mx-auto max-w-7xl p-8">
        <div className="rounded-xl border border-white/10 bg-black/40 p-6 backdrop-blur">
          <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">
            NEXUSAI · CODEVERSE
          </p>

          <h1 className="mt-2 text-5xl font-bold">Explore your code.</h1>

          <p className="mt-3 text-white/60">
            Browse repositories as interactive software worlds.
          </p>
        </div>

        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search files..."
          className="mt-6 w-full rounded-lg border border-white/10 bg-black/50 px-4 py-3 outline-none"
        />

        <div className="mt-6 grid grid-cols-4 gap-4">
          {[
            ["Files", "128"],
            ["Classes", "42"],
            ["Functions", "310"],
            ["Dependencies", "182"],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-xl border border-white/10 bg-black/40 p-5"
            >
              <div className="text-3xl font-bold text-cyan-300">{value}</div>

              <div className="mt-2 text-sm text-white/60">{label}</div>
            </div>
          ))}
        </div>

        <div className="mt-6 grid grid-cols-12 gap-4">
          <div className="col-span-3 rounded-xl border border-white/10 bg-black/40 p-4">
            <h2 className="mb-4 font-semibold">Repository</h2>

            {filtered.map((file) => (
              <button
                key={file.path}
                onClick={() => setSelected(file)}
                className={`mb-2 block w-full rounded-lg border px-3 py-2 text-left transition ${
                  selected.path === file.path
                    ? "border-cyan-400 bg-cyan-950"
                    : "border-white/10 hover:bg-white/5"
                }`}
              >
                📄 {file.path}
              </button>
            ))}
          </div>

          <div className="col-span-5 rounded-xl border border-white/10 bg-black/40 p-4">
            <h2 className="mb-4 font-semibold">Dependency Graph</h2>

            <pre className="text-cyan-300 text-sm">
              {`
       App
        │
        ▼
   UserController
        │
        ▼
    UserService
      /     \\
     ▼       ▼
 Database  Logger
`}
            </pre>

            <p className="mt-6 text-sm text-white/50">
              Interactive graph coming next.
            </p>
          </div>

          <div className="col-span-4 rounded-xl border border-white/10 bg-black/40 p-4">
            <h2 className="mb-4 font-semibold">{selected.path}</h2>

            <pre className="overflow-auto rounded-lg bg-black/70 p-4 text-sm text-green-300">
              {selected.code}
            </pre>
          </div>
        </div>
      </div>
    </main>
  );
}
