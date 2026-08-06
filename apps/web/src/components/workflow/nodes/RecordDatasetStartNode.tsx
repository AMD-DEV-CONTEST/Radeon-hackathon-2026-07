import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function RecordDatasetStartNode({ data, selected }: Props) {
  const leaderPort = (data.config.leaderPort as string) || '/dev/ttyACM0';
  const followerPort = (data.config.followerPort as string) || '/dev/ttyACM1';
  const taskName = (data.config.taskName as string) || '';
  const episodes = (data.config.episodes as number) || 1;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Task:</span>
          <span className="font-medium text-foreground truncate max-w-[120px]">
            {taskName || 'Not set'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Episodes:</span>
          <span className="font-medium text-foreground">{episodes}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span>Leader:</span>
          <span className="font-medium text-foreground text-[10px] font-mono">{leaderPort}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span>Follower:</span>
          <span className="font-medium text-foreground text-[10px] font-mono">{followerPort}</span>
        </div>
      </div>
    </BaseNode>
  );
}
