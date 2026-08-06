import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function PublishSkillNode({ data, selected }: Props) {
  const skillName = (data.config.skillName as string) || '';
  const verb = (data.config.verb as string) || 'manipulate';
  const version = (data.config.version as string) || '1.0.0';

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Skill:</span>
          <span className="font-medium text-foreground truncate max-w-[140px]">
            {skillName || 'Not set'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Verb:</span>
          <span className="font-medium text-foreground">{verb}</span>
        </div>
        <div className="flex justify-between">
          <span>Version:</span>
          <span className="font-medium text-foreground">v{version}</span>
        </div>
        {data.status === 'success' && data.config._manifest && (
          <div className="mt-1 p-1.5 rounded bg-primary/10 text-primary text-[10px] font-mono break-all">
            {(data.config._manifest as Record<string, unknown>).skill_id as string}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
