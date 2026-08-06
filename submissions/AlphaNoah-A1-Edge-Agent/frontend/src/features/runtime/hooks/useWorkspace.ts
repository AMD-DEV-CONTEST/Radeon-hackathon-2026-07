import type { WorkspaceResource } from "../models";
import { useWorkspaceContext } from "./WorkspaceProviderContext";

export function useWorkspace(): WorkspaceResource {
  return useWorkspaceContext();
}
