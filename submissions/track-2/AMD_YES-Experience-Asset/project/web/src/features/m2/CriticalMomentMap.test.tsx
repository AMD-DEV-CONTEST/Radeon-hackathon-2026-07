import { render, screen, within } from '@testing-library/react';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import criticalMomentMapSchema from '../../../../contracts/json-schema/critical-moment-map-v0.1.schema.json';
import { CriticalMomentMap } from './CriticalMomentMap';
import { M2_SCENARIOS } from './fixtures';

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validateContract = ajv.compile(criticalMomentMapSchema);

describe('CriticalMomentMap', () => {
  it('keeps all isolated fixtures inside the published M2 contract', () => {
    for (const fixture of Object.values(M2_SCENARIOS)) {
      expect(validateContract(fixture), JSON.stringify(validateContract.errors)).toBe(true);
    }
  });

  it('rejects malformed provenance and model-asserted confirmation', () => {
    expect(
      validateContract({
        ...M2_SCENARIOS.complete,
        state: 'INVALIDATED',
      }),
    ).toBe(false);
    expect(
      validateContract({
        ...M2_SCENARIOS.complete,
        moments: [
          {
            ...M2_SCENARIOS.complete.moments[0],
            criticality_status: 'USER_CONFIRMED',
          },
        ],
      }),
    ).toBe(false);
  });

  it('renders source-supported moments in sequence', () => {
    render(<CriticalMomentMap artifact={M2_SCENARIOS.complete} />);
    const list = screen.getByTestId('m2-moment-list');
    const moments = within(list).getAllByRole('listitem');
    expect(moments).toHaveLength(2);
    expect(moments[0]).toHaveTextContent('开始试用网面椅');
    expect(moments[1]).toHaveTextContent('更换为软垫人体工学椅');
    expect(screen.getAllByText('时间有来源')).toHaveLength(2);
  });

  it('renders cue, change/turning, surprise and conflict evidence roles', () => {
    render(<CriticalMomentMap artifact={M2_SCENARIOS.complete} />);
    expect(screen.getByTestId('m2-evidence-roles-0')).toHaveTextContent('线索 1');
    expect(screen.getByTestId('m2-evidence-roles-0')).toHaveTextContent('变化/转折 0');
    expect(screen.getByTestId('m2-evidence-roles-1')).toHaveTextContent('变化/转折 1');
    expect(screen.getByTestId('m2-evidence-roles-1')).toHaveTextContent('意外 1');
    expect(screen.getByTestId('m2-evidence-roles-1')).toHaveTextContent('冲突 0');
  });

  it('shows missing time as unresolved instead of inventing a date', () => {
    render(<CriticalMomentMap artifact={M2_SCENARIOS.incomplete} />);
    expect(screen.getByText('时间待确认')).toBeInTheDocument();
    expect(screen.getByTestId('m2-unresolved-reason')).toHaveTextContent('没有说明');
    expect(screen.queryByTestId('m2-time-label')).toBeNull();
  });

  it('keeps conflicting source timelines visible', () => {
    render(<CriticalMomentMap artifact={M2_SCENARIOS.conflicting} />);
    expect(screen.getByText('来源冲突')).toBeInTheDocument();
    expect(screen.getByTestId('m2-unresolved-reason')).toHaveTextContent('当天退回');
  });

  it('does not present an invalidated M2 artifact as current', () => {
    render(<CriticalMomentMap artifact={M2_SCENARIOS.correction_invalidation} />);
    expect(screen.getByTestId('m2-invalidated')).toHaveTextContent('已失效');
    expect(screen.getByText('INVALIDATED')).toBeInTheDocument();
  });
});
