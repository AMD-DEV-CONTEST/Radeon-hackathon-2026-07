/**
 * Tamper-evidence: the vendored contract files must match the recorded
 * provenance hashes. Proves Lane B did not silently fork Lane A's contract.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';

import provenance from '../../contracts/provenance.json';
import e5Provenance from '../../contracts/e5-contract-provenance.json';

const contractsDir = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'contracts');

describe('vendored contract provenance', () => {
  it('records the E1-A source commit', () => {
    expect(provenance.source_commit).toBe('431e1a54040efbe4ccf04daf51b96e3642d233da');
    expect(provenance.source_branch).toBe('main');
    expect(Object.keys(provenance.sha256)).toEqual([
      'examples/health.json',
      'examples/progress-running.json',
      'examples/structured-tool-proposal.json',
      'examples/terminal-model-unavailable.json',
      'json-schema/policy-decision-v1.schema.json',
      'json-schema/progress-event-v1.schema.json',
      'json-schema/structured-proposal-v1.schema.json',
      'json-schema/terminal-result-v1.schema.json',
      'json-schema/tool-execution-record-v1.schema.json',
      'json-schema/verification-report-v1.schema.json',
      'json-schema/work-plan-v1.schema.json',
    ]);
  });

  it('moves re-vendored contracts to the manifest that actually sourced them', () => {
    // ExperienceAssetV1, AgentRunStateV1 and openapi.json changed in the E5
    // contract freeze, so their content no longer comes from 431e1a5. Leaving
    // them listed here would make the manifest assert a source commit that
    // never produced this content — exactly the silent fork the provenance
    // mechanism exists to detect.
    for (const moved of [
      'json-schema/agent-run-state-v1.schema.json',
      'json-schema/experience-asset-v1.schema.json',
      'openapi.json',
    ]) {
      expect(Object.keys(provenance.sha256)).not.toContain(moved);
      expect(Object.keys(e5Provenance.sha256)).toContain(moved);
    }
  });

  it('records the E5 source commit as unmerged rather than claiming a merge', () => {
    // Binding to a branch head is truthful; claiming it is on main would not be.
    expect(e5Provenance.source_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(e5Provenance.source_branch).not.toBe('main');
    expect(e5Provenance.source_commit_is_merged).toBe(false);
  });

  it.each(Object.entries(e5Provenance.sha256))(
    'E5 %s matches its recorded sha256',
    (rel, expected) => {
      const buf = readFileSync(join(contractsDir, rel));
      const actual = createHash('sha256').update(buf).digest('hex');
      expect(actual).toBe(expected);
    },
  );

  it.each(Object.entries(provenance.sha256))('%s matches its recorded sha256', (rel, expected) => {
    const buf = readFileSync(join(contractsDir, rel));
    const actual = createHash('sha256').update(buf).digest('hex');
    expect(actual).toBe(expected);
  });
});
