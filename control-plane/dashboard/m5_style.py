"""Orbital Operations Plot visual system for the private M5 operator surface."""

M5_CSS = r"""
:root { color-scheme:dark; --void:#070A12; --field:#0D1324; --panel:#141D33; --line:#2A3550; --ink:#F3F6FC; --muted:#9AA8BF; --blue:#68A7FF; --gold:#F5C85B; --red:#FF6B72; }
:root[data-theme="light"] { color-scheme:light; --void:#F5F7FB; --field:#FFFFFF; --panel:#EAF0FA; --line:#BCC8D9; --ink:#101828; --muted:#52627A; --blue:#1769D2; --gold:#9A6500; --red:#C5323A; }
* { box-sizing:border-box; }
html { min-width:320px; background:var(--void); scroll-behavior:smooth; }
[hidden] { display:none !important; }
body { margin:0; min-height:100vh; background:var(--void); color:var(--ink); font:14px/1.48 Arial,Helvetica,sans-serif; }
button,select,input { font:inherit; }
button,.action { min-height:38px; padding:8px 13px; border:1px solid var(--line); border-radius:6px; background:var(--field); color:var(--ink); cursor:pointer; font-weight:700; text-decoration:none; }
button:hover,.action:hover { border-color:var(--blue); color:var(--blue); }
button:focus-visible,.action:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible,[role="button"]:focus-visible { outline:3px solid var(--blue); outline-offset:3px; }
button:disabled,.action.disabled { color:var(--muted); border-color:var(--line); background:var(--void); cursor:not-allowed; }
input,select { min-height:38px; border:1px solid var(--line); border-radius:6px; background:var(--field); color:var(--ink); padding:7px 9px; }
.app-shell { display:grid; grid-template-columns:72px minmax(0,1fr); min-height:100vh; }
.nav-rail { position:sticky; top:0; z-index:30; height:100vh; display:flex; flex-direction:column; align-items:center; border-right:1px solid var(--line); background:var(--field); }
.brand { display:grid; place-items:center; width:72px; height:72px; border-bottom:1px solid var(--line); color:var(--gold); font-size:25px; font-weight:800; text-decoration:none; }
.nav-rail nav { display:flex; flex-direction:column; width:100%; padding-top:22px; }
.nav-rail nav a { display:flex; min-height:78px; flex-direction:column; align-items:center; justify-content:center; gap:4px; border-left:2px solid transparent; color:var(--muted); font-size:9px; font-weight:700; letter-spacing:.07em; text-decoration:none; text-transform:uppercase; }
.nav-rail nav a span { color:#697891; font-size:9px; }
.nav-rail nav a:hover,.nav-rail nav a[aria-current="page"] { border-left-color:var(--blue); color:var(--ink); background:var(--panel); }
.private-state { margin-top:auto; padding:0 0 20px; color:var(--muted); font-size:9px; text-align:center; text-transform:uppercase; }
.private-state i { display:block; width:7px; height:7px; margin:0 auto 8px; border-radius:50%; background:var(--blue); box-shadow:0 0 12px color-mix(in srgb,var(--blue) 70%,transparent); }
.app-main { min-width:0; }
.topbar { position:sticky; top:0; z-index:20; display:flex; justify-content:space-between; gap:24px; align-items:center; min-height:72px; padding:10px 24px; border-bottom:1px solid var(--line); background:color-mix(in srgb,var(--void) 96%,transparent); }
h1,h2,p { margin:0; }
h1 { font-size:clamp(23px,2.5vw,36px); line-height:1; letter-spacing:-.03em; }
h2 { font-size:18px; letter-spacing:-.02em; }
.eyebrow { color:var(--blue); font-size:9px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
.title-lockup #route-summary { margin-top:4px; color:var(--muted); font-size:11px; }
.top-actions,.actions,.admin-row { display:flex; flex-wrap:wrap; gap:8px; }
main { width:min(1720px,100%); margin:0 auto; padding:18px 24px 56px; }
.summary { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:var(--field); }
.summary div { min-height:68px; padding:12px 15px; border-right:1px solid var(--line); }
.summary div:last-child { border:0; }
.summary strong { display:block; color:var(--ink); font-size:22px; line-height:1; font-variant-numeric:tabular-nums; }
.summary span,dt { display:block; margin-top:7px; color:var(--muted); font-size:9px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
.alert { display:flex; justify-content:space-between; gap:18px; padding:10px 14px; border:1px solid var(--line); border-top:0; background:var(--field); color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
.alert strong { color:var(--blue); text-transform:uppercase; letter-spacing:.08em; }
.instrument-head { display:flex; justify-content:space-between; align-items:end; gap:30px; padding:32px 0 13px; }
.instrument-head h2 { margin-top:4px; font-size:clamp(24px,3vw,40px); }
.instrument-head>p { max-width:520px; color:var(--muted); }
.topology { display:grid; grid-template-columns:minmax(680px,1fr) 360px; min-height:610px; border:1px solid var(--line); background:var(--field); }
.matrix-stage { min-width:0; overflow:auto; border-right:1px solid var(--line); background:var(--void); }
.matrix-row { display:grid; grid-template-columns:minmax(240px,1fr) minmax(120px,.55fr) 34px minmax(120px,.55fr) 84px; align-items:center; }
.matrix-columns { position:sticky; top:0; z-index:2; display:grid; grid-template-columns:190px minmax(240px,1fr) minmax(120px,.55fr) 34px minmax(120px,.55fr) 84px; align-items:center; min-width:680px; min-height:40px; padding:0 16px 0 0; border-bottom:1px solid var(--line); background:var(--field); color:var(--muted); font-size:9px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
.matrix-columns span:first-child { padding-left:18px; }
.domain-group { display:grid; grid-template-columns:190px minmax(490px,1fr); min-width:680px; border-bottom:1px solid var(--line); }
.domain-group>header { display:flex; gap:11px; padding:17px 14px 14px 18px; border-right:1px solid var(--line); background:var(--field); }
.domain-group>header h3 { margin:0; font-size:14px; overflow-wrap:anywhere; }
.domain-group>header p { margin-top:5px; color:var(--muted); font-size:10px; }
.domain-state { flex:0 0 auto; width:7px; height:7px; margin-top:5px; border:1px solid var(--blue); border-radius:50%; }
.domain-group[data-domain-state="active"] .domain-state { background:var(--blue); box-shadow:0 0 9px color-mix(in srgb,var(--blue) 45%,transparent); }
.domain-workloads { min-width:0; }
.matrix-row { width:100%; min-height:58px; padding:0 16px 0 14px; border:0; border-bottom:1px solid var(--line); border-radius:0; background:var(--void); text-align:left; }
.matrix-row:last-child { border-bottom:0; }
.matrix-row:hover { background:var(--field); color:var(--ink); }
.matrix-row.selected { background:var(--panel); box-shadow:inset 3px 0 var(--gold); }
.matrix-workload b,.matrix-workload small { display:block; }
.matrix-workload small { margin-top:3px; color:var(--muted); font-size:9px; }
.access-value { color:var(--ink); font-size:12px; overflow-wrap:anywhere; }
.access-arrow { color:var(--muted); font-size:17px; text-align:center; }
.drift-state { justify-self:end; font-size:9px; font-weight:800; letter-spacing:.08em; }
.drift-state.has-drift { color:var(--gold); }
.drift-state.aligned { color:var(--blue); }
.matrix-empty { display:flex; min-height:68px; flex-direction:column; justify-content:center; padding:14px; color:var(--muted); }
.matrix-empty small { margin-top:3px; color:var(--muted); }
.topology-inspector { display:flex; min-width:0; flex-direction:column; padding:22px; background:var(--panel); }
.inspector-kicker { color:var(--blue); font-size:9px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.topology-inspector h3 { margin:8px 0 5px; font-size:27px; letter-spacing:-.035em; overflow-wrap:anywhere; }
.inspector-state { color:var(--muted); }
.inspector-facts { display:grid; grid-template-columns:1fr 1fr; margin:20px 0; border-top:1px solid var(--line); border-left:1px solid var(--line); }
.inspector-facts div { min-width:0; padding:10px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
.inspector-facts dd { margin:3px 0 0; color:var(--ink); font-weight:700; overflow-wrap:anywhere; }
.control-verdict { margin-top:auto; padding:14px; border:1px solid var(--blue); background:var(--field); }
.control-verdict.blocked { border-color:var(--red); }
.control-verdict strong { display:block; margin-bottom:5px; }
.inspect-action { width:100%; margin-top:12px; border-color:var(--gold); color:var(--gold); }
.section-head { display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:35px 0 12px; border-bottom:1px solid var(--line); }
.section-head span,.muted { color:var(--muted); }
.workloads { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-left:1px solid var(--line); }
.workload { padding:18px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--field); }
.workload:target { outline:2px solid var(--gold); outline-offset:-2px; }
.workload-head { display:grid; grid-template-columns:1fr auto; gap:16px; padding-bottom:12px; border-bottom:1px solid var(--line); }
.workload-head h2 { font-size:22px; }.workload-head p { margin-top:5px;color:var(--muted); }
code { padding:3px 5px; border:1px solid var(--line); color:var(--blue); font-family:Arial,Helvetica,sans-serif; font-size:12px; overflow-wrap:anywhere; }
.pills { display:flex; flex-wrap:wrap; margin:12px 0; border-left:1px solid var(--line); }.pill { padding:5px 8px; border:1px solid var(--line); border-left:0; font-size:11px; font-weight:700; }.pill span { margin-right:5px;color:var(--muted);font-weight:400; }.pill.bad { color:var(--red); }.pill.warn { color:var(--gold); }
.facts { display:grid; grid-template-columns:repeat(3,1fr); margin:0; border-left:1px solid var(--line); border-top:1px solid var(--line); }.facts div { min-width:0;padding:9px;border-right:1px solid var(--line);border-bottom:1px solid var(--line); }dd { margin:2px 0 0;overflow-wrap:anywhere;font-weight:700; }
.warning { margin-top:10px;padding:10px;border:1px solid var(--gold);background:var(--panel); }.actions,.admin-row { margin-top:12px; }.admin-row { padding-top:12px;border-top:1px solid var(--line); }.admin-row label { display:grid;gap:4px;color:var(--muted);font-size:9px;font-weight:700;text-transform:uppercase; }
.monitor,.command-panel { margin-top:18px;padding:16px;border:1px solid var(--line);background:var(--field); }.metrics-grid,.plan-grid { display:grid;grid-template-columns:repeat(4,1fr);border-left:1px solid var(--line);border-top:1px solid var(--line); }.metric,.plan-grid article { padding:14px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--field); }.metric p { margin-top:5px;font-size:20px;color:var(--blue);font-variant-numeric:tabular-nums; }.bar { height:3px;margin-top:8px;background:var(--line); }.bar span { display:block;height:100%;background:var(--blue); }.plan-grid { margin-top:18px;grid-template-columns:repeat(5,1fr); }.plan-grid article p { margin:8px 0;color:var(--muted); }pre { max-height:220px;overflow:auto;white-space:pre-wrap;font:12px/1.45 Arial,Helvetica,sans-serif; }
@media(prefers-reduced-motion:no-preference){button,.action{transition:border-color 140ms,color 140ms,background-color 140ms}}
@media(max-width:1120px){.topology{grid-template-columns:minmax(600px,1fr) 320px}.summary{grid-template-columns:repeat(3,1fr)}.summary div:nth-child(3){border-right:0}.workloads{grid-template-columns:1fr}.plan-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.app-shell{grid-template-columns:1fr}.nav-rail{position:sticky;width:100%;height:52px;flex-direction:row;border-right:0;border-bottom:1px solid var(--line)}.brand{width:52px;height:52px;border:0;border-right:1px solid var(--line)}.nav-rail nav{min-width:0;flex:1;flex-direction:row;padding:0}.nav-rail nav a{min-width:0;min-height:52px;flex:1;flex-direction:row;border-left:0;border-bottom:2px solid transparent;font-size:8px}.nav-rail nav a:hover,.nav-rail nav a[aria-current="page"]{border-left:0;border-bottom-color:var(--blue)}.private-state{display:none}.topbar{position:static;align-items:flex-start;flex-direction:column;padding:14px 16px}.top-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.top-actions button{min-width:0;padding:7px 4px}.top-actions input{grid-column:1/-1}main{padding:12px 14px 36px}.summary{grid-template-columns:repeat(2,1fr)}.summary div{border-right:1px solid var(--line)!important;border-bottom:1px solid var(--line)}.instrument-head{align-items:flex-start;flex-direction:column;gap:8px}.instrument-head>p{max-width:100%}.topology{display:block;min-height:0}.matrix-stage{max-width:100%;border-right:0;border-bottom:1px solid var(--line)}.topology-inspector{min-height:390px}.alert,.section-head{align-items:flex-start;flex-direction:column}.facts,.metrics-grid,.plan-grid{grid-template-columns:1fr}.inspector-facts{grid-template-columns:1fr 1fr}}
"""
