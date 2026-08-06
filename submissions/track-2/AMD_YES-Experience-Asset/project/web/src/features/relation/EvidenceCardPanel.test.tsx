import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {EvidenceCardPanel} from './EvidenceCardPanel';
import {EVIDENCE_SCENARIOS} from './fixtures';
import type {EvidenceCardRefusalV1, EvidenceCardV1} from './types';

const RENDERED = EVIDENCE_SCENARIOS.rendered as EvidenceCardV1;
const REFUSED = EVIDENCE_SCENARIOS.refused as EvidenceCardRefusalV1;

describe('the confirmed relation renders as a comparison, not a conclusion', () => {
  it('shows both sides of every mapped role with their canonical text', () => {
    render(<EvidenceCardPanel card={RENDERED} />);

    const roles = screen.getByTestId('evidence-mapped-roles');
    // Both labels verbatim: the text the user can open must be the text the
    // card shows, or the card describes something the evidence does not say.
    expect(roles).toHaveTextContent('先补一条基线测量再改缓存策略。');
    expect(roles).toHaveTextContent('先跑一轮压测拿到基线，再动索引。');
  });

  it('quotes the transfer boundary rather than paraphrasing it', () => {
    render(<EvidenceCardPanel card={RENDERED} />);

    // A lesson shown without its limitation reads as general advice, and the
    // user applies it where the original experience never reached.
    expect(screen.getByTestId('evidence-boundaries')).toHaveTextContent(
      '只在读多写少的负载上成立。',
    );
  });

  it('attributes provenance to both sides', () => {
    render(<EvidenceCardPanel card={RENDERED} />);

    // A bilateral explanation that cannot be attributed to both sides is not
    // bilateral.
    expect(screen.getByTestId('evidence-provenance-CURRENT')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-provenance-HISTORICAL')).toBeInTheDocument();
  });

  it('shows the unchanged current-card binding the card was authorized against', () => {
    render(<EvidenceCardPanel card={RENDERED} currentCardHash={'f'.repeat(64)} />);

    const binding = screen.getByTestId('evidence-binding');
    expect(binding).toHaveAttribute('data-binding-holds', 'true');
    expect(binding).toHaveTextContent('没有改变当前卡片');
  });

  it('says so when the binding no longer matches the current card', () => {
    // The paired negative. Without it, the binding display would pass its test
    // while being incapable of ever reporting a mismatch.
    render(
      <EvidenceCardPanel
        card={EVIDENCE_SCENARIOS.staleBinding as EvidenceCardV1}
        currentCardHash={'f'.repeat(64)}
      />,
    );

    const binding = screen.getByTestId('evidence-binding');
    expect(binding).toHaveAttribute('data-binding-holds', 'false');
    expect(binding).toHaveTextContent('重新确认');
  });
});

describe('a refusal is rendered as itself', () => {
  it('never renders as a partial card', () => {
    render(<EvidenceCardPanel card={REFUSED} />);

    expect(screen.getByTestId('evidence-refusal-reason')).toHaveTextContent('溯源不完整');
    // A card missing half its provenance still looks authoritative, and the
    // user has no way to see what was dropped.
    expect(screen.queryByTestId('evidence-mapped-roles')).not.toBeInTheDocument();
    expect(screen.queryByTestId('evidence-card-hash')).not.toBeInTheDocument();
  });

  it('names what could not be resolved', () => {
    render(<EvidenceCardPanel card={REFUSED} />);

    expect(screen.getByTestId('evidence-unresolved')).toHaveTextContent('source:9f3c');
  });
});

describe('before a confirmation there is nothing to render', () => {
  it('renders nothing at all when no card was produced', () => {
    // Four of the five relation operations produce no card. An empty panel
    // would suggest a card exists and is blank.
    const {container} = render(<EvidenceCardPanel card={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
