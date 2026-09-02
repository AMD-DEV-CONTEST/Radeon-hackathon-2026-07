export type ProjectRole = 'admin' | 'pm' | 'member' | 'guest'

export const PROJECT_ROLE_LABELS: Record<ProjectRole, string> = {
  admin: '项目管理员',
  pm: '项目经理',
  member: '项目成员',
  guest: '只读访客',
}

export function canWriteProject(role: ProjectRole | null): boolean {
  return role === 'admin' || role === 'pm' || role === 'member'
}

export function canManageProjectRisks(role: ProjectRole | null): boolean {
  return role === 'admin' || role === 'pm'
}

export function roleCapabilitySummary(role: ProjectRole): string {
  switch (role) {
    case 'admin':
      return '可管理项目成员与角色，并处理任务、报告和风险。'
    case 'pm':
      return '可维护资料与任务、生成报告，并处理风险和报告审批。'
    case 'member':
      return '可维护资料和任务、生成报告及发表评论；风险处理和成员管理由项目经理或管理员负责。'
    case 'guest':
      return '只读模式：可查看项目数据、报告、证据和审计记录，不能修改项目内容。'
  }
}
