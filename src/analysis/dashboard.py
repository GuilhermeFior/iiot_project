"""Exporta um painel HTML autocontido para um experimento de telemetria."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo.collection import Collection

from src.ingestion.consume_telemetry import mongo_settings_from_environment
from src.ingestion.repository import MongoTelemetryRepository
from src.publisher.telemetry import PLANT_ID, TANK_ID


def dashboard_records(collection: Collection, run_id: str) -> list[dict[str, Any]]:
    """Recupera uma execução em ordem de sequência, não de hora de recebimento."""
    query = {
        "source.plant_id": PLANT_ID,
        "source.tank_id": TANK_ID,
        "experiment.run_id": run_id,
    }
    projection = {
        "_id": 0,
        "sequence": 1,
        "timestamp": 1,
        "measurements.ph": 1,
        "measurements.effluent_flow_l_s": 1,
        "measurements.acid_flow_l_s": 1,
        "controller.setpoint_ph": 1,
        "controller.error_ph": 1,
        "anomaly.type": 1,
    }
    return list(collection.find(query, projection).sort("sequence", 1))


def serialize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduz documentos MongoDB aos campos necessários no navegador."""
    serialized = []
    for item in records:
        controller = item["controller"]
        measurements = item["measurements"]
        timestamp = item["timestamp"]
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        serialized.append(
            {
                "sequence": item["sequence"],
                "timestamp": timestamp,
                "ph": measurements["ph"],
                "estimatedPh": controller["setpoint_ph"] - controller["error_ph"],
                "effluentFlow": measurements["effluent_flow_l_s"],
                "acidFlow": measurements["acid_flow_l_s"],
                "anomaly": item.get("anomaly", {}).get("type"),
            }
        )
    return serialized


