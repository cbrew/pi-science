import test from 'node:test';
import assert from 'node:assert/strict';
import {initialState,normalizeState,addRecord,triage,assess,renderReport} from '../src/core.js';
import {sciencePrompt} from '../src/prompt.js';
test('policy triages irrelevant engineering as deferred',()=>assert.equal(triage({impact:'engineering-only',action:'refactor',relation:'none'}).category,'DEFER'));
test('experimental correctness takes priority',()=>assert.equal(triage({impact:'validity-critical',action:'fix metric',relation:'biased comparison'}).category,'DO_NOW'));
test('question and claims required for clerical readiness',()=>{ const s=initialState(); assert.equal(assess(s).ready,false); s.question='Which is faster?'; addRecord(s,'claims',{text:'A faster',status:'supported'}); assert.equal(assess(s).ready,true); addRecord(s,'issues',{text:'unfair input',impact:'validity-critical',resolved:false}); assert.equal(assess(s).ready,false); });
test('report contains observations and provenance',()=>{const s=initialState(); s.question='Q';addRecord(s,'evidence',{kind:'observation',observation:'4 ms',source:'run.log',limitation:'single trial'}); assert.match(renderReport(s),/run.log/);});
test('modes affect research contract',()=>{const s=normalizeState({schema:1,mode:'benchmarking'}); assert.match(sciencePrompt(s),/hardware contention/);});
