// verify.mjs — verify OEIS A001002 against direct enumeration of (2,3)-rooted trees.
//
// Definition (per source clarification): a (2,3)-rooted tree is a PLANE (ordered)
// rooted tree in which every internal node has 2 or 3 children. The size parameter
// is the number of leaves. N(L) = number of such trees with L leaves.
//
// Claim under test: N(L) = A001002(L-1) for all L >= 1.
// (Equivalently, the OEIS comment "a(n+1) is number of (2,3)-rooted trees on n nodes"
//  holds with "on n nodes" = trees with n+2 leaves.)
//
// Reference data: the b-file copy in this directory (first 40 terms of A001002,
// offset 0), fetched from https://oeis.org/A001002/b001002.txt. Terms are read
// from disk, never hand-transcribed, and the index column is validated.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const OEIS = readFileSync(join(here, 'a001002_bfile.txt'), 'utf8')
  .split(/\r?\n/)
  .filter(l => l && !l.startsWith('#'))
  .map(l => { const [n, v] = l.trim().split(/\s+/); return { n: Number(n), v: BigInt(v) }; });
for (let i = 0; i < OEIS.length; i++) if (OEIS[i].n !== i) throw new Error(`b-file index corruption at line ${i}`);
const aOf = i => OEIS[i].v;

// Method 1: leaf-count recurrence for plane ordered (2,3)-trees.
// A tree with L leaves is: a bare leaf (L=1), or a root with 2 children whose
// subtrees have i and L-i leaves, or a root with 3 children whose subtrees have
// i, j, L-i-j leaves. Children are ordered, so every composition counts once.
function countByLeaves(maxL) {
  const t = [0n, 1n];
  for (let L = 2; L <= maxL; L++) {
    let c = 0n;
    for (let i = 1; i <= L - 1; i++) c += t[i] * t[L - i];
    for (let i = 1; i <= L - 2; i++)
      for (let j = 1; j <= L - 1 - i; j++)
        c += t[i] * t[j] * t[L - i - j];
    t[L] = c;
  }
  return t;
}

// Method 2 (independent formulation): the dissection recurrence from the OEIS
// entry itself — a(n) = sum a(i)a(n-1-i) + sum a(i)a(j)a(n-2-i-j), a(0)=1.
// This counts dissections of a convex (n+2)-gon into triangles and quadrilaterals.
function dissectionRecurrence(maxN) {
  const a = [1n];
  for (let n = 1; n <= maxN; n++) {
    let c = 0n;
    for (let i = 0; i <= n - 1; i++) c += a[i] * a[n - 1 - i];
    for (let i = 0; i <= n - 2; i++)
      for (let j = 0; j <= n - 2 - i; j++)
        c += a[i] * a[j] * a[n - 2 - i - j];
    a[n] = c;
  }
  return a;
}

// Method 3 (independent, brute force): generate every plane ordered (2,3)-tree
// with L leaves as a canonical string and count distinct ones.
function bruteForce(maxL) {
  const byLeaves = [[], [['.']]]; // byLeaves[L] = array of canonical strings
  for (let L = 2; L <= maxL; L++) {
    const out = [];
    for (let i = 1; i <= L - 1; i++)
      for (const a of byLeaves[i]) for (const b of byLeaves[L - i])
        out.push(`(${a},${b})`);
    for (let i = 1; i <= L - 2; i++)
      for (let j = 1; j <= L - 1 - i; j++)
        for (const a of byLeaves[i]) for (const b of byLeaves[j]) for (const c of byLeaves[L - i - j])
          out.push(`(${a},${b},${c})`);
    byLeaves[L] = out;
  }
  return byLeaves.map(arr => BigInt(arr.length));
}

const MAXL = OEIS.length; // number of leaves to compare
const t1 = countByLeaves(MAXL);
const t2 = dissectionRecurrence(MAXL - 1);
const t3 = bruteForce(9); // brute force is exponential; cap at 9 leaves

let allMatch = true;
console.log(' L | N(L) trees | A001002(L-1) | match | dissection a(L-1) | brute-force(L<=9)');
for (let L = 1; L <= MAXL; L++) {
  const a = aOf(L - 1);
  const m = t1[L] === a;
  if (!m) allMatch = false;
  const bf = L <= 9 ? t3[L] : '-';
  const bfOk = L <= 9 ? (t3[L] === t1[L] ? 'ok' : 'MISMATCH') : '';
  console.log(
    String(L).padStart(2), '|', String(t1[L]).padStart(12), '|', String(a).padStart(12),
    '|', m ? 'yes' : 'NO', '|', String(t2[L - 1]).padStart(12), '|', String(bf).padStart(12), bfOk
  );
}
console.log('\nMethod 1 (leaf DP) vs A001002(L-1) for L=1..' + MAXL + ': ' + (allMatch ? 'ALL MATCH' : 'MISMATCH FOUND'));
console.log('Method 2 (dissection recurrence) vs A001002:', t2.every((v, i) => v === aOf(i)) ? 'ALL MATCH' : 'MISMATCH');
console.log('Method 3 (brute force, L<=9) vs Method 1:', t3.slice(1, 10).every((v, i) => v === t1[i + 1]) ? 'ALL MATCH' : 'MISMATCH');
process.exitCode = allMatch ? 0 : 1;
