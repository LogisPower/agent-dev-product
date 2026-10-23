const fs=require('node:fs'),path=require('node:path'),dns=require('node:dns').promises,http=require('node:http'),https=require('node:https'),net=require('node:net');
process.env.PLAYWRIGHT_BROWSERS_PATH=path.join(__dirname,'runtime','browsers');
const {chromium}=require('C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
function isPublic(ip){
 if(net.isIP(ip)!==4)return false; // IPv6-only hosts are unsupported, not silently routed.
 const a=ip.split('.').map(Number);
 return !(a[0]===0||a[0]===10||a[0]===127||a[0]>=224||a[0]===169&&a[1]===254||a[0]===172&&a[1]>=16&&a[1]<=31||a[0]===192&&(a[1]===168||a[1]===0)||a[0]===100&&a[1]>=64&&a[1]<=127||a[0]===198&&(a[1]===18||a[1]===19));
}
async function main(c){
 const target=new URL(c.url),local=c.allowedLocal.some(p=>c.url.startsWith(p));
 if(!['http:','https:'].includes(target.protocol)||target.username||target.password)throw Error('Unsupported URL');
 const browser=await chromium.launch({headless:true,chromiumSandbox:true});
 try{
  const context=await browser.newContext({acceptDownloads:false,serviceWorkers:'block',viewport:{width:1280,height:800}}),page=await context.newPage(),errors=[],blocked=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  await context.route('**/*',async route=>{
   try{
    const request=route.request(),u=new URL(request.url());
    if(!['http:','https:'].includes(u.protocol)||u.origin!==target.origin||u.username||u.password)throw Error('Only the selected origin is allowed');
    const allowedLocal=local&&c.allowedLocal.some(p=>u.href.startsWith(p));
    if(local&&!allowedLocal)throw Error('Outside selected project server');
    let ip;
    if(allowedLocal)ip='127.0.0.1';else{
     if(u.port&&!['80','443'].includes(u.port))throw Error('Unsupported port');
     const records=await dns.lookup(u.hostname,{all:true,family:4});
     if(!records.length||records.some(r=>!isPublic(r.address)))throw Error('Private address blocked');ip=records[0].address;
    }
    const headers={...request.headers()};delete headers.host;delete headers.connection;delete headers['accept-encoding'];
    const response=await new Promise((resolve,reject)=>{
     const req=(u.protocol==='https:'?https:http).request(u,{method:request.method(),headers,lookup:(_h,_o,cb)=>cb(null,ip,4),timeout:10000},res=>{
      const chunks=[];let n=0;res.on('data',b=>{n+=b.length;if(n>5000000){req.destroy(Error('Response exceeds 5 MB'));return}chunks.push(b)});res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks)}));res.on('error',reject);
     });req.on('error',reject);req.on('timeout',()=>req.destroy(Error('Request timeout')));const body=request.postDataBuffer();if(body)req.write(body);req.end();
    });
    delete response.headers['transfer-encoding'];delete response.headers['content-encoding'];
    await route.fulfill(response);
   }catch(e){blocked.push(route.request().url()+': '+e.message);await route.abort()}
  });
  await page.goto(c.url,{waitUntil:'domcontentloaded',timeout:20000});
  for(const action of c.actions){
   if(typeof action.selector!=='string'||action.selector.length>500)throw Error('Invalid selector');
   if(action.type==='click')await page.locator(action.selector).click({timeout:5000});
   else if(action.type==='fill')await page.locator(action.selector).fill(String(action.value||''),{timeout:5000});
   else throw Error('Only click/fill actions are supported');
  }
  await page.screenshot({path:c.output,fullPage:false});
  return {url:page.url(),title:await page.title(),dom_text:(await page.locator('body').innerText()).slice(0,16000),controls:await page.locator('input,button,a,select,textarea').evaluateAll(elements=>elements.slice(0,60).map(e=>({tag:e.tagName,id:e.id,name:e.getAttribute('name'),text:(e.innerText||e.getAttribute('aria-label')||'').slice(0,150)}))),errors:errors.slice(0,30),blocked_requests:blocked.slice(0,20),screenshot:'browser-screenshot.png',boundary:'Fresh headless Chromium context. Same-origin requests only; private destinations blocked except this project server. No user browser profile.'};
 }finally{await browser.close()}
}
let input='';process.stdin.on('data',x=>input+=x);process.stdin.on('end',()=>{
 const keepAlive=setInterval(()=>{},1000);
 const deadline=setTimeout(()=>{console.error('Browser verification exceeded 60 seconds');process.exit(1)},60000);
 main(JSON.parse(input)).then(x=>console.log(JSON.stringify(x))).catch(e=>{console.error(e.message);process.exitCode=1}).finally(()=>{clearInterval(keepAlive);clearTimeout(deadline)});
});
