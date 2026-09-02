import { get } from "./client.js";

export const getLogs = (params = {}) => get("/logs", params, { timeoutMs: 10_000 });
export const getLogStats = () => get("/logs/stats", {}, { timeoutMs: 10_000 });
