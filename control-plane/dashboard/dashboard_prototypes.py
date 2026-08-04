"""Render schema-independent PR 5A dashboard state prototypes."""

from __future__ import annotations

import html
import json
from pathlib import Path


FIXTURE = Path(__file__).resolve().parent / "prototypes" / "states.json"


def render_prototypes() -> str:
    fixture = json.loads(FIXTURE.read_text())
    state_options = "".join(
        f'<option value="{html.escape(item["id"])}">{html.escape(item["label"])}</option>'
        for item in fixture["states"]
    )
    surface_options = "".join(
        f'<option value="{html.escape(item["id"])}">{html.escape(item["label"])}</option>'
        for item in fixture["surfaces"]
    )
    payload = json.dumps(fixture, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Argus state prototypes</title><link rel="icon" href="./favicon.svg"><link rel="stylesheet" href="./style.css"></head>
<body class="prototype-page"><header class="prototype-header"><a class="prototype-brand" href="./"><img src="./favicon.svg" alt="" width="40" height="40"><span><strong>Argus</strong><small>PR 5A state prototypes</small></span></a><p>{html.escape(fixture["notice"])}</p></header>
<main><form class="prototype-controls"><label>Surface<select id="prototype-surface">{surface_options}</select></label><label>State<select id="prototype-state">{state_options}</select></label></form><section class="prototype-frame" id="prototype-frame" aria-live="polite"></section></main>
<script type="application/json" id="prototype-fixture">{payload}</script><script>
const fixture=JSON.parse(document.getElementById("prototype-fixture").textContent);const frame=document.getElementById("prototype-frame");const stateSelect=document.getElementById("prototype-state");const surfaceSelect=document.getElementById("prototype-surface");
function escapeText(value){{const node=document.createElement("span");node.textContent=String(value);return node.innerHTML;}}
function render(){{const state=fixture.states.find(item=>item.id===stateSelect.value);const surface=fixture.surfaces.find(item=>item.id===surfaceSelect.value);frame.dataset.tone=state.tone;frame.innerHTML=`<p class="prototype-state">${{escapeText(state.label)}}</p><h1>${{escapeText(surface.label)}}</h1><h2>${{escapeText(state.headline)}}</h2><p>${{escapeText(state.detail)}}</p><dl>${{surface.fields.map(field=>`<div><dt>${{escapeText(field)}}</dt><dd>${{state.id==="loading"?"Loading":"Illustrative value"}}</dd></div>`).join("")}}</dl><button type="button" ${{state.id==="loading"?'disabled aria-disabled="true"':""}}>${{escapeText(state.action)}}</button>`;}}stateSelect.addEventListener("change",render);surfaceSelect.addEventListener("change",render);render();
</script></body></html>"""
