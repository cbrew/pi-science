import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { initialState, normalizeState, addRecord, triage, assess, renderReport, MODES, IMPACTS, STATUSES } from "./core.js";
import { sciencePrompt } from "./prompt.js";

// Project-scoped persistent ledger. It intentionally persists beyond Pi sessions.
export default function scienceExtension(pi: ExtensionAPI) {
  let queue: Promise<unknown> = Promise.resolve();
  function paths(cwd: string) { const dir = join(cwd, ".pi", "science"); return {dir, file: join(dir, "state.json")}; }
  async function read(cwd: string) {
    try { return normalizeState(JSON.parse(await readFile(paths(cwd).file, "utf8"))); }
    catch (e: any) { if (e?.code === "ENOENT") return initialState(); throw e; }
  }
  async function save(cwd: string, state: any) {
    const {dir, file} = paths(cwd);
    await mkdir(dir, {recursive: true});
    // Serialize writers to avoid lost updates within a Pi process.
    const temp = `${file}.${process.pid}.tmp`;
    await writeFile(temp, JSON.stringify(state, null, 2) + "\n");
    await rename(temp, file);
  }
  function mutate<T>(cwd: string, change: (s: any) => T): Promise<T> {
    const task = queue.catch(() => {}).then(async () => {
      const state = await read(cwd);
      const result = change(state);
      state.updated = new Date().toISOString();
      await save(cwd, state);
      return result;
    });
    queue = task;
    return task;
  }
  const result = (value: unknown) => ({content: [{type: "text" as const, text: typeof value === "string" ? value : JSON.stringify(value, null, 2)}], details: {}});

  pi.on("before_agent_start", async (event, ctx) => {
    const s = await read(ctx.cwd);
    // Modify a structured section rather than forcing a potentially stale system prompt.
    event.systemPromptOptions.sections.scientific_harness = sciencePrompt(s);
  });

  pi.registerCommand("science", {
    description: "Scientific mode: /science question TEXT | mode NAME | status | report | reset",
    handler: async (args, ctx) => {
      const [verb, ...tail] = (args || "status").trim().split(/\s+/);
      const value = tail.join(" ").trim();
      if (verb === "status") {
        const s = await read(ctx.cwd);
        ctx.ui.notify(`Science [${s.mode}] ${s.question || "question unset"} | ${s.claims.length} claims, ${s.evidence.length} evidence | ready=${assess(s).ready}`, "info");
      } else if (verb === "question" && value) {
        await mutate(ctx.cwd, s => { s.question = value; s.hypotheses = []; s.claims = []; s.evidence = []; s.issues = []; s.decisions = []; });
        ctx.ui.notify("New research question recorded; prior ledger cleared.", "success");
      } else if (verb === "mode" && MODES.includes(value)) {
        await mutate(ctx.cwd, s => { s.mode = value; });
        ctx.ui.notify(`Science mode: ${value}`, "success");
      } else if (verb === "report") {
        const s = await read(ctx.cwd);
        const dest = join(paths(ctx.cwd).dir, "report.md");
        await mkdir(paths(ctx.cwd).dir, {recursive:true});
        await writeFile(dest, renderReport(s));
        ctx.ui.notify(`Report written to ${dest}`, "success");
      } else if (verb === "reset") {
        if (ctx.hasUI && !(await ctx.ui.confirm("Reset science ledger", "Clear this project's research question and records?"))) return;
        await mutate(ctx.cwd, s => Object.assign(s, initialState()));
        ctx.ui.notify("Research ledger reset", "info");
      } else {
        ctx.ui.notify("Usage: /science question TEXT | mode exploratory|confirmatory|benchmarking|replication | status | report | reset", "warning");
      }
    }
  });

  pi.registerTool({
    name: "science_record", label: "Record research state",
    description: "Record a research hypothesis, claim, observation, issue, or research decision in the persistent project ledger. Do not invent observational evidence.",
    parameters: Type.Object({
      kind: Type.Union([Type.Literal("hypothesis"), Type.Literal("claim"), Type.Literal("evidence"), Type.Literal("issue"), Type.Literal("decision")]),
      text: Type.String({description: "Claim, hypothesis, issue, or decision text; for evidence, the actual observation."}),
      claimId: Type.Optional(Type.String()),
      status: Type.Optional(Type.Union(STATUSES.map(x => Type.Literal(x)) as any)),
      impact: Type.Optional(Type.Union(IMPACTS.map(x => Type.Literal(x)) as any)),
      source: Type.Optional(Type.String({description: "Command, file, dataset version, revision, or source reference."})),
      limitation: Type.Optional(Type.String()),
    }),
    async execute(_id, p, _signal, _update, ctx) {
      const section: Record<string,string> = {hypothesis:"hypotheses",claim:"claims",evidence:"evidence",issue:"issues",decision:"decisions"};
      if (p.kind === "evidence" && (!p.source?.trim() || !p.limitation?.trim())) throw new Error("Evidence needs source and limitation (use 'none identified' if applicable)");
      if (p.kind === "issue" && !p.impact) throw new Error("Issue needs impact");
      const id = await mutate(ctx.cwd, s => addRecord(s, section[p.kind], p.kind === "evidence" ? {kind:"observation", observation:p.text, claimId:p.claimId, source:p.source, limitation:p.limitation} : p.kind === "claim" ? {text:p.text,status:p.status || "open"} : p.kind === "issue" ? {text:p.text,impact:p.impact,resolved:false} : p.kind === "decision" ? {action:p.text, disposition:"recorded",reason:p.limitation || ""} : {text:p.text}));
      return result({id, saved:true});
    }
  });
  pi.registerTool({
    name: "science_triage", label: "Research relevance triage",
    description: "Classify a proposed detour by its impact on the scientific answer. Defer engineering-only work unless the user requests it.",
    parameters: Type.Object({
      action: Type.String(), impact: Type.Union(IMPACTS.map(x => Type.Literal(x)) as any),
      relation: Type.String({description:"Specific effect on research validity, evidence, or execution; say 'none' if none."})
    }),
    async execute(_id, p, _signal, _update, ctx) {
      const judgment = triage(p);
      await mutate(ctx.cwd, s => addRecord(s,"decisions",{action:p.action,disposition:judgment.category,reason:`${p.relation} — ${judgment.rationale}`}));
      return result(judgment);
    }
  });
  pi.registerTool({
    name: "science_sufficiency", label: "Evaluate evidence completeness",
    description: "Inspect research ledger and clerical readiness. This does not replace a scientific assessment; review actual evidence critically.",
    parameters: Type.Object({}),
    async execute(_id, _p, _signal, _update, ctx) {
      const s = await read(ctx.cwd);
      return result({...assess(s), question:s.question, claims:s.claims, evidence:s.evidence, openIssues:s.issues.filter((x:any)=>!x.resolved)});
    }
  });
  pi.registerTool({
    name: "science_update", label: "Update claim or issue",
    description: "Update an existing claim status or resolve an issue. Require explanation, and never mark a claim supported without adequate evidence.",
    parameters: Type.Object({id:Type.String(), status:Type.Optional(Type.Union(STATUSES.map(x=>Type.Literal(x)) as any)), resolved:Type.Optional(Type.Boolean()), reason:Type.String()}),
    async execute(_id,p,_signal,_update,ctx) {
      const updated = await mutate(ctx.cwd, s => {
        const item = [...s.claims,...s.issues].find((x:any)=>x.id === p.id);
        if (!item) throw new Error(`No claim/issue ${p.id}`);
        if (p.status !== undefined) { if (!s.claims.includes(item)) throw new Error("Only claims have status"); item.status = p.status; }
        if (p.resolved !== undefined) { if (!s.issues.includes(item)) throw new Error("Only issues have resolved"); item.resolved = p.resolved; }
        if (p.status === undefined && p.resolved === undefined) throw new Error("Specify status or resolved");
        item.reason = p.reason;
        return item;
      });
      return result(updated);
    }
  });
}
