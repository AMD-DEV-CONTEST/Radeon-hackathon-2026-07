import './shell.css';

/**
 * Every milestone after M1 reads its asset id from the same local-storage key
 * that M1 writes, so in a normal run the field is already filled. An empty
 * field means the upstream milestone has not produced anything yet — say that,
 * instead of leaving a bare id box that reads as "type a UUID here".
 */
export function AssetHandoff({
  assetId,
  upstream,
  testId,
}: {
  assetId: string;
  upstream: string;
  testId: string;
}) {
  if (assetId) return null;

  return (
    <div className="notice notice--muted shell__handoff" data-testid={testId}>
      经验资产 ID 由 {upstream} 自动带入。现在是空的，说明这条链还没走到这里——
      请先完成 {upstream}。
    </div>
  );
}
