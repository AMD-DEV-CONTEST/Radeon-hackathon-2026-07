// 交叉验证：用宣传页同款 JS 引擎重放同一 SGF，输出终局盘面串
// 用法：node crosscheck.mjs <sgf路径>
import { readFileSync } from "fs";

const text = readFileSync(process.argv[2], "utf-8");
const moves = [...text.matchAll(/;[BW]\[([a-s]{2})\]/g)].map(m => m[1]);

const N = 19;
const idx = (c, r) => r * N + c;
const parseCoord = s => [s.charCodeAt(0) - 97, s.charCodeAt(1) - 97];
function neighbors(c, r) {
  const a = [];
  if (c > 0) a.push([c - 1, r]);
  if (c < N - 1) a.push([c + 1, r]);
  if (r > 0) a.push([c, r - 1]);
  if (r < N - 1) a.push([c, r + 1]);
  return a;
}
function groupLibs(board, c, r) {
  const color = board[idx(c, r)], stack = [[c, r]], seen = new Set([idx(c, r)]), grp = [];
  const libSet = new Set();
  while (stack.length) {
    const [x, y] = stack.pop();
    grp.push([x, y]);
    for (const [nx, ny] of neighbors(x, y)) {
      const i = idx(nx, ny);
      if (board[i] === 0) libSet.add(i);
      else if (board[i] === color && !seen.has(i)) { seen.add(i); stack.push([nx, ny]); }
    }
  }
  return { grp, libs: libSet.size };
}

let board = new Int8Array(N * N);
let capB = 0, capW = 0;
moves.forEach((mv, i) => {
  const color = (i % 2 === 0) ? 1 : 2, enemy = color === 1 ? 2 : 1;
  const [c, r] = parseCoord(mv);
  board[idx(c, r)] = color;
  for (const [nx, ny] of neighbors(c, r)) {
    if (board[idx(nx, ny)] === enemy) {
      const { grp, libs } = groupLibs(board, nx, ny);
      if (libs === 0) { grp.forEach(([gx, gy]) => board[idx(gx, gy)] = 0); if (enemy === 1) capB += grp.length; else capW += grp.length; }
    }
  }
});

console.log("moves=" + moves.length);
console.log("capturedB=" + capB + " capturedW=" + capW);
console.log("board=" + Array.from(board).join(""));
