import { useEffect, useMemo, useState } from 'react';
import { useWorkflowStore } from '../../store/workflowStore';
import { X, Plus, Trash2, AlertCircle } from 'lucide-react';
import type { CameraMapEntry, WorkflowNodeData } from '../../types/workflow';
import {
  SUPPORTED_VLA_TYPES,
  SUPPORTED_INSTANCE_TYPES,
  validateNode,
} from '../../lib/workflowValidation';
import {
  listRuntimesWithSkills,
  listSkills,
  type RuntimeWithSkills,
  type Skill,
} from '../../lib/skillsApi';

interface PropertiesPanelProps {
  selectedNode: string | null;
}

export function PropertiesPanel({ selectedNode }: PropertiesPanelProps) {
  const { nodes, updateNodeData, setSelectedNode } = useWorkflowStore();

  const node = selectedNode ? nodes.find((n) => n.id === selectedNode) : null;

  const validationErrors = useMemo(
    () => (node ? validateNode(node) : []),
    [node]
  );

  if (!node) {
    return (
      <div className="w-72 border-l bg-card flex flex-col">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-sm">Properties</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-4 text-center">
          <div className="text-muted-foreground">
            <p className="text-sm">Select a node to edit properties</p>
          </div>
        </div>
      </div>
    );
  }

  const { data } = node;

  const handleConfigChange = (key: string, value: any) => {
    updateNodeData(node.id, {
      config: { ...data.config, [key]: value },
    });
  };

  return (
    <div className="w-72 border-l bg-card flex flex-col">
      <div className="p-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">{data.icon}</span>
          <h2 className="font-semibold text-sm">{data.label}</h2>
        </div>
        <button
          onClick={() => setSelectedNode(null)}
          className="p-1 rounded hover:bg-muted transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Status */}
        <div className="p-3 rounded-lg bg-muted">
          <div className="text-xs text-muted-foreground mb-1">Status</div>
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                data.status === 'idle'
                  ? 'bg-gray-400'
                  : data.status === 'running'
                  ? 'bg-yellow-500 animate-pulse'
                  : data.status === 'success'
                  ? 'bg-green-500'
                  : data.status === 'api_pending'
                  ? 'bg-orange-400'
                  : 'bg-red-500'
              }`}
            />
            <span className="text-sm capitalize">{data.status === 'api_pending' ? 'API Pending' : data.status}</span>
          </div>
        </div>

        {/* Validation Errors */}
        {validationErrors.length > 0 && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <div className="flex items-center gap-1.5 text-xs font-medium text-red-500 mb-1.5">
              <AlertCircle className="w-3.5 h-3.5" />
              <span>Validation</span>
            </div>
            <ul className="text-xs text-red-400 space-y-1 list-disc list-inside">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Configuration */}
        <div>
          <h3 className="text-sm font-medium mb-3">Configuration</h3>

          {/* Qualia Studio nodes */}
          {data.type === 'hf_dataset' && (
            <DatasetLoadForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'ego_dataset' && (
            <EgoDatasetForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'camera_noise' && (
            <CameraNoiseForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'trajectory_noise' && (
            <TrajectoryNoiseForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'output_dataset' && (
            <OutputDatasetForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'merge_datasets' && (
            <MergeDatasetsForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'qualia_finetune' && (
            <QualiaFinetuneForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'reward_model_tuning' && (
            <RewardModelForm data={data} onChange={handleConfigChange} />
          )}
          {(data.type === 'world_model_generator' || data.type === 'depth_estimator' ||
            data.type === 'pose_action_extractor' || data.type === 'urdf_inpaint' ||
            data.type === 'idm_inverse_dynamics') && (
            <ApiPendingForm data={data} />
          )}

          {/* Legacy / existing nodes */}
          {data.type === 'dataset_load' && (
            <DatasetLoadForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'camera_map' && (
            <CameraMapForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'finetune_job' && (
            <FinetuneJobForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'job_monitor' && (
            <JobMonitorForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'skill_invoke' && (
            <SkillInvokeForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'robot_connect' && (
            <LegacyRobotForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'record' && (
            <LegacyRecordForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'train' && (
            <LegacyTrainForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'evaluate' && (
            <EvaluateForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'publish_skill' && (
            <PublishSkillForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'record_dataset_start' && (
            <RecordDatasetStartForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'recording_monitor' && (
            <JobMonitorForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'reachy_record_move' && (
            <ReachyRecordMoveForm data={data} onChange={handleConfigChange} />
          )}
          {data.type === 'deploy' && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Deploy configuration is automatically set from connected model and robot.
              </p>
            </div>
          )}
        </div>

        {/* Description */}
        <div className="pt-4 border-t">
          <h3 className="text-sm font-medium mb-2">Description</h3>
          <p className="text-xs text-muted-foreground">{data.description}</p>
        </div>

        {/* Delete Button */}
        <div className="pt-4">
          <button
            onClick={() => {
              useWorkflowStore.getState().removeNode(node.id);
            }}
            className="w-full py-2 px-4 rounded-md bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors text-sm"
          >
            Delete Node
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- Form field helpers ----------
const labelCls = 'text-xs text-muted-foreground block mb-1';
const inputCls =
  'w-full px-3 py-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary';

interface FormProps {
  data: WorkflowNodeData;
  onChange: (key: string, value: any) => void;
}

// ---------- Qualia Studio forms ----------

function EgoDatasetForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Video Source</label>
        <input
          type="text"
          value={(data.config.source as string) || ''}
          onChange={(e) => onChange('source', e.target.value)}
          placeholder="HF repo or local path"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Prompt / Description</label>
        <textarea
          value={(data.config.prompt as string) || ''}
          onChange={(e) => onChange('prompt', e.target.value)}
          placeholder="Scene description for generative pipeline..."
          rows={2}
          className={inputCls}
        />
      </div>
    </div>
  );
}

function CameraNoiseForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Transforms</label>
        <input
          type="text"
          value={(data.config.transforms as string) || 'lighting,noise'}
          onChange={(e) => onChange('transforms', e.target.value)}
          placeholder="lighting,noise,blur,occlusion"
          className={inputCls}
        />
        <p className="text-[10px] text-muted-foreground mt-1">Comma-separated: lighting, noise, blur, occlusion</p>
      </div>
      <div>
        <label className={labelCls}>Mode</label>
        <select
          value={(data.config.mode as string) || 'stacked'}
          onChange={(e) => onChange('mode', e.target.value)}
          className={inputCls}
        >
          <option value="stacked">Stacked (all transforms together)</option>
          <option value="independent">Independent (each separate)</option>
        </select>
      </div>
      <div>
        <label className={labelCls}>Copies: {(data.config.copies as number) ?? 3}</label>
        <input
          type="range" min={1} max={20}
          value={(data.config.copies as number) ?? 3}
          onChange={(e) => onChange('copies', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>Dataset Mode</label>
        <select
          value={(data.config.datasetMode as string) || 'copy'}
          onChange={(e) => onChange('datasetMode', e.target.value)}
          className={inputCls}
        >
          <option value="copy">Copy (new dataset)</option>
          <option value="inplace">In-place</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={labelCls}>Brightness min</label>
          <input type="number" value={(data.config.brightnessMin as number) ?? -15}
            onChange={(e) => onChange('brightnessMin', Number(e.target.value))} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Brightness max</label>
          <input type="number" value={(data.config.brightnessMax as number) ?? 15}
            onChange={(e) => onChange('brightnessMax', Number(e.target.value))} className={inputCls} />
        </div>
      </div>
    </div>
  );
}

function TrajectoryNoiseForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Strength: {(data.config.strength as number) ?? 0.1}</label>
        <input
          type="range" min={0.01} max={1.0} step={0.01}
          value={(data.config.strength as number) ?? 0.1}
          onChange={(e) => onChange('strength', parseFloat(e.target.value))}
          className="w-full"
        />
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={Boolean(data.config.jointNoise)}
          onChange={(e) => onChange('jointNoise', e.target.checked)} />
        <span>Joint angle noise</span>
      </label>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={Boolean(data.config.timestampJitter)}
          onChange={(e) => onChange('timestampJitter', e.target.checked)} />
        <span>Timestamp jitter</span>
      </label>
    </div>
  );
}

function OutputDatasetForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Output Name</label>
        <input
          type="text"
          value={(data.config.outputName as string) || ''}
          onChange={(e) => onChange('outputName', e.target.value)}
          placeholder="augmented_dataset_v1"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Mode</label>
        <select
          value={(data.config.datasetMode as string) || 'copy'}
          onChange={(e) => onChange('datasetMode', e.target.value)}
          className={inputCls}
        >
          <option value="copy">Copy</option>
          <option value="inplace">In-place</option>
        </select>
      </div>
    </div>
  );
}

function MergeDatasetsForm({ data }: FormProps) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Connect multiple Output Dataset nodes to the inputs. The merge combines all connected datasets for downstream training.
      </p>
    </div>
  );
}

function QualiaFinetuneForm({ data, onChange }: FormProps) {
  const mappings: CameraMapEntry[] = (data.config.cameraMappings as CameraMapEntry[]) || [];

  const updateMapping = (idx: number, patch: Partial<CameraMapEntry>) => {
    const next = mappings.map((m, i) => (i === idx ? { ...m, ...patch } : m));
    onChange('cameraMappings', next);
  };
  const addMapping = () => {
    onChange('cameraMappings', [...mappings, { slot: `cam_${mappings.length + 1}`, imageKey: '' }]);
  };
  const removeMapping = (idx: number) => {
    onChange('cameraMappings', mappings.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>VLA Type *</label>
        <select
          value={(data.config.vlaType as string) || 'act'}
          onChange={(e) => onChange('vlaType', e.target.value)}
          className={inputCls}
        >
          {SUPPORTED_VLA_TYPES.map((v) => (
            <option key={v} value={v}>{v.toUpperCase()}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Hours *: {(data.config.hours as number) ?? 2}</label>
        <input type="range" min={0.5} max={24} step={0.5}
          value={(data.config.hours as number) ?? 2}
          onChange={(e) => onChange('hours', parseFloat(e.target.value))}
          className="w-full" />
      </div>
      <div>
        <label className={labelCls}>Batch Size: {(data.config.batchSize as number) ?? 32}</label>
        <input type="range" min={1} max={256}
          value={(data.config.batchSize as number) ?? 32}
          onChange={(e) => onChange('batchSize', parseInt(e.target.value))}
          className="w-full" />
      </div>
      <div>
        <label className={labelCls}>Instance Type</label>
        <select
          value={(data.config.instanceType as string) || 'A100'}
          onChange={(e) => onChange('instanceType', e.target.value)}
          className={inputCls}
        >
          {SUPPORTED_INSTANCE_TYPES.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Job Name</label>
        <input type="text"
          value={(data.config.jobName as string) || ''}
          onChange={(e) => onChange('jobName', e.target.value)}
          placeholder="Optional" className={inputCls} />
      </div>

      {/* Camera Mappings */}
      <div className="pt-2 border-t">
        <label className={labelCls}>Camera Mappings</label>
        <div className="space-y-2">
          {mappings.map((m, i) => (
            <div key={i} className="flex gap-1.5 items-start">
              <input type="text" value={m.slot}
                onChange={(e) => updateMapping(i, { slot: e.target.value })}
                placeholder="cam_1" className={inputCls + ' flex-1'} />
              <input type="text" value={m.imageKey}
                onChange={(e) => updateMapping(i, { imageKey: e.target.value })}
                placeholder="observation.images.top"
                className={inputCls + ' flex-[1.5] font-mono text-xs'} />
              <button onClick={() => removeMapping(i)}
                className="p-2 rounded-md text-red-500 hover:bg-red-500/10">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
        <button onClick={addMapping}
          className="w-full mt-2 py-1.5 px-3 rounded-md border border-dashed text-xs text-muted-foreground hover:bg-muted flex items-center justify-center gap-1">
          <Plus className="w-3.5 h-3.5" /> Add mapping
        </button>
      </div>
    </div>
  );
}

function RewardModelForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Head Mode</label>
        <select
          value={(data.config.headMode as string) || 'dense'}
          onChange={(e) => onChange('headMode', e.target.value)}
          className={inputCls}
        >
          <option value="dense">Dense</option>
          <option value="sparse">Sparse</option>
          <option value="both">Both</option>
        </select>
      </div>
      <div>
        <label className={labelCls}>Instance Type</label>
        <select
          value={(data.config.instanceType as string) || 'H100'}
          onChange={(e) => onChange('instanceType', e.target.value)}
          className={inputCls}
        >
          {SUPPORTED_INSTANCE_TYPES.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Hours: {(data.config.hours as number) ?? 2}</label>
        <input type="range" min={0.5} max={24} step={0.5}
          value={(data.config.hours as number) ?? 2}
          onChange={(e) => onChange('hours', parseFloat(e.target.value))}
          className="w-full" />
      </div>
      <div>
        <label className={labelCls}>Image Observation Key</label>
        <input type="text"
          value={(data.config.imageObservationKey as string) || ''}
          onChange={(e) => onChange('imageObservationKey', e.target.value)}
          placeholder="observation.images.wrist"
          className={inputCls + ' font-mono text-xs'} />
      </div>
    </div>
  );
}

function ApiPendingForm({ data }: { data: WorkflowNodeData }) {
  return (
    <div className="space-y-3">
      <div className="p-3 rounded-lg bg-orange-500/10 border border-orange-500/30">
        <p className="text-xs font-medium text-orange-600 mb-1">API Pending</p>
        <p className="text-xs text-muted-foreground">
          This Qualia Studio node is present for workflow design purposes.
          BotverseX API integration is pending — execution will show a clear status
          rather than simulating results.
        </p>
      </div>
      <p className="text-xs text-muted-foreground">
        Node: <span className="font-mono">{data.type}</span>
      </p>
    </div>
  );
}

// ---------- Finetune chain forms (legacy) ----------

function DatasetLoadForm({ data, onChange }: FormProps) {
  const imageKeys = (data.config.imageKeys as string[]) || [];
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Dataset ID *</label>
        <input
          type="text"
          value={(data.config.datasetId as string) || ''}
          onChange={(e) => onChange('datasetId', e.target.value)}
          placeholder="owner/name (e.g. lerobot/pusht)"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Dataset Type</label>
        <select
          value={(data.config.datasetType as string) || 'lerobot_v3'}
          onChange={(e) => onChange('datasetType', e.target.value)}
          className={inputCls}
        >
          <option value="lerobot_v3">lerobot_v3</option>
          <option value="sarm_progress">sarm_progress</option>
        </select>
      </div>
      <div>
        <label className={labelCls}>
          Known image keys {imageKeys.length > 0 && `(${imageKeys.length})`}
        </label>
        <textarea
          value={imageKeys.join('\n')}
          onChange={(e) =>
            onChange(
              'imageKeys',
              e.target.value
                .split(/\r?\n/)
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
          placeholder={'observation.images.top\nobservation.images.wrist'}
          rows={3}
          className={inputCls + ' font-mono text-xs'}
        />
        <p className="text-[10px] text-muted-foreground mt-1">
          One per line. Optional — can also be filled by Camera Map.
        </p>
      </div>
    </div>
  );
}

function CameraMapForm({ data, onChange }: FormProps) {
  const mappings: CameraMapEntry[] =
    (data.config.mappings as CameraMapEntry[]) || [];

  const update = (idx: number, patch: Partial<CameraMapEntry>) => {
    const next = mappings.map((m, i) => (i === idx ? { ...m, ...patch } : m));
    onChange('mappings', next);
  };
  const add = () => {
    const nextSlot = `cam_${mappings.length + 1}`;
    onChange('mappings', [...mappings, { slot: nextSlot, imageKey: '' }]);
  };
  const remove = (idx: number) => {
    onChange(
      'mappings',
      mappings.filter((_, i) => i !== idx)
    );
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {mappings.map((m, i) => (
          <div key={i} className="flex gap-1.5 items-start">
            <input
              type="text"
              value={m.slot}
              onChange={(e) => update(i, { slot: e.target.value })}
              placeholder="cam_1"
              className={inputCls + ' flex-1'}
            />
            <input
              type="text"
              value={m.imageKey}
              onChange={(e) => update(i, { imageKey: e.target.value })}
              placeholder="observation.images.top"
              className={inputCls + ' flex-[1.5] font-mono text-xs'}
            />
            <button
              onClick={() => remove(i)}
              className="p-2 rounded-md text-red-500 hover:bg-red-500/10"
              title="Remove"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
      <button
        onClick={add}
        className="w-full py-1.5 px-3 rounded-md border border-dashed text-xs text-muted-foreground hover:bg-muted flex items-center justify-center gap-1"
      >
        <Plus className="w-3.5 h-3.5" />
        Add mapping
      </button>
      <p className="text-[10px] text-muted-foreground">
        Model camera slot (e.g. cam_1) → dataset image key.
      </p>
    </div>
  );
}

function FinetuneJobForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Job Name</label>
        <input
          type="text"
          value={(data.config.jobName as string) || ''}
          onChange={(e) => onChange('jobName', e.target.value)}
          placeholder="Optional"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>VLA Type *</label>
        <select
          value={(data.config.vlaType as string) || 'act'}
          onChange={(e) => onChange('vlaType', e.target.value)}
          className={inputCls}
        >
          {SUPPORTED_VLA_TYPES.map((v) => (
            <option key={v} value={v}>
              {v.toUpperCase()}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>
          Hours *: {(data.config.hours as number) ?? 2}
        </label>
        <input
          type="range"
          min={0.5}
          max={24}
          step={0.5}
          value={(data.config.hours as number) ?? 2}
          onChange={(e) => onChange('hours', parseFloat(e.target.value))}
          className="w-full"
        />
        <p className="text-[10px] text-muted-foreground">Range (0, 168]</p>
      </div>
      <div>
        <label className={labelCls}>
          Batch Size: {(data.config.batchSize as number) ?? 32}
        </label>
        <input
          type="range"
          min={1}
          max={256}
          value={(data.config.batchSize as number) ?? 32}
          onChange={(e) => onChange('batchSize', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>Instance Type</label>
        <select
          value={(data.config.instanceType as string) || 'A100'}
          onChange={(e) => onChange('instanceType', e.target.value)}
          className={inputCls}
        >
          {SUPPORTED_INSTANCE_TYPES.map((i) => (
            <option key={i} value={i}>
              {i}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>Region</label>
        <input
          type="text"
          value={(data.config.region as string) || ''}
          onChange={(e) => onChange('region', e.target.value)}
          placeholder="Optional"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Job Type</label>
        <select
          value={(data.config.jobType as string) || 'vla'}
          onChange={(e) => onChange('jobType', e.target.value)}
          className={inputCls}
        >
          <option value="vla">vla</option>
          <option value="reward">reward</option>
          <option value="vla_w_reward">vla_w_reward</option>
        </select>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={Boolean(data.config.useRabc)}
          onChange={(e) => onChange('useRabc', e.target.checked)}
        />
        <span>Use SARM RA-BC</span>
      </label>
    </div>
  );
}

function SkillInvokeForm({ data, onChange }: FormProps) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [runtimes, setRuntimes] = useState<RuntimeWithSkills[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const skillId = (data.config.skillId as string) || '';
  const runtimeId = (data.config.runtimeId as string) || '';
  const params = (data.config.params as Record<string, unknown>) || {};

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const [sk, rt] = await Promise.all([listSkills(), listRuntimesWithSkills()]);
        if (cancel) return;
        setSkills(sk.skills);
        setRuntimes(rt.runtimes);
      } catch (e) {
        if (!cancel) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  const selectedSkill = skills.find((s) => s.skill_id === skillId);
  const compatibleRuntimes = selectedSkill
    ? runtimes.filter(
        (r) =>
          selectedSkill.robot_type === r.robot_type ||
          selectedSkill.compatible_types.includes(r.robot_type),
      )
    : runtimes;

  const setParam = (key: string, v: unknown) => {
    onChange('params', { ...params, [key]: v });
  };

  return (
    <div className="space-y-3">
      {loading && <p className="text-xs text-muted-foreground">Loading skills...</p>}
      {error && (
        <p className="text-xs text-red-400 border border-red-500/30 rounded px-2 py-1">
          {error}
        </p>
      )}

      <div>
        <label className={labelCls}>Skill *</label>
        <select
          value={skillId}
          onChange={(e) => {
            onChange('skillId', e.target.value);
            onChange('runtimeId', '');
            onChange('params', {});
          }}
          className={inputCls}
        >
          <option value="">— select a skill —</option>
          {skills.map((s) => (
            <option key={s.skill_id} value={s.skill_id}>
              {s.verb} · {s.skill_id}
            </option>
          ))}
        </select>
        {selectedSkill?.description && (
          <p className="text-[10px] text-muted-foreground mt-1">
            {selectedSkill.description}
          </p>
        )}
      </div>

      <div>
        <label className={labelCls}>Runtime *</label>
        <select
          value={runtimeId}
          onChange={(e) => onChange('runtimeId', e.target.value)}
          className={inputCls}
          disabled={!selectedSkill}
        >
          <option value="">
            {selectedSkill ? '— select a runtime —' : 'Pick a skill first'}
          </option>
          {compatibleRuntimes.map((rt) => (
            <option key={rt.runtime_id} value={rt.runtime_id}>
              {rt.display_name}
            </option>
          ))}
        </select>
      </div>

      {selectedSkill && (selectedSkill.params_schema || []).length > 0 && (
        <div className="pt-2 border-t space-y-2">
          <div className="text-xs font-medium">Params (override installation)</div>
          {(selectedSkill.params_schema || []).map((entry) => {
            const v = params[entry.key];
            const id = `wf-skill-param-${entry.key}`;
            return (
              <div key={entry.key}>
                <label htmlFor={id} className={labelCls}>
                  {entry.label}
                  {entry.required && <span className="text-red-400"> *</span>}
                </label>
                {entry.type === 'enum' ? (
                  <select
                    id={id}
                    value={String(v ?? '')}
                    onChange={(e) => setParam(entry.key, e.target.value)}
                    className={inputCls}
                  >
                    <option value="">—</option>
                    {(entry.options || []).map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : entry.type === 'bool' ? (
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      id={id}
                      type="checkbox"
                      checked={Boolean(v)}
                      onChange={(e) => setParam(entry.key, e.target.checked)}
                    />
                    <span>enabled</span>
                  </label>
                ) : entry.type === 'number' ? (
                  <input
                    id={id}
                    type="number"
                    value={v === undefined || v === null ? '' : String(v)}
                    onChange={(e) =>
                      setParam(entry.key, e.target.value === '' ? '' : Number(e.target.value))
                    }
                    className={inputCls}
                  />
                ) : (
                  <input
                    id={id}
                    type="text"
                    value={v === undefined || v === null ? '' : String(v)}
                    onChange={(e) => setParam(entry.key, e.target.value)}
                    className={inputCls}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground">
        Execution delegates to <span className="font-mono">POST /api/v1/skills/{'{id}'}/run</span> — the same path the Skills page uses.
      </p>
    </div>
  );
}

function JobMonitorForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>
          Poll Interval (sec): {(data.config.pollIntervalSec as number) ?? 5}
        </label>
        <input
          type="range"
          min={1}
          max={60}
          value={(data.config.pollIntervalSec as number) ?? 5}
          onChange={(e) => onChange('pollIntervalSec', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>
          Timeout (min): {(data.config.timeoutMin as number) ?? 60}
        </label>
        <input
          type="range"
          min={1}
          max={360}
          value={(data.config.timeoutMin as number) ?? 60}
          onChange={(e) => onChange('timeoutMin', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
    </div>
  );
}

// ---------- Legacy demo forms ----------

function LegacyRobotForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Robot ID</label>
        <input
          type="text"
          value={(data.config.robotId as string) || ''}
          onChange={(e) => onChange('robotId', e.target.value)}
          placeholder="e.g. so100_001"
          className={inputCls}
        />
      </div>
    </div>
  );
}

function LegacyRecordForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Dataset Name</label>
        <input
          type="text"
          value={(data.config.datasetName as string) || ''}
          onChange={(e) => onChange('datasetName', e.target.value)}
          placeholder="e.g. pick_place_v1"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Episodes: {(data.config.episodes as number) || 10}</label>
        <input
          type="range"
          min={1}
          max={50}
          value={(data.config.episodes as number) || 10}
          onChange={(e) => onChange('episodes', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>FPS: {(data.config.fps as number) || 30}</label>
        <input
          type="range"
          min={15}
          max={60}
          value={(data.config.fps as number) || 30}
          onChange={(e) => onChange('fps', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
    </div>
  );
}

function EvaluateForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>
          Pass Threshold: {((data.config.passThreshold as number) ?? 0.7 * 100).toFixed(0)}%
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={((data.config.passThreshold as number) ?? 0.7) * 100}
          onChange={(e) => onChange('passThreshold', parseInt(e.target.value) / 100)}
          className="w-full"
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Reads upstream job_monitor result and produces pass/fail + score metrics.
      </p>
    </div>
  );
}

function PublishSkillForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Skill Name *</label>
        <input
          type="text"
          value={(data.config.skillName as string) || ''}
          onChange={(e) => onChange('skillName', e.target.value)}
          placeholder="e.g. grab_cup"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Verb</label>
        <select
          value={(data.config.verb as string) || 'manipulate'}
          onChange={(e) => onChange('verb', e.target.value)}
          className={inputCls}
        >
          <option value="manipulate">manipulate</option>
          <option value="push">push</option>
          <option value="pick">pick</option>
          <option value="pour">pour</option>
          <option value="wave">wave</option>
          <option value="teleop">teleop</option>
          <option value="record">record</option>
        </select>
      </div>
      <div>
        <label className={labelCls}>Version</label>
        <input
          type="text"
          value={(data.config.version as string) || '1.0.0'}
          onChange={(e) => onChange('version', e.target.value)}
          placeholder="1.0.0"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Description</label>
        <textarea
          value={(data.config.description as string) || ''}
          onChange={(e) => onChange('description', e.target.value)}
          placeholder="What this skill does..."
          rows={2}
          className={inputCls}
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Generates a Skill manifest preview. First version is local-only — Marketplace publishing coming later.
      </p>
    </div>
  );
}

function RecordDatasetStartForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Task Name *</label>
        <input
          type="text"
          value={(data.config.taskName as string) || ''}
          onChange={(e) => onChange('taskName', e.target.value)}
          placeholder="pick_place"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Episodes: {(data.config.episodes as number) || 1}</label>
        <input
          type="range"
          min={1}
          max={50}
          value={(data.config.episodes as number) || 1}
          onChange={(e) => onChange('episodes', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>Leader Port</label>
        <input
          type="text"
          value={(data.config.leaderPort as string) || '/dev/ttyACM0'}
          onChange={(e) => onChange('leaderPort', e.target.value)}
          className={inputCls + ' font-mono text-xs'}
        />
      </div>
      <div>
        <label className={labelCls}>Follower Port</label>
        <input
          type="text"
          value={(data.config.followerPort as string) || '/dev/ttyACM1'}
          onChange={(e) => onChange('followerPort', e.target.value)}
          className={inputCls + ' font-mono text-xs'}
        />
      </div>
      <div>
        <label className={labelCls}>Camera IDs</label>
        <input
          type="text"
          value={(data.config.cameraIds as string) || '0'}
          onChange={(e) => onChange('cameraIds', e.target.value)}
          placeholder="0,1"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>FPS: {(data.config.fps as number) || 30}</label>
        <input
          type="range"
          min={15}
          max={60}
          value={(data.config.fps as number) || 30}
          onChange={(e) => onChange('fps', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Calls <span className="font-mono">POST /api/recording/start</span> — requires Local Agent running.
      </p>
    </div>
  );
}

function ReachyRecordMoveForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Move Name</label>
        <input
          type="text"
          value={(data.config.moveName as string) || ''}
          onChange={(e) => onChange('moveName', e.target.value)}
          placeholder="wave_hello"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>Duration (sec): {(data.config.durationS as number) ?? 10}</label>
        <input
          type="range"
          min={1}
          max={60}
          value={(data.config.durationS as number) ?? 10}
          onChange={(e) => onChange('durationS', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>Sample Hz: {(data.config.sampleHz as number) ?? 100}</label>
        <input
          type="range"
          min={10}
          max={200}
          step={10}
          value={(data.config.sampleHz as number) ?? 100}
          onChange={(e) => onChange('sampleHz', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Calls <span className="font-mono">POST /api/reachy/record/start</span>, waits duration, then <span className="font-mono">POST /api/reachy/record/stop</span>.
      </p>
    </div>
  );
}

function LegacyTrainForm({ data, onChange }: FormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Model Type</label>
        <select
          value={(data.config.modelType as string) || 'act'}
          onChange={(e) => onChange('modelType', e.target.value)}
          className={inputCls}
        >
          <option value="act">ACT</option>
          <option value="diffusion">Diffusion Policy</option>
          <option value="vla">VLA</option>
        </select>
      </div>
      <div>
        <label className={labelCls}>
          Epochs: {(data.config.epochs as number) || 100}
        </label>
        <input
          type="range"
          min={10}
          max={500}
          step={10}
          value={(data.config.epochs as number) || 100}
          onChange={(e) => onChange('epochs', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
      <div>
        <label className={labelCls}>
          Batch Size: {(data.config.batchSize as number) || 8}
        </label>
        <input
          type="range"
          min={1}
          max={32}
          value={(data.config.batchSize as number) || 8}
          onChange={(e) => onChange('batchSize', parseInt(e.target.value))}
          className="w-full"
        />
      </div>
    </div>
  );
}
