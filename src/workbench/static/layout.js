/* Hebao layout preferences. Widths stay independent of the selected module. */
(function (root) {
"use strict";
const limits = Object.freeze({rail:64,nav:256,navMin:216,navMax:352,detail:344,detailMin:280,detailMax:440,compactAt:900,contentMin:480});
const bound=(value,low,high)=>Math.round(Math.max(low,Math.min(high,value)));
function resolveLayout(viewport, preferences) {
  const width=Math.max(0,Math.round(viewport));
  const small=width<limits.compactAt;
  const collapsed=small ? !preferences.mobileExpanded : preferences.collapsed;
  const nav=bound(preferences.navWidth,limits.navMin,limits.navMax);
  const floating=small&&!collapsed;
  const navTrack=small||collapsed?limits.rail:nav;
  const detailWidth=Math.min(bound(preferences.detailWidth,limits.detailMin,limits.detailMax),Math.max(0,width-limits.rail));
  const overlay=Boolean(preferences.detailOpen && width-navTrack-detailWidth<limits.contentMin);
  const detailTrack=preferences.detailOpen&&!overlay?detailWidth:0;
  return {small,collapsed,floating,nav,navTrack,detailWidth,detailTrack,overlay};
}
const api={limits,bound,resolveLayout};
if(typeof module==='object'&&module.exports)module.exports=api;else root.HebaoLayout=api;
})(typeof window==='object'?window:globalThis);
