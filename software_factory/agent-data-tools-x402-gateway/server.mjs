import http from 'node:http';
import https from 'node:https';

const PORT = Number(process.env.PORT || 3000);
const PAY_TO = '0x708f7b52b56eafd7fc1de65fc7752ed732914021';
const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
const NETWORK = 'eip155:8453';
const CONTACT = 'jayp19386@gmail.com';
const FACILITATOR = 'https://facilitator.payai.network';
const TREASURY_API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates';

const routes = {
  '/api/pa-entity-one': ['https://pa-entity-x402.floot.app/_api/pa-entity-one','0.001000','Best Pennsylvania entity match',['Pennsylvania','Business Registry','Entity Resolution'],[['q',true,{type:'string',minLength:2},'OpenAI']]],
  '/api/pa-business': ['https://pa-entity-x402.floot.app/_api/pa-business','0.005000','Search Pennsylvania business registry',['Pennsylvania','Business Registry','Company Identity'],[['q',true,{type:'string',minLength:2},'OpenAI'],['limit',false,{type:'integer',minimum:1,maximum:25},5]]],
  '/api/vendor-intake-gate': ['https://api-v2.appdeploy.ai/app/pa-entity-lookup-x402-4fbm4s/api/vendor-intake-gate','0.020000','Pennsylvania vendor-intake decision gate',['Vendor Intake','Agent Decision','Human Review'],[['name',true,{type:'string',minLength:2},'OpenAI OpCo'],['address',true,{type:'string',minLength:6},'600 North Second Street, Harrisburg, PA 17101'],['domain',true,{type:'string',minLength:3},'openai.com']]],
  '/api/sec-filings': ['https://api-v2.appdeploy.ai/app/sec-recent-filings-x402-f9qatj/api/sec-filings','0.005000','Recent SEC EDGAR filings',['SEC','EDGAR','Filings'],[['ticker',false,{type:'string'},'AAPL'],['cik',false,{type:'string'},'0000320193'],['form',false,{type:'string'},'10-K'],['limit',false,{type:'integer',minimum:1,maximum:25},5]]],
  '/api/us-address-geocode': ['https://api-v2.appdeploy.ai/app/us-census-address-geocoder-x402-23mj4x/api/us-address-geocode','0.005000','Census address geocoder',['Census','Geocoding','Address'],[['address',true,{type:'string',minLength:6},'4600 Silver Hill Rd, Washington, DC 20233']]],
  '/api/ofac-sdn-screen': ['https://api-v2.appdeploy.ai/app/ofac-sdn-name-screen-x402-m9ko96/api/ofac-sdn-screen','0.005000','OFAC SDN name screen',['OFAC','Sanctions','Compliance'],[['name',true,{type:'string',minLength:2},'VLADIMIR PUTIN'],['limit',false,{type:'integer',minimum:1,maximum:10},5],['minScore',false,{type:'integer',minimum:70,maximum:100},85]]],
  '/api/domain-rdap': ['https://api-v2.appdeploy.ai/app/domain-rdap-lookup-x402-spdfnq/api/domain-rdap','0.005000','Domain RDAP lookup',['Domain','RDAP','Registration'],[['domain',true,{type:'string',minLength:3,maxLength:253},'example.com']]],
  '/api/treasury-average-rates': ['https://api-v2.appdeploy.ai/app/treasury-average-interest-rates-x402-xeqftl/api/treasury-average-rates','0.005000','Treasury average interest rates',['Treasury','Interest Rates','Macro'],[['security',false,{type:'string',maxLength:100},'Total Marketable']]]
};

const origin = req => `${String(req.headers['x-forwarded-proto']||'https').split(',')[0].trim()}://${String(req.headers['x-forwarded-host']||req.headers.host||'localhost').split(',')[0].trim()}`;
const send = (res,status,value,type='application/json; charset=utf-8') => {
  const body = type.startsWith('application/json') ? JSON.stringify(value,null,2) : String(value);
  res.writeHead(status,{'content-type':type,'content-length':Buffer.byteLength(body),'cache-control':status===200?'public, max-age=300':'no-store','access-control-allow-origin':'*'});
  res.end(body);
};
const desc = path => path==='/api/vendor-intake-gate'
  ? 'Combine PA registry identity, Census address consistency, OFAC SDN candidate-name screening and RDAP domain evidence into proceed or human_review with explicit review triggers. Not legal or sanctions-clearance approval.'
  : routes[path][2];

