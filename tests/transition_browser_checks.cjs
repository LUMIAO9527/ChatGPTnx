/* Runs the maintained offline explorer in an installed Chromium browser.
   Uses synthetic data only and keeps profiles/reports under the supplied _wip. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url');
const {chromium}=require('playwright');
const [html,output,kind='motion']=process.argv.slice(2);
if(!html||!output||!['motion','layout'].includes(kind))throw new Error('HTML, _wip output directory and motion/layout are required');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({executablePath:process.env.NX_TEST_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
    args:['--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows','--disable-features=CalculateNativeWinOcclusion']});
  try{
    const context=await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'no-preference'});
    const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    await page.goto(pathToFileURL(path.resolve(html)).href+'#resume-history');
    await page.frameLocator('#frame').locator('#app').waitFor();
    await page.locator('#audit-'+kind).click();
    const progress=setInterval(()=>page.locator('#audit-status').textContent().then(text=>console.log(text)).catch(()=>{}),15000);
    try {await page.waitForFunction(()=>/^(检查通过|发现问题)/.test(document.querySelector('#audit-status').textContent),null,{timeout:420000});}
    finally {clearInterval(progress);}
    const report=JSON.parse(await page.locator('#audit-report').textContent());
    report.browserErrors=errors;
    fs.writeFileSync(path.join(output,kind+'-audit.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({kind,passed:report.passed,scenes:report.records.length,problems:report.problems,errors}));
    process.exitCode=report.passed&&!errors.length?0:1;
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
