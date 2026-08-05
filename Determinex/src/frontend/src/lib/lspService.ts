import { invokeSafe } from "./api";

export interface LspDiagnostic {
  line: number;
  column: number;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface LspSymbol {
  name: string;
  kind: "class" | "method" | "function" | "variable";
  line: number;
}

export async function getLspDiagnostics(
  fileName: string,
  workspacePath?: string
): Promise<LspDiagnostic[]> {
  try {
    const res = await invokeSafe<LspDiagnostic[]>("get_lsp_diagnostics", {
      fileName,
      workspacePath: workspacePath || undefined,
    });
    return res || [];
  } catch {
    return [];
  }
}

export async function getLspSymbols(fileName: string): Promise<LspSymbol[]> {
  try {
    const res = await invokeSafe<LspSymbol[]>("get_lsp_symbols", { fileName });
    return res || [];
  } catch {
    return [];
  }
}
