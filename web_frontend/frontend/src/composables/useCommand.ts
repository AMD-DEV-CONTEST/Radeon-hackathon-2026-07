import { useAgentPackageCommands } from './commands/useAgentPackageCommands'
import { useExtensionCommands } from './commands/useExtensionCommands'
import { useKnowledgeCommands } from './commands/useKnowledgeCommands'
import { useRuntimeCommands } from './commands/useRuntimeCommands'
import { useSchedulerCommands } from './commands/useSchedulerCommands'
import { useWorkspaceCommands } from './commands/useWorkspaceCommands'

export function useCommand() {
  return {
    ...useRuntimeCommands(),
    ...useAgentPackageCommands(),
    ...useWorkspaceCommands(),
    ...useKnowledgeCommands(),
    ...useExtensionCommands(),
    ...useSchedulerCommands(),
  }
}
