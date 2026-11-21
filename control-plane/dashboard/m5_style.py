"""Orbital Operations Plot visual system for the private M5 operator surface."""

M5_CSS = r"""
:root { color-scheme:dark; --void:#070A12; --field:#0D1324; --panel:#141D33; --line:#2A3550; --ink:#F3F6FC; --muted:#9AA8BF; --blue:#68A7FF; --green:#45D69A; --gold:#F5C85B; --red:#FF6B72; }
:root[data-theme="light"] { color-scheme:light; --void:#F5F7FB; --field:#FFFFFF; --panel:#EAF0FA; --line:#BCC8D9; --ink:#101828; --muted:#52627A; --blue:#1769D2; --green:#147A50; --gold:#9A6500; --red:#C5323A; }
* { box-sizing:border-box; }
html { min-width:320px; background:var(--void); scroll-behavior:smooth; }
[hidden] { display:none !important; }
.no-js .app-shell { display:none; }
.sr-only { position:absolute!important; width:1px!important; height:1px!important; padding:0!important; margin:-1px!important; overflow:hidden!important; clip:rect(0,0,0,0)!important; white-space:nowrap!important; border:0!important; }
body { margin:0; min-height:100vh; background:var(--void); color:var(--ink); font:14px/1.48 Arial,Helvetica,sans-serif; }
button,select,input { font:inherit; }
button,.action { min-height:44px; padding:9px 13px; border:1px solid var(--line); border-radius:6px; background:var(--field); color:var(--ink); cursor:pointer; font-weight:700; text-decoration:none; }
button:hover,.action:hover { border-color:var(--blue); color:var(--blue); }
button:focus-visible,.action:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible,[role="button"]:focus-visible { outline:3px solid var(--blue); outline-offset:3px; }
button:disabled,.action.disabled { color:var(--muted); border-style:dashed; border-color:var(--muted); background:transparent; cursor:not-allowed; }
button:disabled:hover,.action.disabled:hover { border-color:var(--muted); color:var(--muted); }
input,select { min-height:44px; border:1px solid var(--line); border-radius:6px; background:var(--field); color:var(--ink); padding:7px 9px; }
.app-shell { display:grid; grid-template-columns:72px minmax(0,1fr); min-height:100vh; }
.nav-rail { position:sticky; top:0; z-index:30; height:100vh; display:flex; flex-direction:column; align-items:center; border-right:1px solid var(--line); background:var(--field); }
.brand { display:grid; place-items:center; width:72px; height:72px; border-bottom:1px solid var(--line); text-decoration:none; }
.brand img { display:block; width:40px; height:40px; }
.nav-rail nav { display:flex; flex-direction:column; width:100%; padding-top:22px; }
.nav-rail nav a { display:flex; min-height:72px; align-items:center; justify-content:center; border-left:2px solid transparent; color:var(--muted); font-size:12px; font-weight:700; text-decoration:none; }
.nav-rail nav a:hover,.nav-rail nav a[aria-current="page"] { border-left-color:var(--blue); color:var(--ink); background:var(--panel); }
.private-state { margin-top:auto; padding:0 0 20px; color:var(--muted); font-size:12px; text-align:center; text-transform:uppercase; }
.private-state i { display:block; width:7px; height:7px; margin:0 auto 8px; border-radius:50%; background:var(--blue); }
.app-main { min-width:0; }
.topbar { position:sticky; top:0; z-index:20; display:flex; justify-content:space-between; gap:24px; align-items:center; min-height:72px; padding:10px 24px; border-bottom:1px solid var(--line); background:color-mix(in srgb,var(--void) 96%,transparent); }
h1,h2,p { margin:0; }
h1 { font-size:clamp(23px,2.5vw,36px); line-height:1; letter-spacing:-.03em; }
h2 { font-size:18px; letter-spacing:-.02em; }
.title-lockup #route-summary { margin-top:4px; color:var(--muted); font-size:12px; }
.state-age { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:6px; color:var(--ink); font-size:12px; }
.state-age .state-badge { min-height:22px; padding:2px 7px; }
.top-actions,.actions { display:flex; flex-wrap:wrap; gap:8px; }
.signin-form { display:flex; flex-wrap:wrap; align-items:center; gap:8px; flex-basis:100%; justify-content:flex-end; }
.signin-form[hidden] { display:none; }
.signin-form #admin-totp { width:11ch; }
.signin-message { flex-basis:100%; margin:0; text-align:right; color:var(--muted); font-size:13px; }
.signin-message:empty { display:none; }
.signin-message[data-tone="bad"] { color:var(--red); }
.primary-action { border-color:var(--blue); background:var(--blue); color:var(--void); }
.primary-action:hover { border-color:var(--ink); color:var(--void); }
.utility-action { color:var(--muted); font-weight:600; }
.no-js-state { display:flex; align-items:center; gap:16px; max-width:680px; margin:48px auto; padding:24px; border:1px solid var(--line); background:var(--field); }
.no-js-state p { margin-top:5px; color:var(--muted); }
.no-js-state h2 { margin-top:6px; }
.session-control { display:grid; grid-template-columns:auto minmax(116px,auto) auto; align-items:center; gap:8px; min-height:38px; padding-left:10px; border:1px solid var(--line); border-radius:6px; background:var(--field); font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.session-signal { width:7px; height:7px; border-radius:50%; background:var(--gold); box-shadow:0 0 9px color-mix(in srgb,var(--gold) 55%,transparent); }
.session-copy { min-width:0; line-height:1.15; }
.session-copy strong,.session-copy small { display:block; }
.session-copy strong { white-space:nowrap; }
.session-copy strong { font-size:12px; }
.session-copy small { max-width:250px; margin-top:3px; color:var(--muted); font-size:12px; }
.session-control button { min-height:44px; border-width:0 0 0 1px; border-radius:0 5px 5px 0; }
.session-control[data-state="authenticated"] { border-color:var(--green); }
.session-control[data-state="authenticated"] .session-signal { background:var(--green); box-shadow:0 0 9px color-mix(in srgb,var(--green) 60%,transparent); }
.session-control[data-state="authenticated"] .session-copy strong { color:var(--green); }
.session-control[data-state="expired"] { border-color:var(--red); }
.session-control[data-state="expired"] .session-signal { background:var(--red); box-shadow:0 0 9px color-mix(in srgb,var(--red) 60%,transparent); }
.session-control[data-state="expired"] .session-copy strong { color:var(--red); }
.session-control[data-state="unavailable"] { border-color:var(--gold); }
.session-control[data-state="unavailable"] .session-copy strong { color:var(--gold); }
main { width:min(1720px,100%); margin:0 auto; padding:18px 24px 56px; }
dt { display:block; margin-top:7px; color:var(--muted); font-size:12px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
.alert { display:flex; justify-content:space-between; gap:18px; padding:10px 14px; border:1px solid var(--line); border-top:0; background:var(--field); color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.alert strong { color:var(--blue); text-transform:uppercase; letter-spacing:.08em; }
.alert[data-state="open"] { border-color:var(--red); color:var(--ink); }
.alert[data-state="open"] strong { color:var(--red); }
.evidence-state { margin-top:18px; border:1px solid var(--line); background:var(--field); }
.evidence-state[data-state="error"],.evidence-state[data-state="conflict"] { border-color:color-mix(in srgb,var(--red) 62%,var(--line)); }
.evidence-state[data-state="stale"],.evidence-state[data-state="partial"] { border-color:color-mix(in srgb,var(--gold) 62%,var(--line)); }
.state-badge { display:inline-flex; min-height:30px; align-items:center; padding:5px 9px; border:1px solid currentColor; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.state-badge.info { color:var(--blue); }.state-badge.good { color:var(--green); }.state-badge.warn { color:var(--gold); }.state-badge.bad { color:var(--red); }
.evidence-state-body { display:grid; grid-template-columns:minmax(260px,1.15fr) minmax(280px,1fr); gap:18px; padding:0 18px 18px; }
.evidence-state-copy { min-width:0; padding-top:4px; }.evidence-state-copy>strong { display:block; font-size:18px; }.evidence-state-copy>p { max-width:62ch; margin-top:6px; color:var(--muted); }.evidence-action { display:inline-flex; align-items:center; margin-top:14px; border-color:var(--gold); color:var(--gold); }
.evidence-state-meta { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:0; border-top:1px solid var(--line); border-left:1px solid var(--line); }.evidence-state-meta div { min-width:0; padding:10px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.evidence-state-meta dd { margin:4px 0 0; color:var(--ink); font-weight:700; overflow-wrap:anywhere; }
.evidence-state-detail { grid-column:1/-1; display:grid; grid-template-columns:1fr 1fr; gap:18px; padding-top:14px; border-top:1px solid var(--line); }.evidence-state-sources,.evidence-state-blockers ul { display:grid; gap:1px; margin:7px 0 0; padding:0; border:1px solid var(--line); list-style:none; }.evidence-state-sources li { display:flex; justify-content:space-between; gap:12px; min-height:38px; align-items:center; padding:7px 10px; background:var(--void); }.evidence-state-sources li+li { border-top:1px solid var(--line); }.evidence-state-sources span { min-width:0; overflow-wrap:anywhere; color:var(--muted); font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }.evidence-state-sources strong { color:var(--ink); font-size:12px; text-transform:uppercase; }.evidence-state-empty { margin-top:7px; padding:10px; border:1px solid var(--line); color:var(--muted); }.evidence-state-blockers { margin-top:7px; border:1px solid var(--line); }.evidence-state-blockers summary { min-height:38px; padding:9px 10px; color:var(--gold); cursor:pointer; font-weight:700; }.evidence-state-blockers ul { margin:0 10px 10px; }.evidence-state-blockers li { padding:7px 9px; background:var(--void); color:var(--muted); font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; overflow-wrap:anywhere; }.evidence-state-blockers li+li { border-top:1px solid var(--line); }
.workload-reconciliation { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(220px,1fr); gap:16px; margin-top:12px; padding:13px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }.workload-reconciliation>div { min-width:0; }.workload-reconciliation>.state-badge { justify-self:start; align-self:start; }.workload-reconciliation>div>strong { display:block; margin-top:4px; color:var(--ink); font-size:15px; text-transform:capitalize; }.workload-reconciliation>div>p:last-child { margin-top:4px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }.workload-reconciliation>dl { display:grid; grid-template-columns:1fr 1fr; margin:0; border-top:1px solid var(--line); border-left:1px solid var(--line); }.workload-reconciliation>dl div { min-width:0; padding:9px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.workload-reconciliation dd { margin:3px 0 0; color:var(--ink); font-weight:700; overflow-wrap:anywhere; }
.section-head { display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:35px 0 12px; border-bottom:1px solid var(--line); }
.section-head span,.muted { color:var(--muted); }
.workloads { display:grid; border:1px solid var(--line); background:var(--field); }
.workload { min-width:0; border-bottom:1px solid var(--line); background:var(--field); }
.workload:last-child { border-bottom:0; }
.workload[data-health="down"] { box-shadow:inset 3px 0 0 var(--red); background:color-mix(in srgb,var(--red) 7%,var(--field)); }
.tone-good { color:var(--green); }.tone-warn { color:var(--gold); }.tone-bad { color:var(--red); }
.workload:target { outline:2px solid var(--gold); outline-offset:-2px; }
.workload-overview { display:grid; grid-template-columns:minmax(180px,1.35fr) minmax(140px,1fr) minmax(90px,.65fr) minmax(150px,1fr) minmax(110px,.75fr) auto; gap:16px; align-items:center; min-height:70px; padding:10px 14px; }
.workload-overview>span { min-width:0; }
.workload-overview>span::before { content:attr(data-label); display:block; margin-bottom:3px; color:var(--muted); font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
.workload-overview strong,.workload-overview small { display:block; overflow-wrap:anywhere; }
.workload-overview small { margin-top:3px; color:var(--muted); font-size:12px; }
.workload-identity strong { font-size:15px; }
.workload-overview .inspect-action { display:inline-flex; justify-self:end; align-items:center; }
.workload-detail { padding:20px; border-top:1px solid var(--line); background:var(--void); }
.workload.detail-open .workload-overview { background:var(--panel); }
.detail-heading-actions { display:flex; align-items:center; gap:8px; }
.detail-close { display:inline-flex; min-height:44px; align-items:center; padding:7px 10px; color:var(--muted); font-weight:700; }
.workload-head { display:grid; grid-template-columns:1fr auto; gap:16px; padding:0 20px 14px 0; border-bottom:1px solid var(--line); }
.workload-head h2 { font-size:22px; }.workload-head p { max-width:68ch; margin-top:5px;color:var(--muted); text-wrap:pretty; }
code { padding:3px 5px; border:1px solid var(--line); color:var(--blue); font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; overflow-wrap:anywhere; }
.workload-notice { margin:12px 0 0; border:1px solid color-mix(in srgb,var(--gold) 55%,var(--line)); background:color-mix(in srgb,var(--gold) 8%,var(--field)); }.workload-notice summary { padding:9px 12px; color:var(--gold); font-weight:700; cursor:pointer; }.workload-notice p { padding:0 12px 11px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.workload-evidence { border-bottom:1px solid var(--line); }.workload-evidence>summary { display:flex; justify-content:space-between; gap:12px; padding:12px 0; color:var(--ink); font-weight:700; cursor:pointer; list-style:none; }.workload-evidence>summary::-webkit-details-marker { display:none; }.workload-evidence>summary::before { content:"＋"; color:var(--blue); }.workload-evidence[open]>summary::before { content:"−"; }.workload-evidence>summary span { flex:1; }.workload-evidence>summary small { color:var(--muted); font-weight:400; }
.fact-groups { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); padding:0 0 14px; }.fact-groups section { min-width:0; padding:0 14px; border-left:1px solid var(--line); }.fact-groups section:first-child { padding-left:0; border-left:0; }.fact-groups section:last-child { padding-right:0; }.fact-groups h3 { margin:0 0 6px; color:var(--muted); font-size:12px; letter-spacing:.1em; text-transform:uppercase; }
.facts { margin:0; }.facts div { display:grid; grid-template-columns:minmax(88px,.7fr) minmax(0,1.3fr); gap:10px; padding:6px 0; border-top:1px solid color-mix(in srgb,var(--line) 60%,transparent); }.facts div:first-child { border-top:0; }.facts dt { margin:0; }.facts dd { margin:0;overflow-wrap:anywhere;font-weight:700; }
.workload-controls { margin-top:16px; padding-top:16px; border-top:1px solid var(--line); }.control-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 16px; }.control-head h3 { margin:0; font-size:16px; }.control-head .workload-links { margin-left:auto; }.agent-state { display:flex; align-items:center; gap:7px; font-size:12px; font-weight:700; }.agent-state::before { content:""; width:7px; height:7px; border-radius:50%; }.agent-state.available { color:var(--blue); }.agent-state.available::before { background:var(--blue); box-shadow:0 0 8px color-mix(in srgb,var(--blue) 55%,transparent); }.agent-state.offline { color:var(--red); }.agent-state.offline::before { background:var(--red); }
.workload-links,.command-actions { display:flex; flex-wrap:wrap; gap:8px; }.operation-history { min-height:42px; padding-top:10px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }.history-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:6px; }.history-head strong { color:var(--ink); font-size:12px; letter-spacing:.06em; text-transform:uppercase; }.history-head span { color:var(--muted); font-size:12px; }.history-list { margin:0; padding:0; border-top:1px solid var(--line); list-style:none; }.history-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:9px; align-items:center; min-height:44px; border-bottom:1px solid var(--line); }.history-state { min-width:76px; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; }.history-state.good { color:var(--green); }.history-state.warn { color:var(--gold); }.history-state.bad { color:var(--red); }.history-copy { min-width:0; }.history-copy strong,.history-copy small { display:block; overflow-wrap:anywhere; }.history-copy strong { color:var(--ink); font-size:12px; }.history-copy small { margin-top:2px; color:var(--muted); font-size:12px; }.history-item button { min-height:30px; padding:4px 8px; font-size:12px; }.history-empty { padding:10px 0 2px; }
.monitor { margin-top:18px;padding:16px;border:1px solid var(--line);background:var(--field); }.command-panel { position:fixed; z-index:50; top:14px; right:14px; bottom:14px; width:min(520px,calc(100vw - 28px)); padding:18px; overflow:auto; border:1px solid color-mix(in srgb,var(--blue) 58%,var(--line)); background:var(--field); box-shadow:0 18px 60px color-mix(in srgb,#000 56%,transparent); }.command-panel:focus { outline:none; }.command-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }.command-heading { display:flex; align-items:center; gap:12px; min-width:0; }.command-heading h2 { margin-top:3px; font-size:20px; text-transform:none; overflow-wrap:anywhere; }.result-badge { flex:0 0 auto; padding:5px 8px; border:1px solid currentColor; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }.result-badge.info { color:var(--blue); }.result-badge.good { color:var(--green); }.result-badge.warn { color:var(--gold); }.result-badge.bad { color:var(--red); }.command-summary { max-width:80ch; margin-top:16px; color:var(--ink); font-size:15px; text-wrap:pretty; }.command-highlights { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); margin:14px 0 0; border-top:1px solid var(--line); border-left:1px solid var(--line); }.command-highlights div { min-width:0; padding:9px 10px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.command-highlights dd { margin:3px 0 0; overflow-wrap:anywhere; font-weight:700; }.command-assurance { display:grid; gap:1px; margin-top:14px; background:var(--line); border:1px solid var(--line); }.assurance-row { padding:10px 11px; background:var(--void); }.assurance-row strong { display:block; margin-bottom:3px; color:var(--muted); font-size:12px; letter-spacing:.09em; text-transform:uppercase; }.assurance-row span,.assurance-row ul { color:var(--ink); overflow-wrap:anywhere; }.assurance-row ul { margin:4px 0 0; padding-left:18px; }.command-details { margin-top:12px; }.command-details summary { display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-bottom:1px solid var(--line); color:var(--muted); font-weight:700; cursor:pointer; }.command-details summary span { font-size:12px; font-weight:400; letter-spacing:.08em; text-transform:uppercase; }.command-details pre { margin:0; padding:12px; max-height:280px; background:var(--void); color:var(--muted); }.command-actions { margin-top:12px; }.metrics-grid { display:grid;grid-template-columns:repeat(4,1fr);border-left:1px solid var(--line);border-top:1px solid var(--line); }.metric { padding:14px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--field); }.metric p { margin-top:5px;font-size:20px;color:var(--blue);font-variant-numeric:tabular-nums; }.bar { height:3px;margin-top:8px;background:var(--line); }.bar span { display:block;height:100%;background:var(--blue); }pre { max-height:220px;overflow:auto;white-space:pre-wrap;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.history-item button { min-height:44px; padding:7px 9px; }
.prototype-page main { width:min(900px,100%); }
.prototype-header { display:flex; justify-content:space-between; gap:24px; align-items:center; padding:16px 24px; border-bottom:1px solid var(--line); background:var(--field); }
.prototype-header>p { max-width:62ch; color:var(--muted); }
.prototype-brand { display:flex; align-items:center; gap:11px; color:var(--ink); text-decoration:none; }
.prototype-brand strong,.prototype-brand small { display:block; }.prototype-brand small { color:var(--muted); }
.prototype-controls { display:flex; gap:12px; margin-bottom:20px; }.prototype-controls label { display:grid; gap:5px; color:var(--muted); font-weight:700; }
.prototype-frame { min-height:390px; padding:28px; border:1px solid var(--line); background:var(--field); }
.prototype-frame h1 { margin-top:7px; }.prototype-frame h2 { margin-top:28px; font-size:24px; }.prototype-frame>p:not(.prototype-state) { max-width:68ch; margin-top:8px; color:var(--muted); }
.prototype-state { color:var(--blue); font-weight:800; }.prototype-frame[data-tone="warning"] .prototype-state { color:var(--gold); }.prototype-frame[data-tone="danger"] .prototype-state { color:var(--red); }.prototype-frame[data-tone="success"] .prototype-state { color:var(--green); }
.prototype-frame dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); margin:24px 0; border-top:1px solid var(--line); }.prototype-frame dl div { padding:11px 0; border-bottom:1px solid var(--line); }.prototype-frame dd { margin:3px 0 0; font-weight:700; }
@media(prefers-reduced-motion:no-preference){button,.action{transition:border-color 140ms,color 140ms,background-color 140ms}}
@media(max-width:760px){.app-shell{grid-template-columns:1fr}.nav-rail{position:sticky;width:100%;height:52px;flex-direction:row;border-right:0;border-bottom:1px solid var(--line)}.brand{width:52px;height:52px;border:0;border-right:1px solid var(--line)}.nav-rail nav{min-width:0;flex:1;flex-direction:row;padding:0}.nav-rail nav a{min-width:0;min-height:52px;flex:1;flex-direction:row;border-left:0;border-bottom:2px solid transparent;font-size:12px}.nav-rail nav a:hover,.nav-rail nav a[aria-current="page"]{border-left:0;border-bottom-color:var(--blue)}.private-state{display:none}.topbar{position:static;align-items:flex-start;flex-direction:column;padding:14px 16px}.top-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.view-tools{grid-column:1/-1}.view-tools button{flex:1}.top-actions button{min-width:0;padding:7px 4px}.top-actions input{grid-column:1/-1}.signin-form{grid-column:1/-1;justify-content:stretch}.signin-form input{flex:1 1 100%}.signin-message{text-align:left}.session-control{grid-column:1/-1;grid-template-columns:auto minmax(0,1fr) auto}.session-control button{min-height:44px}.session-copy small{max-width:none}main{padding:12px 14px 36px}.evidence-state-body{grid-template-columns:1fr}.evidence-state-detail{grid-template-columns:1fr}.evidence-state-meta{grid-template-columns:1fr 1fr}.workload-reconciliation{grid-template-columns:1fr}.alert,.section-head{align-items:flex-start;flex-direction:column}.command-header{align-items:flex-start;flex-direction:column}.fact-groups{grid-template-columns:1fr}.fact-groups section,.fact-groups section:first-child,.fact-groups section:last-child{padding:10px 0;border-left:0;border-top:1px solid var(--line)}.fact-groups section:first-child{padding-top:0;border-top:0}.metrics-grid{grid-template-columns:1fr}.workload-links{width:100%}.command-panel{top:8px;right:8px;bottom:8px;width:calc(100vw - 16px)}}
@media(max-width:520px){.system-facts{grid-template-columns:1fr}.command-highlights{grid-template-columns:1fr}.history-item{grid-template-columns:auto minmax(0,1fr)}.history-item button{grid-column:2}}
@media(max-width:900px){.workload-overview{grid-template-columns:repeat(2,minmax(0,1fr))}.workload-overview .inspect-action{justify-self:start}}
@media(max-width:760px){.brand img{width:34px;height:34px}.workload-overview{grid-template-columns:1fr;gap:9px;padding:14px}.workload-overview>span{display:grid;grid-template-columns:110px minmax(0,1fr);gap:10px}.workload-overview>span::before{margin:0}.workload-identity{display:block!important}.workload-detail{padding:14px}.detail-heading-actions{align-items:flex-end;flex-direction:column}}
@media(max-width:760px){.prototype-header{align-items:flex-start;flex-direction:column;padding:14px}.prototype-controls{flex-direction:column}.prototype-frame{padding:18px}.prototype-frame dl{grid-template-columns:1fr}}
main [id],.workload { scroll-margin-top:calc(var(--topbar-h,72px) + 12px); }
.active-banner { position:sticky; top:var(--topbar-h,72px); z-index:5; padding:10px 14px; border:1px solid var(--gold); background:var(--panel); font-size:12px; font-weight:700; }
.stages-table,.activity-table { width:100%; border-collapse:collapse; font-size:12px; }.stages-table th,.stages-table td,.activity-table th,.activity-table td { padding:8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }#events { padding-left:0; font-size:12px; }
.stages-table small { display:block; font-size:12px; }
@media(max-width:760px){.stages-table thead{display:none}.stages-table tr,.stages-table th,.stages-table td{display:block}.stages-table tr{padding:8px 0;border-bottom:1px solid var(--line)}.stages-table th,.stages-table td{border:0;padding:4px 0}.stages-table td::before{content:attr(data-label);display:block;color:var(--muted);font-size:12px;font-weight:700;text-transform:uppercase}}
@media(max-width:760px){main [id],.workload{scroll-margin-top:64px}.active-banner{top:52px}}
.view-tools { display:flex; gap:8px; }
.attention { border:1px solid var(--line); background:var(--field); }
.attention-head { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 16px; border-bottom:1px solid var(--line); }
.attention-head h2 { font-size:18px; }
.attention-list { margin:0; padding:0; list-style:none; }
.attention-item { display:grid; grid-template-columns:96px minmax(0,1fr) auto; gap:4px 16px; align-items:center; min-height:56px; padding:9px 16px; border-bottom:1px solid var(--line); }
.attention-item>div { min-width:0; }
.attention-item strong { display:block; overflow-wrap:anywhere; }
.attention-item p { margin-top:2px; color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
.attention-tone { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.attention-tone::before { content:""; flex:0 0 auto; width:8px; height:8px; border-radius:50%; background:currentColor; }
.attention-item[data-tone="bad"] .attention-tone { color:var(--red); }
.attention-item[data-tone="warn"] .attention-tone { color:var(--gold); }
.attention-item[data-tone="good"] .attention-tone { color:var(--green); }
.attention-item[data-tone="info"] .attention-tone { color:var(--blue); }
.attention-item .action,.attention-item button { display:inline-flex; align-items:center; justify-self:end; white-space:nowrap; }
.estate-facts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:0; }
.estate-facts div { min-width:0; padding:10px 16px; border-right:1px solid var(--line); }
.estate-facts div:last-child { border-right:0; }
.estate-facts dt { margin:0; }
.estate-facts dd { margin:3px 0 0; font-size:16px; font-weight:700; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.estate-facts [data-tone="bad"] dd,.system-facts [data-tone="bad"] dd { color:var(--red); }
.estate-facts [data-tone="warn"] dd,.system-facts [data-tone="warn"] dd { color:var(--gold); }
.estate-facts [data-tone="good"] dd { color:var(--green); }
.empty-domains { margin-top:8px; color:var(--muted); font-size:13px; }
.subhead { margin:20px 0 6px; color:var(--muted); font-size:12px; letter-spacing:.1em; text-transform:uppercase; }
#events li { padding:8px 0; border-bottom:1px solid var(--line); color:var(--muted); overflow-wrap:anywhere; }
.system-facts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:0; border-left:1px solid var(--line); border-top:1px solid var(--line); }
.system-facts div { min-width:0; padding:11px 14px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--field); }
.system-facts dt { margin:0; }
.system-facts dd { margin:4px 0 0; font-weight:700; overflow-wrap:anywhere; }
.system-facts code { display:block; width:max-content; max-width:100%; margin-top:6px; font-weight:400; }
.evidence-state-head { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 18px; }
.evidence-state-head h3,.evidence-state-detail h4,.workload-reconciliation h4 { margin:0; }
.evidence-state-head h3 { font-size:16px; }
.evidence-state-detail h4,.workload-reconciliation h4 { color:var(--muted); font-size:12px; letter-spacing:.1em; text-transform:uppercase; }
.workload-context { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:14px 0 0; border-top:1px solid var(--line); border-left:1px solid var(--line); }
.workload-context div { min-width:0; padding:9px 10px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
.workload-context dt { margin:0; }
.workload-context dd { margin:4px 0 0; font-weight:700; overflow-wrap:anywhere; }
.workload-context .drift dd { color:var(--red); }
.control-blocked { display:flex; align-items:center; gap:8px; margin-top:10px; color:var(--red); font-weight:700; }
.action-groups { display:grid; grid-template-columns:minmax(240px,1fr) minmax(0,2fr); gap:24px; margin-top:14px; }
.action-group h4 { margin:0 0 8px; color:var(--muted); font-size:12px; letter-spacing:.1em; text-transform:uppercase; }
.action-hint { max-width:68ch; color:var(--muted); font-size:13px; }
.confirm-field { display:grid; gap:4px; max-width:360px; margin:10px 0 4px; color:var(--muted); font-size:12px; font-weight:700; }
.action-list { display:grid; margin:0; padding:0; list-style:none; }
.action-row { display:grid; grid-template-columns:150px minmax(0,1fr); gap:12px; align-items:center; padding:6px 0; border-bottom:1px solid color-mix(in srgb,var(--line) 60%,transparent); }
.action-row:last-child { border-bottom:0; }
.action-row button { width:100%; }
.action-row small { color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
.action-row.is-blocked small { color:var(--gold); }
.action-row-access { grid-template-columns:150px auto minmax(0,1fr); }
.action-row-access label { display:flex; align-items:center; gap:6px; color:var(--muted); }
@media(max-width:1000px){.action-groups{grid-template-columns:1fr}.system-facts,.workload-context{grid-template-columns:repeat(2,minmax(0,1fr))}.estate-facts{grid-template-columns:repeat(2,minmax(0,1fr))}.estate-facts div:nth-child(2){border-right:0}.estate-facts div:nth-child(-n+2){border-bottom:1px solid var(--line)}}
@media(max-width:760px){.attention-head{padding:12px 14px}.attention-item{grid-template-columns:minmax(0,1fr);padding:12px 14px}.attention-item .action,.attention-item button{justify-self:start}.action-row,.action-row-access{grid-template-columns:minmax(0,1fr);gap:4px;padding:8px 0}.action-row-access label{flex-wrap:wrap}.control-head .workload-links{margin-left:0}}
"""
