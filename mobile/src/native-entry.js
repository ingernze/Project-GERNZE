import {createRemindersHost} from './native-reminders';
window.HecateNative=createRemindersHost();

import {mountUpdates} from './native-updates';
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountUpdates,{once:true});else mountUpdates();

import {mountShake} from './native-shake';
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountShake,{once:true});else mountShake();

import {mountChat} from './native-chat';
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountChat,{once:true});else mountChat();

import {mountBalance} from './native-balance';
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountBalance,{once:true});else mountBalance();

import {mountCodexTasks} from './native-codex-tasks';
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountCodexTasks,{once:true});else mountCodexTasks();
