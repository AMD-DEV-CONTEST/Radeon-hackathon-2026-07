import { buildQuery, get, post } from "./client.js";

export const getBackupStats = () => get("/backup/stats");
export const listBackups = () => get("/backup/list");
export const createBackup = (description = "") => post(`/backup/create${buildQuery({ description })}`, {});
export const restoreBackup = (backupName) => post(`/backup/restore/${encodeURIComponent(backupName)}`, {});
export const getAutoBackup = () => get("/backup/auto-backup");
export const setAutoBackup = (enabled) => post(`/backup/auto-backup${buildQuery({ enabled })}`, {});
