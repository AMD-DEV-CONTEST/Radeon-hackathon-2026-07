/**
 * 基础 Schema Registry (QAE-015 最小实现)
 * 
 * 提供 JSON Schema 的集中加载和管理。
 * 当前仅加载已有的 schemas/ 下定义，后续可扩展为支持 CI 校验、版本兼容检查。
 * 
 * 参考：
 * - schemas/events/evidence-event-v1.json
 * - schemas/evaluations/ai-evaluation-result-v1.json
 * - schemas/openapi.yaml
 */

import evidenceEventSchema from '../../../schemas/events/evidence-event-v1.json';
import aiEvalResultSchema from '../../../schemas/evaluations/ai-evaluation-result-v1.json';

export interface SchemaInfo {
  $id: string;
  title?: string;
  version?: string;
}

export const SCHEMA_REGISTRY: Record<string, any> = {
  'schemas/events/evidence-event-v1.json': evidenceEventSchema,
  'schemas/evaluations/ai-evaluation-result-v1.json': aiEvalResultSchema,
};

export function getSchema(ref: string): any | undefined {
  return SCHEMA_REGISTRY[ref];
}

export function listAvailableSchemas(): string[] {
  return Object.keys(SCHEMA_REGISTRY);
}

export function getSchemaInfo(ref: string): SchemaInfo | undefined {
  const schema = getSchema(ref);
  if (!schema) return undefined;
  return {
    $id: schema.$id || ref,
    title: schema.title,
    version: schema.version || '1.0',
  };
}

/**
 * 简单校验入口（占位）
 * 实际生产可集成 ajv 或其他 validator。
 * 当前仅返回 schema 以支持后续扩展。
 */
export function validateAgainstSchema(data: unknown, ref: string): { valid: boolean; schema?: any; error?: string } {
  const schema = getSchema(ref);
  if (!schema) {
    return { valid: false, error: `Schema not found: ${ref}` };
  }
  // TODO: 实际校验逻辑 (QAE-015 后续)
  return { valid: true, schema };
}
