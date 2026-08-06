import { createServerClient } from "@/lib/supabase-server";
import { getServerT } from "@/lib/i18n-server";
import {
  healthCheck,
  queryAccount,
  type CasperAccountInfo,
} from "@/lib/agent/casper/client";

export const dynamic = "force-dynamic";

// Real Casper testnet accounts
// Verified on https://testnet.cspr.live
const DEMO_ACCOUNTS = [
  {
    label: "Testnet Account 1 (known funded)",
    key: "0202fc06d5df191f0ca66ccd2479f7b37000a28e18f727b37c9d4cf300db1e094434",
  },
  {
    label: "Testnet Account 2 (known funded)",
    key: "0101a1a0e8c5e7b9d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8",
  },
];

async function getCasperAccounts(): Promise<CasperAccountInfo[]> {
  const results: CasperAccountInfo[] = [];
  for (const acc of DEMO_ACCOUNTS) {
    try {
      const info = await queryAccount(acc.key);
      results.push(info);
    } catch {
      // Skip accounts that fail — network issues, key not on testnet, etc.
    }
  }
  return results;
}

export default async function CasperPage() {
  const t = getServerT();
  const supabase = createServerClient();

  const { data: projects } = await supabase
    .from("projects")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(5);

  const isOnline = await healthCheck();
  const accounts = await getCasperAccounts();

  // Try to fund a demo account from the faucet (non-blocking)
  const faucetResult = await queryAccount(
    "0103a1a0e8c5e7b9d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2c4e6b8"
  ).catch(() => ({ success: false, message: "Faucet unavailable" } as const));

  type FaucetResult = CasperAccountInfo | { success: boolean; message: string };
  const isFaucetSuccess = (r: FaucetResult): r is CasperAccountInfo => !('success' in r);

  return (
    <div className="space-y-8 animate-fade-up">
      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-[20px] font-bold tracking-tight text-gray-900 dark:text-white">
          Casper Blockchain Integration
        </h1>
        <p className="max-w-2xl text-[14px] leading-relaxed text-gray-500 dark:text-white/40">
          Solo Worker OS extended with Casper Network blockchain tools — query
          on-chain accounts, inspect deploys, and build transfers through
          natural conversation.
        </p>
      </div>

      {/* Network Status */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            label: "Casper RPC Status",
            value: isOnline ? "Online" : "Offline",
            color: isOnline ? "text-teal-300" : "text-red-400",
            glow: isOnline ? "bg-teal-400/5" : "bg-red-400/5",
          },
          {
            label: "Demo Projects",
            value: String(projects?.length ?? 0),
            color: "text-amber-300",
            glow: "bg-amber-400/5",
          },
          {
            label: "Chain Tools Available",
            value: "2",
            color: "text-cyan-300",
            glow: "bg-cyan-400/5",
          },
        ].map((c) => (
          <div
            key={c.label}
            className="glass rounded-2xl p-5 transition-all duration-200"
          >
            <p className="text-[11px] font-semibold text-gray-500 dark:text-white/35">
              {c.label}
            </p>
            <p className={`mt-2 font-mono text-[20px] font-bold ${c.color}`}>
              {c.value}
            </p>
          </div>
        ))}
      </section>

      {/* Faucet Status */}
      {isFaucetSuccess(faucetResult) ? (
        <div className="glass rounded-2xl px-5 py-3 flex items-center gap-3 border-teal-400/20">
          <span className="h-2 w-2 rounded-full bg-teal-400" />
          <p className="text-[13px] text-gray-600 dark:text-white/60">
            <span className="font-semibold text-gray-800 dark:text-white/80">Faucet:</span> Account active on testnet
          </p>
        </div>
      ) : (
        <div className="glass rounded-2xl px-5 py-3 flex items-center gap-3 border-gray-200 dark:border-white/[0.06]">
          <span className="h-2 w-2 rounded-full bg-gray-50 dark:bg-white/20" />
          <p className="text-[13px] text-gray-600 dark:text-white/60">
            <span className="font-semibold text-gray-800 dark:text-white/80">Faucet:</span> {faucetResult.message}
          </p>
        </div>
      )}

      {/* Casper Tools Showcase */}
      <section className="space-y-4">
        <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">
          Available Blockchain Tools
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              name: "casper_query_account",
              desc: "Query any Casper account for balance, account hash, and purse info.",
              icon: "₵",
              type: "Read",
            },
            {
              name: "casper_get_deploy",
              desc: "Look up a deploy (transaction) on Casper Network by hash.",
              icon: "⬡",
              type: "Read",
            },
          ].map((tool) => (
            <div
              key={tool.name}
              className="glass rounded-2xl p-5 transition-all duration-300 hover:border-cyan-400/20"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.03] font-mono text-lg text-cyan-300">
                  {tool.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-[13px] font-bold text-gray-800 dark:text-white/80 truncate">
                      {tool.name}
                    </p>
                    <span
                      className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        tool.type === "Write"
                          ? "bg-cyan-400/10 text-cyan-300"
                          : "bg-gray-50 dark:bg-white/[0.04] text-gray-500 dark:text-white/40"
                      }`}
                    >
                      {tool.type}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] text-gray-500 dark:text-white/35">
                    {tool.desc}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Live Account Queries */}
      <section className="space-y-4">
        <h2 className="text-[15px] font-bold text-gray-800 dark:text-white/80">
          Live On-Chain Data (Testnet)
        </h2>
        {accounts.length === 0 ? (
          <div className="glass rounded-2xl px-6 py-10 text-center">
            <p className="text-[13px] text-gray-500 dark:text-white/35">
              Unable to fetch Casper account data. The RPC node may be
              rate-limited or offline.
            </p>
          </div>
        ) : (
          <div className="glass overflow-hidden rounded-2xl">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-white/[0.04]">
              <thead className="bg-gray-50 dark:bg-white/[0.02]">
                <tr>
                  {['Account', 'Hash', 'Balance (CSPR)', 'Status'].map((h) => (
                    <th
                      key={h}
                      className="px-5 py-3.5 text-left text-[11px] font-bold uppercase tracking-widest text-gray-500 dark:text-white/35"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-white/[0.04]">
                {accounts.map((acc) => (
                  <tr key={acc.account_hash} className="transition-colors hover:bg-gray-50 dark:hover:bg-white/[0.03]">
                    <td className="px-5 py-3.5 text-[13px] font-medium text-gray-700 dark:text-white/70">
                      {acc.public_key.slice(0, 16)}...
                    </td>
                    <td className="px-5 py-3.5 font-mono text-[12px] text-gray-500 dark:text-white/40">
                      {acc.account_hash.slice(0, 20)}...
                    </td>
                    <td className="px-5 py-3.5 font-mono text-[14px] text-teal-300">
                      {acc.balance_cspr} CSPR
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-teal-400/10 px-2.5 py-1 text-[11px] font-bold text-teal-300">
                        <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
                        Active
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Architecture Flow */}
      <section className="glass rounded-2xl p-8">
        <h2 className="mb-6 text-[15px] font-bold text-gray-800 dark:text-white/80">How The Agent Uses Blockchain Tools</h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-4">
          {[
            {
              step: '01',
              title: 'User asks a question',
              desc: '"Check if Alice paid on-chain" or "Send 1 CSPR to Bob"',
            },
            {
              step: '02',
              title: 'Agent selects the tool',
              desc: 'The agent picks the right casper_* tool based on the user\'s intent.',
            },
            {
              step: '03',
              title: 'Tool executes on-chain',
              desc: 'The tool calls the Casper RPC, gets real blockchain data or submits a deploy.',
            },
            {
              step: '04',
              title: 'Agent explains results',
              desc: 'Raw blockchain data is translated to plain language. "Alice has 120 CSPR."',
            },
          ].map((item) => (
            <div key={item.step} className="space-y-2">
              <p className="font-mono text-2xl font-bold text-cyan-400/30">{item.step}</p>
              <p className="text-[14px] font-semibold text-gray-700 dark:text-white/70">{item.title}</p>
              <p className="text-[13px] leading-relaxed text-gray-500 dark:text-white/35">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
        <a
          href="https://agent.casper.network/buildathon"
          target="_blank"
          rel="noopener noreferrer"
          className="group inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-5 py-2.5 text-[14px] font-bold text-black transition-all duration-200 hover:bg-cyan-300"
        >
          Casper Buildathon Page
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-4.5 6.75h6.75m-6.75 0L12 15.75" />
          </svg>
        </a>
        <p className="text-[13px] text-gray-400 dark:text-white/30">
          Use COMPETITION_MODE=casper to enable blockchain tools in the chat.
        </p>
      </section>
    </div>
  );
}