def build_dashboard_html(
    run_id: str,
    records: list[dict[str, Any]],
    detection: dict[str, Any] | None = None,
) -> str:
    """Monta um único arquivo HTML sem bibliotecas externas."""
    if not records:
        raise ValueError("não há registros para gerar o painel")

    compact_records = serialize_records(records)
    anomaly_counts = Counter(
        item["anomaly"] for item in compact_records if item["anomaly"]
    )
    payload = json.dumps(
        {
            "runId": run_id,
            "records": compact_records,
            "anomalyCounts": anomaly_counts,
            "detection": detection or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    title = escape(f"Painel IIoT — experimento {run_id}")
    return """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; color: #172033; background: #f5f7fb; }
body { max-width: 1280px; margin: 0 auto; padding: 28px; }
h1 { margin: 0; font-size: 1.7rem; } .subtitle { color: #526078; margin-top: 8px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin:24px 0; }
.card, .panel { background:#fff; border:1px solid #e1e6f0; border-radius:12px; box-shadow:0 2px 8px #1720330d; padding:18px; }
.card .value { font-size:1.6rem; font-weight:700; color:#16213e; margin-top:5px; } .label { color:#526078; font-size:.88rem; }
.panel { margin-bottom:18px; } canvas { width:100%; height:310px; display:block; } .legend { display:flex; gap:17px; flex-wrap:wrap; font-size:.86rem; color:#3d4a60; }
.legend span::before { content:""; display:inline-block; width:20px; height:3px; margin:0 6px 3px 0; vertical-align:middle; background:var(--color); }
table { width:100%; border-collapse:collapse; font-size:.92rem; } th,td { text-align:left; border-bottom:1px solid #e6eaf1; padding:9px; } th { color:#526078; }
.note { color:#526078; font-size:.88rem; line-height:1.45; } code { background:#edf1f8; padding:2px 5px; border-radius:4px; }
</style>
</head>
<body>
<h1>Monitoramento IIoT de neutralização de pH</h1>
<div class="subtitle">Experimento <code id="run-id"></code> · visualização exportada do MongoDB Time Series</div>
<div class="cards" id="cards"></div>
<section class="panel"><div class="legend"><span style="--color:#2563eb">pH medido</span><span style="--color:#7c3aed">pH estimado pelo processo</span><span style="--color:#ef4444">faixa rotulada como anomalia</span></div><canvas id="ph-chart" width="1160" height="310"></canvas></section>
<section class="panel"><div class="legend"><span style="--color:#059669">vazão afluente</span><span style="--color:#f59e0b">vazão de ácido</span></div><canvas id="flow-chart" width="1160" height="310"></canvas></section>
<section class="panel"><h2>Métricas dos detectores</h2><table><thead><tr><th>Anomalia</th><th>Precisão</th><th>Revocação</th><th>F1-score</th></tr></thead><tbody id="metrics"></tbody></table><p class="note">Os rótulos simulados são usados apenas na avaliação posterior. As curvas seguem a sequência de publicação para preservar a ordem causal, inclusive quando há atraso de comunicação no timestamp.</p></section>
<script>
const data = __DATA__;
const palette = {process_disturbance:'#dc2626', sensor_noise:'#ea580c', sensor_stuck:'#7c3aed', sensor_out_of_range:'#be123c', communication_delay:'#0369a1'};
document.querySelector('#run-id').textContent = data.runId;
const counts = data.anomalyCounts;
const cards = [['Observações', data.records.length], ['Anomalias rotuladas', Object.values(counts).reduce((a,b)=>a+b,0)], ...Object.entries(counts).map(([k,v])=>[k,v])];
document.querySelector('#cards').innerHTML = cards.map(([label,value]) => `<div class="card"><div class="label">${label.replaceAll('_',' ')}</div><div class="value">${value}</div></div>`).join('');
function chart(canvasId, keys, colors) {
  const canvas=document.querySelector(canvasId), ctx=canvas.getContext('2d'), records=data.records, w=canvas.width, h=canvas.height, pad={l:52,r:18,t:18,b:31};
  const values=records.flatMap(item=>keys.map(key=>item[key])); const min=Math.min(...values), max=Math.max(...values), range=Math.max(max-min,0.01); const y=v=>pad.t+(h-pad.t-pad.b)*(1-(v-min)/range); const x=i=>pad.l+(w-pad.l-pad.r)*i/Math.max(records.length-1,1);
  ctx.clearRect(0,0,w,h); ctx.fillStyle='#526078'; ctx.font='12px Arial'; ctx.fillText(max.toFixed(2),4,pad.t+4); ctx.fillText(min.toFixed(2),4,h-pad.b+4);
  records.forEach((item,i)=>{ if(item.anomaly){ctx.fillStyle=(palette[item.anomaly]||'#ef4444')+'22'; const next=x(i+1)-x(i)||1; ctx.fillRect(x(i)-next/2,pad.t,next,h-pad.t-pad.b);} });
  ctx.strokeStyle='#cbd5e1'; ctx.beginPath(); ctx.moveTo(pad.l,pad.t); ctx.lineTo(pad.l,h-pad.b); ctx.lineTo(w-pad.r,h-pad.b); ctx.stroke();
  keys.forEach((key,series)=>{ctx.strokeStyle=colors[series]; ctx.lineWidth=1.7; ctx.beginPath(); records.forEach((item,i)=>{const command=i?'lineTo':'moveTo';ctx[command](x(i),y(item[key]));});ctx.stroke();});
  ctx.fillStyle='#526078'; ctx.fillText(`sequência: ${records[0].sequence}–${records.at(-1).sequence}`,pad.l,h-8);
}
chart('#ph-chart',['ph','estimatedPh'],['#2563eb','#7c3aed']); chart('#flow-chart',['effluentFlow','acidFlow'],['#059669','#f59e0b']);
const detectors=data.detection.detectors||{}; document.querySelector('#metrics').innerHTML=Object.entries(detectors).map(([name,result])=>{const m=result.metrics;return `<tr><td>${name}</td><td>${m.precision.toFixed(4)}</td><td>${m.recall.toFixed(4)}</td><td>${m.f1_score.toFixed(4)}</td></tr>`}).join('') || '<tr><td colspan="4">Arquivo de métricas não informado.</td></tr>';
</script>
</body></html>""".replace("__TITLE__", title).replace("__DATA__", payload)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exporta um painel HTML autocontido de um experimento IIoT."
    )
    parser.add_argument("--run-id", required=True, help="UUID do lote experimental.")
    parser.add_argument(
        "--collection",
        choices=("document", "timeseries"),
        default="timeseries",
        help="Coleção MongoDB usada no painel.",
    )
    parser.add_argument(
        "--detection-input",
        type=Path,
        help="JSON opcional produzido por multi_anomaly_detection.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/dashboard/iiot_experiment_dashboard.html"),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    detection = (
        json.loads(arguments.detection_input.read_text(encoding="utf-8"))
        if arguments.detection_input
        else None
    )
    load_dotenv()
    repository = MongoTelemetryRepository(mongo_settings_from_environment())
    try:
        collection_name = (
            repository.settings.document_collection
            if arguments.collection == "document"
            else repository.settings.timeseries_collection
        )
        records = dashboard_records(repository.database[collection_name], arguments.run_id)
    finally:
        repository.close()
    html = build_dashboard_html(arguments.run_id, records, detection)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(html, encoding="utf-8")
    print(f"Painel gravado em {arguments.output} ({len(records)} observações).")


if __name__ == "__main__":
    main()
