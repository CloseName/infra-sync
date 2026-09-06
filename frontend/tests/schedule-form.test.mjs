import test from "node:test";
import assert from "node:assert/strict";
import { intervalDraft, intervalSeconds, schedulePresets } from "../src/ui/scheduleForm.ts";
import { interval } from "../src/ui/format.ts";
import { fetchSourceRuns } from "../src/api/runs.ts";
import { run } from "./fixtures.mjs";
test("presets and all supported second values round-trip exactly", () => {
 assert.deepEqual(schedulePresets, [300,600,900,1800,3600,7200,21600]);
 for (let value=60; value<=86400; value++) assert.equal(intervalSeconds(intervalDraft(value)), value);
 for (const value of [1,30,59,86401,2147483647]) {
   const draft = intervalDraft(value);
   assert.equal(draft.preset, "custom");
   assert.equal(intervalSeconds(draft), null);
 }
 assert.equal(intervalDraft(601).amount, "601");
 assert.equal(intervalDraft(9000).preset, "custom");
 assert.equal(interval(9000), "2 h 30 min");
 assert.equal(interval(601), "10 min 1 s");
});
test("custom unit conversion is exact and validates whole-second update bounds", () => {
 for (const [amount,unit,expected] of [["61","seconds",61],["1.15","minutes",69],["90","minutes",5400],["2.5","hours",9000],["0.5","hours",1800],["","seconds",null],["1.001","minutes",null],["-1","hours",null],["25","hours",null],["Infinity","seconds",null],["1e3","seconds",null]])
 assert.equal(intervalSeconds({preset:"custom",amount,unit}), expected);
});
test("source run request filters exact identity and rejects foreign results", async context => {
 const mock = context.mock.method(globalThis,"fetch",async path => {
   assert.equal(new URL(path,"https://test.invalid").searchParams.get("source_instance"),"source-1");
   return Response.json({runs:[run()]});
 });
 assert.equal((await fetchSourceRuns("source-1",new AbortController().signal)).length,1);
 mock.mock.mockImplementation(async()=>Response.json({runs:[{...run(),source_instance:"source-2"}]}));
 await assert.rejects(fetchSourceRuns("source-1",new AbortController().signal),/invalid data/);
});
