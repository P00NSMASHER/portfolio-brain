// Portfolio Brain independent Cloudflare cron. NO HTTP dispatch endpoint.
// The signing secret remains a Cloudflare Worker secret, never source or logs.
export const REPO = "P00NSMASHER/portfolio-brain";
export const WORKER = "portfolio-brain-recovery";
export const CRON = "*/10 * * * *";
const API = "https://api.github.com/repos/" + REPO;
const FRESH_MS = 25 * 60 * 1000;
const ACTIVE_STALE_MS = 20 * 60 * 1000;
const CLOCK_SKEW_MS = 60 * 1000;

function asBytes(b64) {
  const clean = b64.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(clean), c => c.charCodeAt(0));
}
function base64url(bytes) {
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function fail(code) { throw new Error(code); }
function validSha(x) { return typeof x === "string" && /^[a-f0-9]{40}$/.test(x); }
async function githubGet(path, token) {
  const r = await fetch(API + path, {
    headers: { "Accept": "application/vnd.github+json",
      "User-Agent": WORKER,
      ...(token ? { "Authorization": "Bearer " + token } : {}) },
    redirect: "error"
  });
  if (!r.ok) fail("GITHUB_GET_" + r.status);
  return await r.json();
}
export function decide(runs, source, nowMs) {
  if (!validSha(source)) fail("SOURCE_INVALID");
  if (!runs || !Array.isArray(runs.workflow_runs) || !Number.isInteger(nowMs)) fail("RUN_INVENTORY_INVALID");
  if (runs.workflow_runs.length > 100 || runs.total_count < runs.workflow_runs.length) fail("RUN_INVENTORY_INVALID");
  const present = runs.workflow_runs.filter(r => r.head_sha === source && r.head_branch === "main");
  for (const r of present) {
    if (!Number.isInteger(r.id) || !validSha(r.head_sha) || typeof r.created_at !== "string") fail("RUN_ID_OR_HEAD_SHA_INVALID");
    const t=Date.parse(r.created_at);
    if (!Number.isFinite(t) || t > nowMs + CLOCK_SKEW_MS) fail("RUN_TIME_INVALID");
  }
  const active = present.filter(r => r.status !== "completed").sort((a,b) => Date.parse(b.created_at)-Date.parse(a.created_at));
  if (active.length) {
    const age=nowMs-Date.parse(active[0].created_at);
    return {status:age<=ACTIVE_STALE_MS?"ACTIVE":"STALE_ACTIVE_BLOCKED",dispatch:false,run_id:active[0].id,age_ms:age};
  }
  const successful = present.filter(r => r.status === "completed" && r.conclusion === "success").sort((a,b) => Date.parse(b.updated_at)-Date.parse(a.updated_at));
  if (successful.length) {
    const last=successful[0], when=Date.parse(last.updated_at);
    if (!Number.isFinite(when) || when > nowMs + CLOCK_SKEW_MS) fail("SUCCESS_TIME_INVALID");
    const age=nowMs-when;
    if (age<FRESH_MS) return {status:"FRESH",dispatch:false,run_id:last.id,age_ms:age};
  }
  return {status:"DUE",dispatch:true,last_success_id:successful[0]?.id ?? null};
}
export async function tick(controller,env) {
  const nowMs=Date.now();
  const scheduledMs=controller?.scheduledTime;
  if (!Number.isFinite(scheduledMs) || typeof controller.cron !== "string" || controller.cron !== CRON) fail("NOT_EXPECTED_CLOUDFLARE_CRON");
  if (scheduledMs > nowMs + CLOCK_SKEW_MS || nowMs-scheduledMs>15*60*1000) fail("STALE_CLOUDFLARE_SCHEDULE");
  const token=env.GITHUB_ACTIONS_TOKEN;
  const main=await githubGet("/branches/main",token);
  const sha=main?.commit?.sha;
  if (!validSha(sha)) fail("MAIN_IDENTITY_INVALID");
  const runs=await githubGet("/actions/workflows/brain-cycle.yml/runs?branch=main&per_page=100",token);
  const result=decide(runs,sha,nowMs);
  if (!result.dispatch) { console.log(JSON.stringify({worker:WORKER,status:result.status,source:sha,run_id:result.run_id??null,scheduled_at:new Date(scheduledMs).toISOString()})); return result; }
  if (typeof token !== "string" || token.length<10) fail("GITHUB_ACTIONS_TOKEN_MISSING");
  if (typeof env.SIGNING_KEY_PKCS8 !== "string") fail("SIGNING_KEY_MISSING");
  const key=await crypto.subtle.importKey("pkcs8",asBytes(env.SIGNING_KEY_PKCS8),{name:"ECDSA",namedCurve:"P-256"},false,["sign"]);
  const payload={kind:"cloudflare_cron_v1",worker:WORKER,cron:CRON,source_sha:sha,
    scheduled_at:new Date(scheduledMs).toISOString(),issued_at:new Date(nowMs).toISOString(),
    slot:Math.floor(scheduledMs/600000)};
  const raw=new TextEncoder().encode(JSON.stringify(payload));
  const signature=new Uint8Array(await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"},key,raw));
  if (signature.length !== 64) fail("INVALID_SIGNATURE_FORMAT");
  const body={ref:"main",inputs:{cloudflare_attestation:base64url(raw),cloudflare_signature:base64url(signature)}};
  const response=await fetch(API+"/actions/workflows/brain-cycle.yml/dispatches", {
    method:"POST",redirect:"error",headers:{"Accept":"application/vnd.github+json",
       "Content-Type":"application/json","User-Agent":WORKER,
       "Authorization":"Bearer "+token},body:JSON.stringify(body)
  });
  if (response.status!==204) fail("GITHUB_DISPATCH_FAILED_"+response.status);
  console.log(JSON.stringify({worker:WORKER,status:"DISPATCH_ACCEPTED_NOT_COMPLETED",
     source:sha,slot:payload.slot,scheduled_at:payload.scheduled_at}));
  return {status:"DISPATCH_ACCEPTED_NOT_COMPLETED",source_sha:sha,slot:payload.slot,dispatch:true};
}
export default {
  async scheduled(controller,env,ctx) {
    ctx.waitUntil(tick(controller,env).catch(error=> {
      const code=error instanceof Error?error.message:"UNKNOWN_ERROR";
      console.error(JSON.stringify({worker:WORKER,status:"FAILED",code}));
      throw new Error(code);
    }));
  },
  async fetch() { return new Response("Not Found",{status:404}); }
};
