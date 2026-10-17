export const MODES = ["exploratory", "confirmatory", "benchmarking", "replication"];
export const IMPACTS = ["validity-critical", "evidence-critical", "execution-blocking", "reproducibility", "engineering-only", "deployment-only", "speculative"];
export const STATUSES = ["open", "supported", "contradicted", "inconclusive"];

export function initialState() {
  return {schema: 1, mode: "exploratory", question: "", hypotheses: [], claims: [], evidence: [], issues: [], decisions: [], updated: new Date().toISOString()};
}
export function normalizeState(obj) {
  if (!obj || obj.schema !== 1) return initialState();
  const base = initialState();
  return {
    ...base, ...obj,
    mode: MODES.includes(obj.mode) ? obj.mode : base.mode,
    question: typeof obj.question === "string" ? obj.question : "",
    hypotheses: Array.isArray(obj.hypotheses) ? obj.hypotheses : [],
    claims: Array.isArray(obj.claims) ? obj.claims : [],
    evidence: Array.isArray(obj.evidence) ? obj.evidence : [],
    issues: Array.isArray(obj.issues) ? obj.issues : [],
    decisions: Array.isArray(obj.decisions) ? obj.decisions : []
  };
}
export function triage({impact, relation, action}) {
  if (!IMPACTS.includes(impact)) throw new Error(`Invalid impact: ${impact}`);
  if (!relation?.trim() || !action?.trim()) throw new Error("Action and research relation are required");
  const category = {
    "validity-critical": "DO_NOW", "evidence-critical": "DO_NOW", "execution-blocking": "DO_NOW",
    "reproducibility": "MINIMAL_FIX", "engineering-only": "DEFER", "deployment-only": "DEFER", "speculative": "DEFER"
  }[impact];
  return {category, rationale: category === "DO_NOW" ? "Necessary to establish trustworthy evidence or execute the experiment." : category === "MINIMAL_FIX" ? "Capture sufficient provenance; avoid unrelated hardening." : "Do not work on this unless a concrete threat to the research answer is demonstrated."};
}
export function assess(state) {
  const open = state.claims.filter(x => x.status === "open");
  const blockers = state.issues.filter(x => !x.resolved && ["validity-critical", "evidence-critical", "execution-blocking"].includes(x.impact));
  return {ready: !!state.question.trim() && state.claims.length > 0 && open.length === 0 && blockers.length === 0,
    claimCount: state.claims.length, openClaims: open.length, criticalIssues: blockers.length,
    caution: "This is an administrative completeness check, not an automatic judgment of scientific validity. The investigator must still evaluate evidential sufficiency."};
}
export function addRecord(state, section, data) {
  if (!["hypotheses", "claims", "evidence", "issues", "decisions"].includes(section)) throw new Error("Unknown record type");
  const id = `${section[0]}${state[section].length + 1}`;
  state[section].push({id, ...data, at: new Date().toISOString()});
  state.updated = new Date().toISOString();
  return id;
}
export function renderReport(s) {
  const fmt = (items, printer) => items.length ? items.map(printer).join("\n") : "(none)";
  const {ready, caution} = assess(s);
  return `# Research report\n\n**Question:** ${s.question || "(not set)"}\n\n**Mode:** ${s.mode}\n\n## Hypotheses\n${fmt(s.hypotheses,x=>`- ${x.id}: ${x.text}`)}\n\n## Claims\n${fmt(s.claims,x=>`- ${x.id} [${x.status}]: ${x.text}`)}\n\n## Evidence\n${fmt(s.evidence,x=>`- ${x.id} (${x.kind}; claim ${x.claimId || "unlinked"}): ${x.observation} | source: ${x.source || "not recorded"} | limitation: ${x.limitation || "not recorded"}`)}\n\n## Open issues\n${fmt(s.issues.filter(x=>!x.resolved),x=>`- ${x.id} [${x.impact}]: ${x.text}`)}\n\n## Deferred work and decisions\n${fmt(s.decisions,x=>`- ${x.id}: ${x.action} [${x.disposition}] — ${x.reason}`)}\n\n## Sufficiency\nAdministrative completeness: ${ready ? "complete" : "incomplete"}. ${caution}\n\n## Scientific conclusion\n(To be written by the investigator, distinguishing observations, inferences, and uncertainty.)\n`;
}
