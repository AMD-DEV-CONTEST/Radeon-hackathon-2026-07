import { Brain } from "lucide-react";

export function HeroVisual() {
  return (
    <div className="relative mx-auto mt-14 max-w-5xl px-4 sm:px-6">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-8 -inset-y-6 rounded-[40px] bg-primary/25 blur-3xl"
      />
      <div className="relative overflow-hidden rounded-3xl border border-border/70 bg-card shadow-2xl shadow-primary/15">
        <div className="flex items-center gap-2 border-b border-border/60 bg-[#0c0c12] px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
          <span className="ml-3 text-xs text-muted-foreground">
            AgentVox · Live Interview Session
          </span>
        </div>
        <div className="aspect-[16/10] bg-gradient-to-br from-[#111827] via-[#0d0d14] to-[#09090b] p-4 sm:p-8">
          <div className="flex h-full flex-col justify-between rounded-2xl border border-border/50 bg-[#09090B]/85 p-5 sm:p-8">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/20">
                <Brain className="h-5 w-5 text-primary" aria-hidden="true" />
              </div>
              <div>
                <p className="text-sm font-medium text-white">
                  Hi, I&apos;m{" "}
                  <span className="text-primary">Vox-1</span>. How can I help
                  you today?
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Multi-agent interview panel · latency 124ms
                </p>
              </div>
            </div>

            <div className="mt-6 space-y-3">
              <div className="rounded-xl border border-border bg-[#111827] px-4 py-3">
                <p className="text-sm text-muted-foreground">
                  Ask me anything about system design, algorithms, or
                  architecture...
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {["System Design", "Distributed Systems", "Leadership"].map(
                  (chip) => (
                    <span
                      key={chip}
                      className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs text-primary"
                    >
                      {chip}
                    </span>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
