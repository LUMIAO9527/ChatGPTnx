/* Match the configuration that the production resource builder supplies. */
'use strict';
const fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../_wip/build/resources/panel.html'),'utf8');
const match=html.match(/window\.NX_CONFIG=Object\.freeze\(([^\n]+)\);/);
if(!match)throw new Error('Build the production panel before running UI fixtures');
module.exports=JSON.parse(match[1]);