function openapi(req){
  const paths={};
  for(const [path,r] of Object.entries(routes)){
    paths[path]={get:{operationId:path.slice(5).replaceAll('-','_'),summary:r[2],description:desc(path),tags:r[3],security:[],
      'x-payment-info':{price:{mode:'fixed',currency:'USD',amount:r[1]},protocols:[{x402:{}}],network:NETWORK,payTo:PAY_TO},
      parameters:r[4].map(([name,required,schema,example])=>({name,in:'query',required,schema,example})),
      responses:{'200':{description:'Paid JSON result',content:{'application/json':{schema:{type:'object',additionalProperties:true}}}},'400':{description:'Invalid input'},'402':{description:'Payment Required'},'502':{description:'Upstream unavailable'},'503':{description:'Payment service unavailable'}}}};
  }
  return {openapi:'3.1.0',info:{title:'Agent Data Tools x402 Gateway',version:'1.0.0',description:'Eight same-origin pay-per-call x402 v2 endpoints backed by authoritative public data and a composed vendor-intake decision gate.',contact:{email:CONTACT},'x-guidance':'Use /api/vendor-intake-gate for a bounded proceed or human_review workflow decision. Use lower-cost routes for direct lookups. Unpaid calls return x402 v2 HTTP 402 challenges; retry the same gateway URL with PAYMENT-SIGNATURE.'},servers:[{url:origin(req)}],paths};
}
function discovery(req){
  return {x402Version:2,name:'Agent Data Tools x402',description:'Eight same-origin x402 endpoints.',network:NETWORK,asset:USDC,payTo:PAY_TO,
    resources:Object.entries(routes).map(([path,r])=>({resource:origin(req)+path,method:'GET',price:'$'+Number(r[1]).toFixed(3),description:desc(path),tags:r[3],inputSchema:{type:'object',properties:Object.fromEntries(r[4].map(([n,,s])=>[n,s])),required:r[4].filter(([,q])=>q).map(([n])=>n)}}))};
}
function agent(req){
  return {version:'1.3',origin:new URL(origin(req)).host,display_name:'Agent Data Tools x402',description:'Eight pay-per-call x402 endpoints for registry, SEC, Census, OFAC, RDAP and Treasury data, plus a vendor-intake decision gate.',payout_address:PAY_TO,payments:{x402:{networks:[{network:'base',asset:'USDC',contract:USDC}]}},
    intents:Object.entries(routes).map(([path,r])=>({name:path.slice(5).replaceAll('-','_'),description:desc(path),endpoint:path,method:'GET',price:{amount:Number(r[1]),currency:'USDC'}}))};
}
function encodePaymentHeader(value){
  return Buffer.from(JSON.stringify(value),'utf8').toString('base64');
}
function decodePaymentHeader(value){
  if(typeof value!=='string'||value.length>16384)throw new Error('invalid_payment_header');
  const normalized=value.replace(/-/g,'+').replace(/_/g,'/');
  const parsed=JSON.parse(Buffer.from(normalized,'base64').toString('utf8'));
  if(!parsed||typeof parsed!=='object'||Array.isArray(parsed)||parsed.x402Version!==2)throw new Error('invalid_payment_payload');
  return parsed;
}
function paymentRequirements(priceUsd){
  return {scheme:'exact',network:NETWORK,amount:String(Math.round(Number(priceUsd)*1e6)),asset:USDC,payTo:PAY_TO,maxTimeoutSeconds:60,extra:{name:'USD Coin',version:'2'}};
}
function paymentDocument(req,path){
  const r=routes[path];
  return {x402Version:2,resource:{url:origin(req)+path,description:desc(path),mimeType:'application/json',serviceName:'Treasury Average Rates',tags:['Treasury','interest-rates','government','macro','finance']},accepts:[paymentRequirements(r[1])]};
}
function sendPaymentRequired(req,res,path,reason='payment_required'){
  const doc=paymentDocument(req,path), r=routes[path];
  const price='
  const u=new URL(req.url,'http://gateway.local'), target=new URL(r[0]); target.search=u.search;
  const headers={...req.headers};
  delete headers.host; delete headers.connection; delete headers['transfer-encoding'];
  const upstream=https.request(target,{method:'GET',headers},up=>{
    res.statusCode=up.statusCode||502;
    for(const [k,v] of Object.entries(up.headers)){if(v!==undefined)res.setHeader(k,v);}
    res.setHeader('x-x402-gateway','transparent-proxy');
    up.pipe(res);
  });
  upstream.on('error',e=>send(res,502,{error:'gateway_upstream_error',detail:e.message}));
  upstream.end();
}

