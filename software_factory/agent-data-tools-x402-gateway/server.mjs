import http from 'node:http';
import https from 'node:https';

const PORT = Number(process.env.PORT || 3000);
const PAY_TO = '0x708f7b52b56eafd7fc1de65fc7752ed732914021';
const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
const NETWORK = 'eip155:8453';
const CONTACT = 'jayp19386@gmail.com';
const FACILITATOR = 'https://facilitator.payai.network';
const TREASURY_API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates';
const IANA_RDAP_BOOTSTRAP = 'https://data.iana.org/rdap/dns.json';
let rdapBootstrapCache = null;

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
const nativeResourceMeta={
  '/api/treasury-average-rates':{serviceName:'Treasury Average Rates',tags:['Treasury','interest-rates','government','macro','finance']},
  '/api/us-address-geocode':{serviceName:'Census Address Geocoder',tags:['Census','geocoding','address','geography','US']},
  '/api/domain-rdap':{serviceName:'Domain RDAP Lookup',tags:['RDAP','domain','registration','DNS','internet']}
};
function paymentDocument(req,path){
  const r=routes[path], meta=nativeResourceMeta[path]||{serviceName:'Agent Data Tool',tags:['data']};
  return {x402Version:2,resource:{url:origin(req)+path,description:desc(path),mimeType:'application/json',serviceName:meta.serviceName,tags:meta.tags},accepts:[paymentRequirements(r[1])]};
}
function sendPaymentRequired(req,res,path,reason='payment_required'){
  const doc=paymentDocument(req,path), r=routes[path];
  const price='$'+Number(r[1]).toFixed(3);
  const body=JSON.stringify({error:reason,...doc,price,currency:'USDC',network:NETWORK,payTo:PAY_TO},null,2);
  res.writeHead(402,{'content-type':'application/json; charset=utf-8','content-length':Buffer.byteLength(body),'cache-control':'no-store','access-control-allow-origin':'*','access-control-expose-headers':'PAYMENT-REQUIRED, PAYMENT-RESPONSE, x402-settled, x402-price, x402-network, x402-asset, x402-pay-to','PAYMENT-REQUIRED':encodePaymentHeader(doc),'x402-price':price,'x402-asset':'USDC','x402-network':NETWORK,'x402-pay-to':PAY_TO});
  res.end(body);
}
async function fetchWithTimeout(url,init={},timeoutMs=10000){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{return await fetch(url,{...init,signal:controller.signal});}finally{clearTimeout(timer);}
}
async function facilitatorPost(stage,payload,requirements){
  const r=await fetchWithTimeout(FACILITATOR+'/'+stage,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({x402Version:2,paymentPayload:payload,paymentRequirements:requirements})},6000);
  if(!r.ok)throw new Error('facilitator_'+stage+'_'+r.status);
  return await r.json();
}
async function latestTreasuryRates(security){
  const u=new URL(TREASURY_API);
  u.searchParams.set('fields','record_date,security_type_desc,security_desc,avg_interest_rate_amt');
  u.searchParams.set('sort','-record_date');
  u.searchParams.set('page[size]','100');
  const r=await fetchWithTimeout(u,{headers:{accept:'application/json','user-agent':'agent-data-tools-x402/1.0'}},10000);
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

function firstGeoByKey(geographies,key){
  const value=geographies&&geographies[key];
  return Array.isArray(value)&&value.length?value[0]:null;
}
function firstGeoByPattern(geographies,pattern){
  for(const [key,value] of Object.entries(geographies||{})){if(pattern.test(key)&&Array.isArray(value)&&value.length)return value[0];}
  return null;
}
async function geocodeAddress(address){
  const u=new URL('https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress');
  u.searchParams.set('address',address);
  u.searchParams.set('benchmark','Public_AR_Current');
  u.searchParams.set('vintage','Current_Current');
  u.searchParams.set('format','json');
  const r=await fetchWithTimeout(u,{headers:{accept:'application/json','user-agent':'agent-data-tools-x402/1.0'}},10000);
  if(!r.ok)throw new Error('census_http_'+r.status);
  const data=await r.json(), match=data?.result?.addressMatches?.[0];
  if(!match)return {input:address,matched:false,matchedAddress:null,coordinates:null,addressComponents:null,geographies:null,source:'U.S. Census Bureau Geocoding Services'};
  const geos=match.geographies||{};
  const state=firstGeoByKey(geos,'States'), county=firstGeoByKey(geos,'Counties'), tract=firstGeoByKey(geos,'Census Tracts');
  const block=firstGeoByKey(geos,'Census Blocks')||firstGeoByPattern(geos,/^\\d{4} Census Blocks$/i);
  const district=firstGeoByPattern(geos,/^(?:\\d+(?:st|nd|rd|th) )?Congressional Districts$/i);
  return {input:address,matched:true,matchedAddress:match.matchedAddress??null,coordinates:{longitude:match.coordinates?.x??null,latitude:match.coordinates?.y??null},addressComponents:match.addressComponents??null,geographies:{stateFips:state?.STATE??null,countyFips:county?.COUNTY??null,countyGeoid:county?.GEOID??null,tract:tract?.TRACT??null,tractGeoid:tract?.GEOID??null,block:block?.BLOCK??null,blockGeoid:block?.GEOID??null,congressionalDistrict:district?.CD??district?.BASENAME??null},source:'U.S. Census Bureau Geocoding Services'};
}
async function serveCensus(req,res,u){
  const path='/api/us-address-geocode';
  const signature=req.headers['payment-signature']||req.headers['x-payment'];
  if(!signature)return sendPaymentRequired(req,res,path);
  let payload;
  try{payload=decodePaymentHeader(String(signature));}catch{return sendPaymentRequired(req,res,path,'invalid_payment_header');}
  const address=(u.searchParams.get('address')||'').trim().replace(/\\s+/g,' ');
  if(address.length<6)return send(res,400,{error:'address must contain at least 6 characters.'});
  if(address.length>240)return send(res,400,{error:'address must be 240 characters or fewer.'});
  const requirements=paymentRequirements(routes[path][1]);
  try{
    const verified=await facilitatorPost('verify',payload,requirements);
    if(verified.isValid!==true&&verified.success!==true)return sendPaymentRequired(req,res,path,String(verified.invalidReason||verified.errorReason||'payment_verification_failed'));
    let result;
    try{result=await geocodeAddress(address);}catch{return send(res,502,{error:'Census geocoder unavailable; payment was not settled.'});}
    const settled=await facilitatorPost('settle',payload,requirements);
    if(settled.success!==true)return sendPaymentRequired(req,res,path,String(settled.errorReason||'payment_settlement_failed'));
    const body=JSON.stringify({...result,paid:true},null,2);
    res.writeHead(200,{'content-type':'application/json; charset=utf-8','content-length':Buffer.byteLength(body),'cache-control':'no-store','access-control-allow-origin':'*','access-control-expose-headers':'PAYMENT-RESPONSE, x402-settled','PAYMENT-RESPONSE':encodePaymentHeader(settled),'x402-settled':'true'});
    res.end(body);
  }catch{return send(res,503,{error:'Payment facilitator is temporarily unavailable; no result was served.'});}
}

function normalizeDomain(raw){
  let value=String(raw||'').trim().toLowerCase();
  if(value.endsWith('.'))value=value.slice(0,-1);
  if(value.length<3||value.length>253||!/^[a-z0-9.-]+$/.test(value))return null;
  const labels=value.split('.');
  if(labels.length<2)return null;
  for(const label of labels){if(!label||label.length>63||label.startsWith('-')||label.endsWith('-'))return null;}
  return value;
}
async function rdapBootstrap(){
  if(rdapBootstrapCache&&Date.now()-rdapBootstrapCache.loadedAt<3600000)return rdapBootstrapCache.data;
  const r=await fetchWithTimeout(IANA_RDAP_BOOTSTRAP,{headers:{accept:'application/json','user-agent':'agent-data-tools-x402/1.0'}},10000);
  if(!r.ok)throw new Error('iana_bootstrap_http_'+r.status);
  const data=await r.json();
  rdapBootstrapCache={loadedAt:Date.now(),data};
  return data;
}
function findRdapBase(data,tld){
  for(const service of data.services||[]){
    const tlds=service[0]||[], urls=service[1]||[];
    if(tlds.some(value=>String(value).toLowerCase()===tld.toLowerCase())&&urls.length)return urls[0];
  }
  return null;
}
function vcardName(entity){
  const card=entity&&entity.vcardArray;
  if(!Array.isArray(card)||!Array.isArray(card[1]))return null;
  for(const item of card[1]){if(Array.isArray(item)&&item[0]==='fn')return String(item[3]||'')||null;}
  return null;
}
function eventMap(events){
  const out={};
  if(!Array.isArray(events))return out;
  for(const item of events){
    const action=String(item?.eventAction||'').toLowerCase().replace(/[^a-z0-9]+(.)/g,(_m,ch)=>ch.toUpperCase());
    const date=String(item?.eventDate||'');
    if(action&&date&&!out[action])out[action]=date;
  }
  return out;
}
async function lookupRdap(domain){
  const tld=domain.split('.').pop()||'', registry=await rdapBootstrap(), base=findRdapBase(registry,tld);
  if(!base)return {domain,registered:null,error:'no_rdap_bootstrap_service',source:'IANA RDAP Bootstrap Service Registry'};
  const u=base.replace(/\/+$/,'')+'/domain/'+encodeURIComponent(domain);
  const r=await fetchWithTimeout(u,{headers:{accept:'application/rdap+json, application/json','user-agent':'agent-data-tools-x402/1.0'},redirect:'follow'},10000);
  if(r.status===404)return {domain,registered:false,authoritativeRdap:base,source:'Authoritative RDAP server discovered via IANA bootstrap'};
  if(!r.ok)throw new Error('rdap_http_'+r.status);
  const data=await r.json();
  const registrar=Array.isArray(data.entities)?data.entities.find(entity=>Array.isArray(entity.roles)&&entity.roles.map(role=>String(role).toLowerCase()).includes('registrar')):undefined;
  const nameservers=Array.isArray(data.nameservers)?data.nameservers.map(ns=>String(ns.ldhName||ns.unicodeName||'')).filter(Boolean):[];
  return {domain,registered:true,handle:data.handle??null,unicodeName:data.unicodeName??null,status:Array.isArray(data.status)?data.status:[],registrar:registrar?{name:vcardName(registrar),handle:registrar.handle??null}:null,events:eventMap(data.events),nameservers,secureDns:data.secureDNS?{delegationSigned:data.secureDNS.delegationSigned??null}:null,authoritativeRdap:base,source:'Authoritative RDAP server discovered via IANA bootstrap'};
}
async function serveRdap(req,res,u){
  const path='/api/domain-rdap';
  const signature=req.headers['payment-signature']||req.headers['x-payment'];
  if(!signature)return sendPaymentRequired(req,res,path);
  let payload;
  try{payload=decodePaymentHeader(String(signature));}catch{return sendPaymentRequired(req,res,path,'invalid_payment_header');}
  const domain=normalizeDomain(u.searchParams.get('domain')||'');
  if(!domain)return send(res,400,{error:'domain must be a valid ASCII or punycode domain name.'});
  const requirements=paymentRequirements(routes[path][1]);
  try{
    const verified=await facilitatorPost('verify',payload,requirements);
    if(verified.isValid!==true&&verified.success!==true)return sendPaymentRequired(req,res,path,String(verified.invalidReason||verified.errorReason||'payment_verification_failed'));
    let result;
    try{result=await lookupRdap(domain);}catch{return send(res,502,{error:'IANA or authoritative RDAP service unavailable; payment was not settled.'});}
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
  if(u.pathname==='/api/treasury-average-rates')return serveTreasury(req,res,u);
  if(u.pathname==='/api/us-address-geocode')return serveCensus(req,res,u);
  if(u.pathname==='/api/domain-rdap')return serveRdap(req,res,u);
  if(routes[u.pathname])return proxy(req,res,routes[u.pathname]);
  return send(res,404,{error:'not_found'});
}).listen(PORT,'0.0.0.0',()=>console.log(`Agent Data Tools x402 gateway listening on ${PORT}`));
