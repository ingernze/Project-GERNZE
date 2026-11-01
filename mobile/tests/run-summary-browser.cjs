// Optional runner: npm-installed playwright or the Codex runtime copy; no browser installation here.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
(async()=>{
 let playwright;try{playwright=require('playwright');}catch{try{playwright=require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES||'', 'playwright'));}catch{console.log(JSON.stringify({status:'skipped',reason:'Playwright unavailable',indexedDB:false,realAPI:0}));return;}}
 let browser;try{browser=await playwright.chromium.launch({headless:true,...process.env.SUMMARY_CHROMIUM?{executablePath:process.env.SUMMARY_CHROMIUM}:{}});}catch(e){console.log(JSON.stringify({status:'skipped',reason:'Chromium unavailable: '+e.message.split('\n')[0],indexedDB:false,realAPI:0}));return;}
 const root=path.resolve(__dirname,'../..');
 const server=http.createServer((req,res)=>{const filename=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));if(!filename.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}fs.readFile(filename,(e,data)=>{if(e){res.writeHead(404);res.end();return;}res.setHeader('content-type',filename.endsWith('.html')?'text/html; charset=utf-8':filename.endsWith('.json')?'application/json':'text/javascript; charset=utf-8');res.end(data);});});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{const testPage=process.env.SUMMARY_TEST_PAGE||'summary-backlog-storage.html';if(!/^[a-z0-9-]+\.html$/.test(testPage))throw Error('Invalid local test page');const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port+'/mobile/tests/'+testPage);await page.waitForFunction(()=>window.summaryTestResult,{timeout:30000});const result=await page.evaluate(()=>window.summaryTestResult);console.log(JSON.stringify(result,null,2));if(result.status!=='passed')process.exitCode=1;}finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