http.createServer(async(req,res)=>{
  if(!req.url)return send(res,400,{error:'missing_url'});
  const u=new URL(req.url,'http://gateway.local');
  if(req.method==='OPTIONS'){res.writeHead(204,{'access-control-allow-origin':'*','access-control-allow-methods':'GET,HEAD,OPTIONS','access-control-allow-headers':'PAYMENT-SIGNATURE,X-PAYMENT,Content-Type,Accept','access-control-expose-headers':'PAYMENT-REQUIRED,PAYMENT-RESPONSE,x402-settled,x402-price,x402-network,x402-asset,x402-pay-to'});return res.end();}
  if(!['GET','HEAD'].includes(req.method||''))return send(res,405,{error:'method_not_allowed'});
  if(u.pathname==='/healthz')return send(res,200,{ok:true,routes:Object.keys(routes).length});
  if(u.pathname==='/openapi.json')return send(res,200,openapi(req));
  if(u.pathname==='/.well-known/x402')return send(res,200,discovery(req));
  if(u.pathname==='/.well-known/agent.json')return send(res,200,agent(req));
  if(u.pathname==='/llms.txt')return send(res,200,`# Agent Data Tools x402\n\nOpenAPI: ${origin(req)}/openapi.json\nx402: ${origin(req)}/.well-known/x402\nagent.json: ${origin(req)}/.well-known/agent.json\nSkill: ${origin(req)}/skill.md\n`,'text/plain; charset=utf-8');
  if(u.pathname==='/skill.md')return send(res,200,'# Agent Data Tools x402\n\nUse /api/vendor-intake-gate for a bounded proceed or human_review decision. Other routes return direct public-data lookups. Unpaid calls return HTTP 402; pay the quote and retry the same gateway URL with PAYMENT-SIGNATURE.','text/markdown; charset=utf-8');
  if(u.pathname==='/'){return send(res,200,`<!doctype html><meta name="viewport" content="width=device-width"><title>Agent Data Tools x402</title><main style="max-width:800px;margin:40px auto;font:16px system-ui"><h1>Agent Data Tools x402</h1><p>Unique-host transparent gateway for eight x402 v2 paid endpoints.</p><p><a href="/openapi.json">OpenAPI</a> · <a href="/.well-known/x402">x402 discovery</a> · <a href="/.well-known/agent.json">agent.json</a></p></main>`,'text/html; charset=utf-8');}
  if(u.pathname==='/api/treasury-average-rates')return serveTreasury(req,res,u);
  if(routes[u.pathname])return proxy(req,res,routes[u.pathname]);
  return send(res,404,{error:'not_found'});
}).listen(PORT,'0.0.0.0',()=>console.log(`Agent Data Tools x402 gateway listening on ${PORT}`));
+Number(r[1]).toFixed(3);
  const body=JSON.stringify({error:reason,...doc,price,currency:'USDC',network:NETWORK,payTo:PAY_TO},null,2);
  res.writeHead(402,{'content-type':'application/json; charset=utf-8','content-length':Buffer.byteLength(body),'cache-control':'no-store','access-control-allow-origin':'*','access-control-expose-headers':'PAYMENT-REQUIRED, PAYMENT-RESPONSE, x402-settled, x402-price, x402-network, x402-asset, x402-pay-to','PAYMENT-REQUIRED':encodePaymentHeader(doc),'x402-price':price,'x402-asset':'USDC','x402-network':NETWORK,'x402-pay-to':PAY_TO});
  res.end(body);
}
async function facilitatorPost(stage,payload,requirements){
  const r=await fetch(FACILITATOR+'/'+stage,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({x402Version:2,paymentPayload:payload,paymentRequirements:requirements})});
  if(!r.ok)throw new Error('facilitator_'+stage+'_'+r.status);
  return await r.json();
}
async function latestTreasuryRates(security){
  const u=new URL(TREASURY_API);
  u.searchParams.set('fields','record_date,security_type_desc,security_desc,avg_interest_rate_amt');
  u.searchParams.set('sort','-record_date');
  u.searchParams.set('page[size]','100');
  const r=await fetch(u,{headers:{accept:'application/json','user-agent':'agent-data-tools-x402/1.0'}});
  if(!r.ok)throw new Error('treasury_http_'+r.status);
  const payload=await r.json(), rows=Array.isArray(payload.data)?payload.data:[];
  if(!rows.length)throw new Error('treasury_no_data');
  const recordDate=String(rows[0].record_date||''), needle=String(security||'').trim().toLowerCase();
  const latest=rows.filter(row=>String(row.record_date||'')===recordDate);
  const filtered=needle?latest.filter(row=>String(row.security_desc||'').toLowerCase().includes(needle)):latest;
  return {recordDate,count:filtered.length,rates:filtered.map(row=>({securityDescription:row.security_desc??null,securityType:row.security_type_desc??null,averageInterestRatePercent:row.avg_interest_rate_amt===''||row.avg_interest_rate_amt==null?null:Number(row.avg_interest_rate_amt)})),source:'U.S. Treasury Fiscal Data — Average Interest Rates on U.S. Treasury Securities',frequency:'monthly'};
}
async function serveTreasury(req,res,u){
  const path='/api/treasury-average-rates';
  const signature=req.headers['payment-signature']||req.headers['x-payment'];
  if(!signature)return sendPaymentRequired(req,res,path);
  let payload;
  try{payload=decodePaymentHeader(String(signature));}catch{return sendPaymentRequired(req,res,path,'invalid_payment_header');}
  const security=(u.searchParams.get('security')||'').trim();
  if(security.length>100)return send(res,400,{error:'security filter must be 100 characters or fewer.'});
  const requirements=paymentRequirements(routes[path][1]);
  try{
    const verified=await facilitatorPost('verify',payload,requirements);
    if(verified.isValid!==true&&verified.success!==true)return sendPaymentRequired(req,res,path,String(verified.invalidReason||verified.errorReason||'payment_verification_failed'));
    let result;
    try{result=await latestTreasuryRates(security);}catch{return send(res,502,{error:'Treasury Fiscal Data unavailable; payment was not settled.'});}
    const settled=await facilitatorPost('settle',payload,requirements);
    if(settled.success!==true)return sendPaymentRequired(req,res,path,String(settled.errorReason||'payment_settlement_failed'));
    const body=JSON.stringify({...result,paid:true},null,2);
    res.writeHead(200,{'content-type':'application/json; charset=utf-8','content-length':Buffer.byteLength(body),'cache-control':'no-store','access-control-allow-origin':'*','access-control-expose-headers':'PAYMENT-RESPONSE, x402-settled','PAYMENT-RESPONSE':encodePaymentHeader(settled),'x402-settled':'true'});
    res.end(body);
  }catch{return send(res,503,{error:'Payment facilitator is temporarily unavailable; no result was served.'});}
}

