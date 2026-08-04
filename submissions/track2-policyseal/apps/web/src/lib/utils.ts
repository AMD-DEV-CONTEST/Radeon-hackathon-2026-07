import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { Action, RevisionStatus } from "./types";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function shortId(value: string): string {
  const tail = value.split("-").at(-1) ?? value;
  return tail.slice(0, 8).toUpperCase();
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function statusTone(
  status: RevisionStatus,
): "neutral" | "success" | "warning" | "danger" {
  if (status === "exportable" || status === "approved") return "success";
  if (status === "awaiting_approval" || status === "awaiting_confirmation") return "warning";
  if (status === "blocked" || status === "rejected" || status === "processing_failed") {
    return "danger";
  }
  return "neutral";
}

export function actionTone(
  action: Action,
): "neutral" | "success" | "warning" | "danger" | "info" {
  if (action === "keep") return "success";
  if (action === "mask" || action === "generalize" || action === "filter") return "info";
  if (action === "require_approval") return "warning";
  if (action === "block") return "danger";
  return "neutral";
}
