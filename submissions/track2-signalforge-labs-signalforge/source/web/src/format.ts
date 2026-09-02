export function displayCompany(value: string) {
  const normalized = value.trim().toLowerCase();
  const names: Record<string, string> = { microsoft: "Microsoft", msft: "Microsoft", nvidia: "NVIDIA", nvda: "NVIDIA" };
  return names[normalized] ?? value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function displayCaseTitle(value: string) {
  return value
    .replace(/microsoft/gi, "Microsoft")
    .replace(/nvidia/gi, "NVIDIA")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}
