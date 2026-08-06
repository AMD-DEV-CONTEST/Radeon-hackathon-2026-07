import type { RelationDiscoveryView } from '../viewmodel/relationView';
import { Badge, Panel } from './primitives';
import {
  DETAIL_ACCESS_LABEL,
  DETAIL_ACCESS_TONE,
  RELATION_CONFIRMATION_LABEL,
  RELATION_CONFIRMATION_TONE,
  RELATION_GATE_LABEL,
  RELATION_GATE_TONE,
} from './labels';

/**
 * Cross-asset relation discovery, rendered from the canonical E1-A asset and
 * independently checked retrieval-phase trace. This component enforces nothing
 * itself — the gates live in `deriveRelationDiscovery`; it only presents the
 * derived, contract-faithful state:
 *  - LOCKED until an accepted KnowledgeCardReady at M4 (candidates hidden);
 *  - candidates are summary-only (title, relation type, reason, provenance);
 *  - a valid no-match state;
 *  - detailed evidence stays denied until a relation is explicitly confirmed;
 *  - editing/reopening M1–M4 invalidates the whole surface.
 *
 * Confirm/Decline are backend-owned actions. The shell presents them as the
 * required explicit affordance but does not fabricate the mutation locally; each
 * checked-in scenario is a truthful snapshot of one contract state.
 */
export function RelationDiscoveryPanel({
  relation,
}: {
  relation: RelationDiscoveryView;
}) {
  const gateBadge = (
    <Badge
      tone={RELATION_GATE_TONE[relation.gate]}
      testId="relation-gate"
      title={relation.gate}
    >
      {RELATION_GATE_LABEL[relation.gate]}
    </Badge>
  );

  if (!relation.available) {
    return (
      <Panel title="跨资产关系发现" testId="relation-panel" actions={gateBadge}>
        <p className="hint" data-testid="relation-not-served">
          当前数据源未提供检索阶段轨迹（后端 RAG 端点尚未暴露，not&nbsp;served）。界面不虚构候选或就绪度。
        </p>
      </Panel>
    );
  }

  return (
    <Panel title="跨资产关系发现" testId="relation-panel" actions={gateBadge}>
      {relation.gate === 'LOCKED' ? (
        <p className="hint" data-testid="relation-locked">
          M4 KnowledgeCardReady 尚未被显式接受：跨资产候选发现已锁定，界面不会预取历史详情。
        </p>
      ) : null}

      {relation.gate === 'INVALIDATED' ? (
        <p className="notice notice--danger" data-testid="relation-invalidated">
          {relation.invalidationReason}
        </p>
      ) : null}

      {relation.gate === 'READY' ? (
        <>
          <div className="relation__card-meta">
            <span className="hint">
              知识卡版本 <code className="mono">{relation.knowledgeCardVersion ?? '—'}</code>
              {relation.knowledgeCardHash ? (
                <>
                  {' · '}
                  <code className="mono">{relation.knowledgeCardHash.slice(0, 12)}</code>
                </>
              ) : null}
            </span>
          </div>

          {relation.noMatch ? (
            <p className="hint" data-testid="relation-no-match">
              已在就绪的知识卡上检索：未发现相似的跨资产关系（no-match）。这是一个合法状态，非错误。
            </p>
          ) : relation.candidates.length === 0 ? (
            <p className="hint" data-testid="relation-empty">
              就绪，但尚未产生候选。
            </p>
          ) : (
            <ul className="relations" data-testid="relation-candidates">
              {relation.candidates.map((c) => (
                <li key={c.relationId} className="relation" data-testid={`relation-${c.relationId}`}>
                  <div className="relation__head">
                    <span className="relation__title">{c.title ?? c.relatedAssetId ?? c.relationId}</span>
                    {c.relationType ? (
                      <Badge tone="info" testId={`relation-${c.relationId}-type`}>
                        {c.relationType}
                      </Badge>
                    ) : null}
                    <Badge
                      tone={RELATION_CONFIRMATION_TONE[c.confirmation]}
                      testId={`relation-${c.relationId}-confirmation`}
                    >
                      {RELATION_CONFIRMATION_LABEL[c.confirmation]}
                    </Badge>
                  </div>

                  {c.summary ? (
                    <p className="relation__why" data-testid={`relation-${c.relationId}-summary`}>
                      {c.summary}
                    </p>
                  ) : null}
                  {c.boundaryNodeIds.length ? (
                    <p
                      className="relation__why"
                      data-testid={`relation-${c.relationId}-boundary`}
                    >
                      迁移边界：{c.boundaryNodeIds.length} 项（来自当前资产的限制、
                      适用条件或反例）
                    </p>
                  ) : null}

                  {/* Provenance stays attributed to each side. A count that
                      merged both sides could show a full bar while one asset
                      contributed nothing, and a one-sided explanation is
                      exactly what the bilateral requirement rules out. */}
                  <p className="relation__prov">
                    出处引用：当前 {c.currentProvenanceRefs.length} 条 · 历史{' '}
                    {c.historicalProvenanceRefs.length} 条
                    {c.relatedAssetId ? (
                      <>
                        {' · '}资产 <code className="mono">{c.relatedAssetId}</code>
                      </>
                    ) : null}
                  </p>

                  <div className="relation__detail">
                    <Badge
                      tone={DETAIL_ACCESS_TONE[c.detailAccess]}
                      testId={`relation-${c.relationId}-detail`}
                    >
                      {DETAIL_ACCESS_LABEL[c.detailAccess]}
                      {c.detailAccess === 'AVAILABLE' && c.detailRetrieved ? '（已检索）' : ''}
                    </Badge>
                  </div>

                  {c.confirmation === 'PENDING' ? (
                    <div className="relation__actions" data-testid={`relation-${c.relationId}-actions`}>
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled
                        title="确认为后端受控动作；当前为契约轨迹快照，界面不虚构状态。"
                      >
                        确认关系
                      </button>
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled
                        title="拒绝为后端受控动作；当前为契约轨迹快照，界面不虚构状态。"
                      >
                        拒绝
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}

      {relation.gateViolations.length > 0 ? (
        <div className="notice notice--danger" data-testid="relation-gate-violations">
          <strong>门控违规（契约顺序异常，已被界面拒绝）：</strong>
          <ul>
            {relation.gateViolations.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="hint">
        规则：候选发现须在 M4 KnowledgeCardReady 之后；详细证据须在关系被显式确认之后。二者由 <code className="mono">deriveRelationDiscovery</code> 强制并有单测证明。
      </p>
    </Panel>
  );
}
