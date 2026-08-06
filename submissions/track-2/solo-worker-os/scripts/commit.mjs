import isogit from 'isomorphic-git';
import fs from 'fs';
import path from 'path';

const DIR = 'e:\\gitproject\\hackathon\\solo';
const changedFiles = [
  'components/DashboardRefresher.tsx',
  'components/SignOutButton.tsx',
];

async function main() {
  // Check current branch
  const branch = await isogit.currentBranch({ fs, dir: DIR, fullname: false });
  console.log('Current branch:', branch);

  // Get status
  const status = await isogit.statusMatrix({ fs, dir: DIR });
  const changed = status.filter(([file, head, workdir, stage]) => head !== workdir || stage !== workdir);
  console.log('Changed files:', changed.map(f => f[0]).join(', '));

  if (changed.length === 0) {
    console.log('No changes to commit.');
    return;
  }

  // Configure git user
  await isogit.setConfig({ fs, dir: DIR, path: 'user.name', value: 'Solo Worker OS' });
  await isogit.setConfig({ fs, dir: DIR, path: 'user.email', value: 'bot@solo-worker-os.ai' });

  // Stage all files
  for (const [filepath] of changed) {
    await isogit.add({ fs, dir: DIR, filepath });
  }
  console.log('Staged', changed.length, 'files');

  // Commit
  const sha = await isogit.commit({
    fs,
    dir: DIR,
    message: 'fix: 修复点击响应和浅色模式显示问题',
    author: {
      name: 'Solo Worker OS',
      email: 'bot@solo-worker-os.ai',
    },
  });
  console.log('Committed:', sha);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});