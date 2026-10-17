// enumerate.js — enumerate (2,3)-trees under several precise definitions and
// compare against A001002.
import assert from 'node:assert';

// A001002 (offset 0): 1,1,3,10,38,154,654,2871,12925,59345,276835,1308320,6250832,30142360
const OEIS = [1,1,3,10,38,154,654,2871,12925,59345,276835,1308320,6250832,30142360,146510216,717061938,3530808798,17478955570,86941210950,434299921440,2177832612120,10959042823020,55322023332420,280080119609550,1421744205767418,7234759677699954];
const OEIS_L = OEIS.map((v,i)=>`A001002(${i})=${v}`).join('\n');

// ---------- Definition A: PLANE (ordered) rooted trees, every internal node has 2 or 3 children ----------
// count by total nodes
function planeByNodes(N) {
  const t = [0n]; // t[n] = #plane (2,3)-trees with n nodes
  t[1] = 1n;      // single root (leaf)
  for (let n = 2; n <= N; n++) {
    let c = 0n;
    // root with 2 children: child sizes i, j, i+j = n-1
    for (let i = 1; i <= n-2; i++) c += t[i] * t[n-1-i];
    // root with 3 children: i+j+k = n-1
    for (let i = 1; i <= n-3; i++)
      for (let j = 1; j <= n-2-i; j++)
        c += t[i] * t[j] * t[n-1-i-j];
    t[n] = c;
  }
  return t;
}
// count by leaves
function planeByLeaves(N) {
  const t = [0n, 1n]; // t[L] = #plane (2,3)-trees with L leaves
  for (let L = 2; L <= N; L++) {
    let c = 0n;
    for (let i = 1; i <= L-1; i++) c += t[i] * t[L-i];       // root with 2 children
    for (let i = 1; i <= L-2; i++)
      for (let j = 1; j <= L-1-i; j++)
        c += t[i] * t[j] * t[L-i-j];                          // root with 3 children
    t[L] = c;
  }
  return t;
}
// count by internal nodes
function planeByInternals(N) {
  const t = [1n]; // t[k] = #plane (2,3)-trees with k internal nodes; k=0: single leaf
  for (let k = 1; k <= N; k++) {
    let c = 0n;
    for (let i = 0; i <= k-1; i++) c += t[i] * t[k-1-i];
    for (let i = 0; i <= k-2; i++)
      for (let j = 0; j <= k-2-i; j++)
        c += t[i] * t[j] * t[k-2-i-j];
    t[k] = c;
  }
  return t;
}

// ---------- Definition B: UNORDERED rooted trees, every internal node has 2 or 3 children ----------
// canonical form: "(children sorted)" and enumerate by size
function unorderedByNodes(N) {
  const forms = []; // forms[n] = array of canonical strings with n nodes
  forms[1] = ['.'];
  for (let n = 2; n <= N; n++) {
    const set = new Set();
    // multisets of children sizes summing to n-1, each part in [minChildSize..], count 2 or 3 children only
    const parts2 = [];
    for (let a = 1; a <= n-2; a++) parts2.push([a, n-1-a]);
    for (const [a,b] of parts2) {
      for (const fa of a < forms.length ? forms[a] : []) for (const fb of b < forms.length ? forms[b] : []) {
        const kids = [fa, fb].sort();
        set.add('(' + kids.join(',') + ')');
      }
    }
    for (let a = 1; a <= n-3; a++) for (let b = a; b <= n-2-a; b++) {
      const c = n-1-a-b; if (c < b) continue;
      for (const fa of forms[a]||[]) for (const fb of forms[b]||[]) for (const fc of forms[c]||[]) {
        const kids = [fa, fb, fc].sort();
        set.add('(' + kids.join(',') + ')');
      }
    }
    forms[n] = [...set];
  }
  return [0n, ...forms.map(f => BigInt(f.length))];
}

// ---------- Definition C: recurrence from OEIS (plane, weight = 2-nodes+2*3-nodes) ----------
function weightRecurrence(N) {
  const a = [1n]; // a[0] = empty
  for (let n = 1; n <= N; n++) {
    let c = 0n;
    for (let i = 0; i <= n-1; i++) c += a[i] * a[n-1-i];
    for (let i = 0; i <= n-2; i++) for (let j = 0; j <= n-2-i; j++) c += a[i] * a[j] * a[n-2-i-j];
    a[n] = c;
  }
  return a;
}

const N = 14;

console.log('OEIS A001002:');
console.log(OEIS_L);

const cases = [
  ['plane-by-total-nodes (n=1..)', planeByNodes(N).slice(1)],
  ['plane-by-leaves (L=1..)', planeByLeaves(N).slice(1)],
  ['plane-by-internal-nodes (k=0..)', planeByInternals(N)],
  ['unordered-by-total-nodes (n=1..)', unorderedByNodes(N).slice(1)],
  ['weight recurrence a(n) = 2-nodes + 2*(3-nodes)', weightRecurrence(N)],
];

for (const [name, seq] of cases) {
  console.log('\n' + name + ':');
  console.log('  ' + seq.slice(0, 12).join(', '));
  // find shift s such that seq[i] == OEIS[i+s] for as many i as possible
  for (let s = -3; s <= 3; s++) {
    let match = 0;
    for (let i = 0; i < Math.min(seq.length, 10); i++) {
      const j = i + s;
      if (j >= 0 && j < OEIS.length && seq[i] === BigInt(OEIS[j])) match++;
    }
    console.log(`  shift ${s>=0?'+':''}${s}: ${match}/10 prefix terms match A001002(i+${s})`);
  }
}
