"""Swiss visual system for the private M5 operator surface."""

M5_CSS = r"""
:root { color-scheme: light; --paper:#FFFFFF; --wash:#F7F7F8; --ink:#111111; --muted:#5B5B60; --line:#D7D7DB; --blue:#002FA7; }
* { box-sizing:border-box; }
html { min-width:320px; background:var(--paper); }
[hidden] { display:none !important; }
body { margin:0; min-height:100vh; background:var(--paper); color:var(--ink); font:14px/1.45 "Helvetica Neue", Helvetica, Arial, sans-serif; }
button,select,input { font:inherit; }
button,.action { min-height:36px; padding:8px 12px; border:1px solid var(--ink); border-radius:0; background:var(--paper); color:var(--ink); cursor:pointer; font-weight:700; text-decoration:none; }
button:hover,.action:hover { background:var(--blue); border-color:var(--blue); color:var(--paper); }
button:focus-visible,.action:focus-visible,select:focus-visible,input:focus-visible { outline:3px solid var(--blue); outline-offset:2px; }
button:disabled,.action.disabled { color:var(--muted); border-color:var(--line); background:var(--wash); cursor:not-allowed; }
input,select { min-height:36px; border:1px solid var(--ink); border-radius:0; background:var(--paper); padding:7px 9px; }
.topbar { position:sticky; top:0; z-index:20; display:grid; grid-template-columns:1fr auto; gap:24px; align-items:center; padding:18px 24px; border-bottom:1px solid var(--ink); background:rgba(255,255,255,.97); }
h1,h2,p { margin:0; }
h1 { font-size:clamp(22px,3vw,44px); line-height:.95; letter-spacing:-.055em; font-weight:800; }
h2 { font-size:15px; line-height:1.1; }
.topbar p,.section-head span,.muted { color:var(--muted); }
.top-actions,.actions,.admin-row { display:flex; flex-wrap:wrap; gap:8px; }
main { width:min(1680px,100%); margin:0 auto; padding:0 24px 48px; }
.summary { display:grid; grid-template-columns:repeat(5,1fr); border-left:1px solid var(--ink); }
.summary div { min-height:112px; padding:18px; border-right:1px solid var(--ink); border-bottom:1px solid var(--ink); }
.summary strong { display:block; font-size:clamp(28px,4vw,64px); line-height:.9; letter-spacing:-.06em; color:var(--blue); font-variant-numeric:tabular-nums; }
.summary span,dt,.eyebrow { display:block; margin-top:10px; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
.alert { display:flex; justify-content:space-between; gap:18px; padding:14px 18px; border:1px solid var(--blue); border-top:0; color:var(--blue); overflow-wrap:anywhere; }
.section-head { display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:28px 0 12px; border-bottom:1px solid var(--ink); }
.topology { border-bottom:1px solid var(--ink); }
.host-rail { display:grid; grid-template-columns:180px 1fr; min-height:84px; border-bottom:1px solid var(--ink); }
.host-rail h3 { margin:0; padding:18px; background:var(--blue); color:var(--paper); font-size:24px; letter-spacing:-.04em; }
.host-rail p { padding:18px; }
.domain-rail { display:grid; grid-template-columns:repeat(5,minmax(210px,1fr)); overflow-x:auto; }
.domain { min-width:210px; padding:16px; border-right:1px solid var(--ink); background:var(--paper); }
.domain:last-child { border-right:0; }
.domain[data-kind="legacy"] { background:var(--wash); }
.domain h3 { min-height:44px; margin:0; font-size:18px; letter-spacing:-.025em; }
.domain-meta { margin:8px 0 16px; color:var(--muted); font-size:12px; }
.node-list { display:grid; gap:7px; margin:0; padding:0; list-style:none; }
.node { width:100%; text-align:left; border-color:var(--line); }
.node[data-drift="true"] { border-left:5px solid var(--blue); }
.edge-legend { display:flex; flex-wrap:wrap; gap:20px; padding:12px 0; color:var(--muted); font-size:12px; }
.edge-legend b { color:var(--ink); }
.workloads { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-left:1px solid var(--ink); }
.workload { padding:18px; border-right:1px solid var(--ink); border-bottom:1px solid var(--ink); }
.workload-head { display:grid; grid-template-columns:1fr auto; gap:16px; align-items:start; padding-bottom:12px; border-bottom:1px solid var(--line); }
.workload-head h2 { font-size:22px; letter-spacing:-.035em; }
.workload-head p { margin-top:5px; color:var(--muted); }
code { padding:3px 5px; border:1px solid var(--line); color:var(--blue); font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:12px; overflow-wrap:anywhere; }
.pills { display:flex; flex-wrap:wrap; gap:0; margin:12px 0; border-left:1px solid var(--line); }
.pill { padding:5px 8px; border:1px solid var(--line); border-left:0; font-size:11px; font-weight:700; }
.pill span { margin-right:5px; color:var(--muted); font-weight:400; }
.pill.bad,.pill.warn { border-bottom:3px solid var(--blue); }
.facts { display:grid; grid-template-columns:repeat(3,1fr); margin:0; border-left:1px solid var(--line); border-top:1px solid var(--line); }
.facts div { min-width:0; padding:9px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
dd { margin:2px 0 0; overflow-wrap:anywhere; font-weight:700; }
.warning { margin-top:10px; padding:10px; border-left:5px solid var(--blue); background:var(--wash); }
.actions,.admin-row { margin-top:12px; }
.admin-row { padding-top:12px; border-top:1px solid var(--ink); }
.admin-row label { display:grid; gap:4px; color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; }
.monitor,.command-panel { margin-top:18px; padding:16px; border:1px solid var(--ink); }
.metrics-grid,.plan-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:0; border-left:1px solid var(--ink); border-top:1px solid var(--ink); }
.metric,.plan-grid article { padding:14px; border-right:1px solid var(--ink); border-bottom:1px solid var(--ink); }
.metric p { margin-top:5px; font-size:20px; color:var(--blue); font-variant-numeric:tabular-nums; }
.bar { height:4px; margin-top:8px; background:var(--line); }.bar span { display:block; height:100%; background:var(--blue); }
.plan-grid { margin-top:18px; grid-template-columns:repeat(5,1fr); }.plan-grid article p { margin:8px 0; color:var(--muted); }
pre { max-height:220px; overflow:auto; white-space:pre-wrap; font:12px/1.45 "Helvetica Neue",Helvetica,Arial,sans-serif; }
@media(max-width:1050px){.summary{grid-template-columns:repeat(3,1fr)}.workloads{grid-template-columns:1fr}.plan-grid{grid-template-columns:repeat(2,1fr)}.facts{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.topbar{position:static;grid-template-columns:1fr;padding:16px}.top-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));width:100%}.top-actions button{min-width:0;padding:8px 4px}.summary{grid-template-columns:1fr}.summary div{min-height:82px}.alert,.section-head{align-items:flex-start;flex-direction:column}.alert span{max-width:100%}.host-rail{grid-template-columns:1fr}.facts,.metrics-grid,.plan-grid{grid-template-columns:1fr}main{padding:0 16px 32px}}
"""