function proxy(req,res,r){
  const u=new URL(req.url,'http://gateway.local'), target=new URL(r[0]); target.search=u.search;
  const headers={...req.headers};
  delete headers.host; delete headers.connection; delete headers['transfer-encoding'];
  const upstream=https.request(target,{method:'GET',headers},up=>{
    res.statusCode=up.statusCode||502;
    for(const [k,v] of Object.entries(up.headers)){if(v!==undefined)res.setHeader(k,v);}
    res.setHeader('x-x402-gateway','transparent-proxy');
    up.pipe(res);
  });
  upstream.on('error',e=>send(res,502,{error:'gateway_upstream_error',detail:e.message}));
  upstream.end();
}

http.createServer(async(req,res)=>{
  if(!req.url)return send(res,400,{error:'missing_url'});
  const u=new URL(req.url,'http://gateway.local');
  if(req.method==='OPTIONS'){res.writeHead(204,{'access-control-allow-origin':'*','access-control-allow-methods':'GET,HEAD,OPTIONS','access-control-allow-headers':'PAYMENT-SIGNATURE,X-PAYMENT,Content-Type,Accept','access-control-expose-headers':'PAYMENT-REQUIRED,PAYMENT-RESPONSE,x402-settled,x402-price,x402-network,x402-asset,x402-pay-to'});return res.end();}
  if(!['GET','HEAD'].includes(req.method||''))return send(res,405,{error:'method_not_allowed'});
  if(u.pathname==='/healthz')return send(res,200,{ok:true,routes:Object.keys(routes).length});
  if(u.pathname==='/openapi.json')return send(res,200,openapi(req));
  if(u.pathname==='/.well-known/x402')return send(res,200,discovery(req));
  if(u.pathname==='/.well-known/agent.json')return send(res,200,agent(req));
  if(u.pathname==='/llms.txt')return send(res,200,`# Agent Data Tools x402\n\nOpenAPI: ${origin(req)}/openapi.json\nx402: ${origin(req)}/.well-known/x402\nagent.json: ${origin(req)}/.well-known/agent.json\nSkill: ${origin(req)}/skill.md\n`,'text/plain; charset=utf-8');
  if(u.pathname==='/skill.md')return send(res,200,'# Agent Data Tools x402\n\nUse /api/vendor-intake-gate for a bounded proceed or human_review decision. Other routes return direct public-data lookups. Unpaid calls return HTTP 402; pay the quote and retry the same gateway URL with PAYMENT-SIGNATURE.','text/markdown; charset=utf-8');
  if(u.pathname==='/'){return send(res,200,`<!doctype html><meta name="viewport" content="width=device-width"><title>Agent Data Tools x402</title><main style="max-width:800px;margin:40px auto;font:16px system-ui"><h1>Agent Data Tools x402</h1><p>Unique-host transparent gateway for eight x402 v2 paid endpoints.</p><p><a href="/openapi.json">OpenAPI</a> · <a href="/.well-known/x402">x402 discovery</a> · <a href="/.well-known/agent.json">agent.json</a></p></main>`,'text/html; charset=utf-8');}
  if(routes[u.pathname])return proxy(req,res,routes[u.pathname]);
  return send(res,404,{error:'not_found'});
}).listen(PORT,'0.0.0.0',()=>console.log(`Agent Data Tools x402 gateway listening on ${PORT}`));
