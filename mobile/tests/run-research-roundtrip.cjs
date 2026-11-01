const {createRequire}=require('node:module'),path=require('node:path');
const load=process.env.GERNZE_TEST_NODE_MODULES?createRequire(path.join(process.env.GERNZE_TEST_NODE_MODULES,'__runner__.cjs')):require;
const {chromium}=load('playwright');
(async()=>{let browser;try{
 const origin=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw Error('synthetic loopback origin required');
 browser=await chromium.launch({channel:process.env.GERNZE_TEST_BROWSER_CHANNEL||'msedge',headless:true});const context=await browser.newContext({viewport:{width:393,height:852}}),page=await context.newPage(),errors=[];
 await context.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
 page.on('pageerror',e=>errors.push(e.message));await page.goto(origin);
 const checks=await page.evaluate(async()=>{const config=await(await fetch('/fixture')).json();const {run}=await import('/tests/research-roundtrip.browser.mjs');return run(config);});
 if(errors.length)throw Error(errors.join('\n'));process.stdout.write(JSON.stringify({success:true,checkpoints:checks.length,checks,realIndexedDB:true}));
 }finally{await browser?.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
