import {Badge, Mono, Panel} from '../../components/primitives';
import {RELATION_TYPE_LABELS} from './discoveryView';
import type {EvidenceCardRefusalReason, EvidenceCardRefusalV1, EvidenceCardV1} from './types';

const REFUSAL_LABELS: Record<EvidenceCardRefusalReason, string> = {
  RELATION_NOT_LIVE: '这条关系已不再有效',
  BINDING_MISMATCH: '绑定与当前卡片不一致',
  PERMISSION_REVOKED: '访问权限已被撤销',
  CONTENT_UNAVAILABLE: '被引用的内容已不可用',
  PARTIAL_PROVENANCE: '溯源不完整',
  MISSING_REFERENCES: '来源或片段无法解析',
};

/**
 * The bilateral comparison the user confirmed, and nothing more.
 *
 * No generated summary anywhere in this component. A summary would be a new
 * artifact produced after the confirmation gate: never reviewed by the user,
 * free to drift from the relation they approved, and reading as a faithful
 * description of it.
 */
export function EvidenceCardPanel({
  card,
  currentCardHash,
}: {
  card: EvidenceCardV1 | EvidenceCardRefusalV1 | null;
  /** The binding from the workspace, shown beside the card's own. */
  currentCardHash?: string | null;
}) {
  if (card === null) {
    return null;
  }

  if (card.outcome === 'REFUSED') {
    return (
      <Panel title="历史证据" testId="evidence-card">
        {/* A whole-card refusal, rendered as itself. Rendering it as an empty
            card would look authoritative while silently dropping content, which
            is the failure the typed refusal exists to prevent. */}
        <div role="alert" data-testid="evidence-refusal" className="notice notice--warn">
          <strong data-testid="evidence-refusal-reason">{REFUSAL_LABELS[card.reason]}</strong>
          <p>{card.detail}</p>
          <p>没有渲染出局部的卡片：缺一半溯源的卡片看上去同样完整，而你无从知道少了什么。</p>
          {card.unresolved_refs.length > 0 ? (
            <ul data-testid="evidence-unresolved">
              {card.unresolved_refs.map((ref) => (
                <li key={ref}>
                  <Mono>{ref}</Mono>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </Panel>
    );
  }

  // GRAG-14 made visible: the card names the current-card binding it was
  // authorized against, so the user can check it against the card they
  // accepted rather than trusting that the read changed nothing.
  const bindingHolds = currentCardHash == null || currentCardHash === card.current_knowledge_card_hash;

  return (
    <Panel
      title="历史证据"
      testId="evidence-card"
      actions={
        <Badge tone="ok" testId="evidence-relation-type">
          {RELATION_TYPE_LABELS[card.relation_type] ?? card.relation_type}
        </Badge>
      }
    >
      <div data-testid="evidence-binding" data-binding-holds={String(bindingHolds)}>
        <strong>当前卡片绑定</strong>
        <p>
          <Mono>{card.current_knowledge_card_hash}</Mono>
        </p>
        <p>
          {bindingHolds
            ? '与你接受的那张卡一致：这次读取没有改变当前卡片。'
            : '与当前卡片不一致，请重新确认后再读。'}
        </p>
      </div>

      <div data-testid="evidence-mapped-roles">
        <strong>逐角色对照</strong>
        <ul>
          {card.mapped_roles.map((role) => (
            <li key={`${role.current_node_id}:${role.historical_node_id}`}>
              <div>
                <Mono>{role.current_role ?? '根节点'}</Mono>：{role.current_label}
              </div>
              <div>
                <Mono>{role.historical_role ?? '根节点'}</Mono>：{role.historical_label}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div data-testid="evidence-boundaries">
        {/* Quoted, not paraphrased: a lesson shown without its limitation reads
            as general advice, and the user applies it where the original
            experience never reached. */}
        <strong>迁移边界</strong>
        <ul>
          {card.boundaries.map((boundary) => (
            <li key={`${boundary.side}:${boundary.node_id}`}>
              {boundary.side === 'CURRENT' ? '当前' : '历史'}
              <Mono>{boundary.role ?? '根节点'}</Mono>：{boundary.content}
            </li>
          ))}
        </ul>
      </div>

      <div data-testid="evidence-provenance">
        <strong>双边溯源</strong>
        <ul>
          {card.provenance.map((side) => (
            <li key={side.side} data-testid={`evidence-provenance-${side.side}`}>
              {side.side === 'CURRENT' ? '当前' : '历史'}（
              <Mono>{side.asset_id}</Mono>）：{side.statement_ids.length} 条陈述，
              {side.node_ids.length} 个节点
            </li>
          ))}
        </ul>
      </div>

      <p data-testid="evidence-card-hash">
        卡片哈希 <Mono>{card.card_hash}</Mono>
      </p>
    </Panel>
  );
}
