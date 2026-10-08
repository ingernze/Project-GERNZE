/* Appearance only. No timers, network calls or learning-data writes. */
(function (root) {
"use strict";
const key='hebao.workbench.theme.v1';
const preview=document.documentElement.dataset.preview==='true'||location.protocol==='file:';
const valid=value=>value==='dark'||value==='light';
let selected=document.documentElement.dataset.theme;
if(preview){try{const saved=localStorage.getItem(key);if(valid(saved))selected=saved;}catch(_error){}}
document.documentElement.dataset.theme=valid(selected)?selected:'dark';
root.HebaoTheme=Object.freeze({
  current:()=>document.documentElement.dataset.theme,
  apply(value){
    if(!valid(value))throw new Error('请选择深色或浅色主题。');
    document.documentElement.dataset.theme=value;
  },
  rememberPreview(value){
    if(!preview||!valid(value))return false;
    try{localStorage.setItem(key,value);return true;}catch(_error){return false;}
  },
});
})(window);
