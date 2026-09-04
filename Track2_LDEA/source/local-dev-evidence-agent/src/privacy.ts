export interface PrivacyRisk {
  kind:
    | "email"
    | "api_key"
    | "bearer_token"
    | "private_key"
    | "aws_key"
    | "env_secret_name"
    | "connection_string";
  count: number;
  samples: string[];
  paths?: string[];
}

const PATTERNS: Array<{ kind: PrivacyRisk["kind"]; re: RegExp; redact: (m: string) => string }> = [
  {
    kind: "email",
    re: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi,
    redact: (m) => {
      const [u, d] = m.split("@");
      return `${(u ?? "").slice(0, 1)}***@${d ?? "?"}`;
    },
  },
  {
    kind: "api_key",
    re: /\b(?:sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9\-_]{20,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b/g,
    redact: (m) => `${m.slice(0, 6)}…${m.slice(-4)}`,
  },
  {
    kind: "bearer_token",
    re: /\bBearer\s+[A-Za-z0-9\-._~+/]+=*/gi,
    redact: () => "Bearer ***",
  },
  {
    kind: "private_key",
    re: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g,
    redact: () => "-----BEGIN PRIVATE KEY----- ***",
  },
  {
    kind: "aws_key",
    re: /\bAKIA[0-9A-Z]{16}\b/g,
    redact: (m) => `${m.slice(0, 4)}…${m.slice(-4)}`,
  },
  {
    kind: "env_secret_name",
    re: /\b(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?TOKEN|AUTH[_-]?TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|AWS_SECRET_ACCESS_KEY)\b/g,
    redact: (m) => m,
  },
  {
    kind: "connection_string",
    re: /\b(?:postgres|mysql|mongodb|redis):\/\/[^\s'"]+/gi,
    redact: (m) => m.replace(/:\/\/([^:\/@]+):([^@\/]+)@/, "://$1:***@"),
  },
];

export function scanText(text: string, path?: string): PrivacyRisk[] {
  const bucket = new Map<string, PrivacyRisk>();
  for (const p of PATTERNS) {
    const samples: string[] = [];
    let count = 0;
    text.replace(p.re, (m) => {
      count += 1;
      if (samples.length < 3) samples.push(p.redact(m));
      return m;
    });
    if (count > 0) {
      const key = p.kind;
      const prev = bucket.get(key);
      if (prev) {
        prev.count += count;
        for (const s of samples) {
          if (prev.samples.length < 5 && !prev.samples.includes(s)) prev.samples.push(s);
        }
        if (path) {
          prev.paths = [...new Set([...(prev.paths ?? []), path])];
        }
      } else {
        bucket.set(key, {
          kind: p.kind,
          count,
          samples,
          ...(path ? { paths: [path] } : {}),
        });
      }
    }
  }
  return [...bucket.values()].sort((a, b) => b.count - a.count);
}

export function scanMany(files: Array<{ path: string; content: string }>): PrivacyRisk[] {
  const merged = new Map<string, PrivacyRisk>();
  for (const f of files) {
    for (const risk of scanText(f.content, f.path)) {
      const prev = merged.get(risk.kind);
      if (!prev) {
        merged.set(risk.kind, risk);
        continue;
      }
      prev.count += risk.count;
      for (const s of risk.samples) {
        if (prev.samples.length < 5 && !prev.samples.includes(s)) prev.samples.push(s);
      }
      prev.paths = [...new Set([...(prev.paths ?? []), ...(risk.paths ?? [])])];
    }
  }
  return [...merged.values()].sort((a, b) => b.count - a.count);
}

export function redactText(text: string): string {
  let out = text;
  for (const p of PATTERNS) {
    out = out.replace(p.re, (m) => p.redact(m));
  }
  return out;
}
