const mode=process.argv.includes('--private')?'private':'public';
require('child_process').execFileSync(process.env.HEBAO_PYTHON||'python',['tools/build-core.py','--mode',mode],{stdio:'inherit'});
const fs=require('fs');
const path=require('path');
// Keep the opening version in step with the Android package metadata.
const versionMatch=fs.readFileSync('android/app/build.gradle','utf8').match(/versionName\s+["']([A-Za-z0-9.+_-]+)["']/);
if(!versionMatch)throw Error('Android versionName is missing.');
const opening=fs.readFileSync('www/index.html','utf8');
const versionTag=/<span class="splash-version" data-app-version[^>]*>[^<]*<\/span>/g;
if((opening.match(versionTag)||[]).length!==1)throw Error('Opening version label is missing or duplicated.');
fs.writeFileSync('www/index.html',opening.replace(versionTag,'<span class="splash-version" data-app-version aria-label="版本 '+versionMatch[1]+'">v'+versionMatch[1]+'</span>'));

// Share the accepted read-only book renderer with desktop; all data stays local.
const sharedBooks=path.resolve('../src/workbench/static');
for(const name of ['memory-books.js','memory-books.css'])fs.copyFileSync(path.join(sharedBooks,name),path.join('www',name));
fs.mkdirSync('www/assets',{recursive:true});
for(const month of [10,11,12]){const name='cover-'+month+'.png';fs.copyFileSync(path.join(sharedBooks,'assets',name),path.join('www/assets',name));}
const esbuild=require('esbuild');
esbuild.buildSync({entryPoints:['src/native-entry.js'],bundle:true,outfile:'www/native-bridge.js',format:'iife',target:'chrome89',minify:true});
