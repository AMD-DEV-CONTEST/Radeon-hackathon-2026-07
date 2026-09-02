// ============================================================================
// RBAC — role-based access control for menu/button/data level
// ============================================================================

export type Role = "admin" | "operator" | "agent" | "viewer";

export interface PermissionSet {
  menus: string[];
  actions: string[];
  dataScope: "all" | "team" | "self";
}

const ROLE_PERMISSIONS: Record<Role, PermissionSet> = {
  admin: {
    menus: ["overview", "bot-config", "chat-monitor", "knowledge-base", "campaign-sync", "inquiry-loss", "diagnosis", "satisfaction", "reports", "qa", "audit", "admin", "compliance", "intent-accuracy", "work-orders", "effect-compare", "payment-reminders", "agent-assist", "agent-performance", "llm-metrics", "platforms", "shadow-approval", "quality-monitor", "prompts", "model-configs", "cost-savings", "unresolved", "release-evidence"],
    actions: ["create", "read", "update", "delete", "overturn", "dispatch", "export", "manage_roles"],
    dataScope: "all",
  },
  operator: {
    menus: ["bot-config", "chat-monitor", "knowledge-base", "campaign-sync", "inquiry-loss", "diagnosis", "satisfaction", "reports", "qa", "audit", "compliance", "intent-accuracy", "work-orders", "effect-compare", "payment-reminders", "agent-assist", "agent-performance", "llm-metrics", "platforms", "shadow-approval", "quality-monitor", "prompts", "unresolved"],
    actions: ["create", "read", "update", "overturn", "dispatch", "export"],
    dataScope: "team",
  },
  agent: {
    menus: ["chat-monitor", "knowledge-base", "qa"],
    actions: ["read", "update"],
    dataScope: "self",
  },
  viewer: {
    menus: ["chat-monitor", "reports", "qa"],
    actions: ["read"],
    dataScope: "team",
  },
};

export function getPermissions(role: Role): PermissionSet {
  return ROLE_PERMISSIONS[role] || ROLE_PERMISSIONS.viewer;
}

export function canAccessMenu(role: Role, menuId: string): boolean {
  const perms = getPermissions(role);
  return perms.menus.includes(menuId);
}

export function canPerformAction(role: Role, action: string): boolean {
  const perms = getPermissions(role);
  return perms.actions.includes(action);
}

export function getRoleLabel(role: Role): string {
  const labels: Record<Role, string> = {
    admin: "超级管理员",
    operator: "运营",
    agent: "客服",
    viewer: "只读",
  };
  return labels[role] || role;
}

export const ALL_ROLES: Role[] = ["admin", "operator", "agent", "viewer"];
