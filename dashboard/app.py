"""
dashboard/app.py — FastAPI + Plotly Dashboard

All pages served from a single HTML with Plotly.js charts.
Auto-refresh every 5 seconds via polling.
API endpoints protected by X-API-Key header.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

app = FastAPI(title="XAUUSD Pro Scalper", version="2.0.0", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET"], allow_headers=["*"])

_api_key_hdr = APIKeyHeader(name="X-API-Key", auto_error=False)
_state: Dict[str, Any] = {}
_db = None
_health = None


def inject(state: Dict, db, health) -> None:
    global _state, _db, _health
    _state = state
    _db = db
    _health = health


async def _auth(k: str = Depends(_api_key_hdr)):
    from app.config import settings
    exp = settings.dashboard.api_key
    if exp and exp != "changeme" and k != exp:
        raise HTTPException(403, "Invalid API key")
    return k


# ── REST endpoints ────────────────────────────────────────────────

@app.get("/ping")
async def ping():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/overview")
async def overview(_=Depends(_auth)):
    return {
        "account":   _state.get("account", {}),
        "trade":     _state.get("trade", {}),
        "risk":      _state.get("risk", {}),
        "health":    _state.get("health", {}),
        "market":    _state.get("market", {}),
        "of":        _state.get("of", {}),
        "dom":       _state.get("dom", {}),
        "micro":     _state.get("micro", {}),
        "vol":       _state.get("vol", {}),
        "session":   _state.get("session", {}),
        "quality":   _state.get("quality", {}),
        "ml":        _state.get("ml", {}),
        "ts":        datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/trades")
async def trades(status: Optional[str] = None,
                 limit: int = Query(50, le=500), _=Depends(_auth)):
    if _db is None:
        return []
    return _db.get_trades(status=status, limit=limit)


@app.get("/api/stats/daily")
async def daily(days: int = Query(30, le=365), _=Depends(_auth)):
    if _db is None:
        return []
    return _db.get_daily_stats(days)


@app.get("/api/events")
async def events(limit: int = Query(50, le=500),
                 severity: Optional[str] = None, _=Depends(_auth)):
    if _db is None:
        return []
    return _db.get_events(limit=limit, severity=severity)


@app.get("/api/health")
async def health_ep(_=Depends(_auth)):
    if _health and _health.latest:
        return _health.latest.to_dict()
    return _state.get("health", {"healthy": False})


@app.get("/api/ml")
async def ml_ep(_=Depends(_auth)):
    return _state.get("ml", {})


@app.get("/api/charts/equity")
async def equity_chart(_=Depends(_auth)):
    if _db is None:
        return {"dates": [], "values": []}
    stats = list(reversed(_db.get_daily_stats(90)))
    dates, vals = [], []
    cum = 0.0
    for s in stats:
        cum += s.get("net_pnl", 0)
        dates.append(s["date"])
        vals.append(round(cum, 2))
    return {"dates": dates, "values": vals}


@app.get("/api/charts/winrate")
async def wr_chart(_=Depends(_auth)):
    if _db is None:
        return {"dates": [], "values": []}
    stats = list(reversed(_db.get_daily_stats(30)))
    return {
        "dates":  [s["date"] for s in stats],
        "values": [s.get("win_rate", 0) for s in stats],
    }


@app.get("/api/charts/quality_hist")
async def quality_hist(_=Depends(_auth)):
    if _db is None:
        return {"buckets": [], "counts": []}
    trades = _db.get_closed_trades(200)
    scores = [t.get("quality_score", 0) for t in trades if t.get("quality_score")]
    buckets = list(range(60, 101, 5))
    counts  = [sum(1 for s in scores if b <= s < b + 5) for b in buckets]
    return {"buckets": [f"{b}-{b+4}" for b in buckets], "counts": counts}


# ── Full HTML dashboard ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XAUUSD Pro Scalper</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
:root{--bg:#0d1117;--s:#161b22;--b:#30363d;--t:#e6edf3;--m:#8b949e;
  --g:#2ea043;--r:#da3633;--y:#d29922;--bl:#58a6ff;--o:#f0883e;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--t);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;font-size:13px;}
header{background:var(--s);border-bottom:1px solid var(--b);padding:10px 18px;
  display:flex;align-items:center;justify-content:space-between;}
header h1{font-size:15px;font-weight:700;color:var(--bl);}
.grid{display:grid;gap:10px;padding:14px;}
.g4{grid-template-columns:repeat(4,1fr);}
.g3{grid-template-columns:repeat(3,1fr);}
.g2{grid-template-columns:repeat(2,1fr);}
.g1{grid-template-columns:1fr;}
@media(max-width:1100px){.g4{grid-template-columns:repeat(2,1fr);}
  .g3{grid-template-columns:repeat(2,1fr);}}
@media(max-width:650px){.g4,.g3,.g2{grid-template-columns:1fr;}}
.card{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:12px;}
.ctitle{font-size:10px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--m);margin-bottom:8px;}
.kv{font-size:22px;font-weight:700;font-family:monospace;}
.sub{font-size:11px;color:var(--m);margin-top:2px;}
.row{display:flex;justify-content:space-between;padding:3px 0;
  border-bottom:1px solid var(--b);font-size:12px;}
.row:last-child{border:0;}
.lbl{color:var(--m);}
.val{font-family:monospace;font-weight:600;}
.g{color:var(--g);}.r{color:var(--r);}.y{color:var(--y);}.bl{color:var(--bl);}
.pb{height:5px;background:var(--b);border-radius:3px;overflow:hidden;margin-top:3px;}
.pf{height:100%;border-radius:3px;transition:width .4s;}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;}
.tbl{width:100%;border-collapse:collapse;}
.tbl th{text-align:left;padding:5px 7px;font-size:10px;text-transform:uppercase;
  color:var(--m);border-bottom:1px solid var(--b);}
.tbl td{padding:5px 7px;border-bottom:1px solid rgba(48,54,61,.4);
  font-family:monospace;font-size:12px;}
.tbl tr:last-child td{border:0;}
.chart-wrap{height:160px;}
</style>
</head>
<body>
<header>
  <h1>⚡ XAUUSD Pro Scalper</h1>
  <div style="display:flex;align-items:center;gap:14px;font-size:12px;">
    <span><span class="dot" id="sd" style="background:var(--r)"></span>
    <span id="st" style="color:var(--m)">Connecting…</span></span>
    <span id="ts" style="color:var(--m);font-size:11px"></span>
  </div>
</header>

<div class="grid g4">
  <div class="card"><div class="ctitle">Balance</div>
    <div class="kv" id="bal">—</div>
    <div class="sub" id="eq-sub">Equity: —</div></div>
  <div class="card"><div class="ctitle">Daily P&L</div>
    <div class="kv" id="dpnl">—</div>
    <div class="sub" id="dtrades">0 trades today</div></div>
  <div class="card"><div class="ctitle">Quality Score</div>
    <div class="kv" id="qs">—</div>
    <div class="sub" id="qdir">—</div></div>
  <div class="card"><div class="ctitle">System</div>
    <div class="row"><span class="lbl">MT5</span>
      <span class="val" id="mt5s">—</span></div>
    <div class="row"><span class="lbl">DOM</span>
      <span class="val" id="doms">—</span></div>
    <div class="row"><span class="lbl">Feed</span>
      <span class="val" id="feeds">—</span></div>
    <div class="row"><span class="lbl">Circuit</span>
      <span class="val" id="circs">—</span></div></div>
</div>

<div class="grid g3">
  <div class="card"><div class="ctitle">Open Position</div>
    <div id="pos-info"><div class="kv" style="color:var(--m);font-size:15px">Flat</div></div></div>
  <div class="card"><div class="ctitle">Drawdown</div>
    <div class="row"><span class="lbl">Daily</span>
      <span class="val" id="ddd">0.00%</span></div>
    <div class="pb"><div class="pf" id="ddb" style="width:0%"></div></div>
    <div class="row" style="margin-top:6px"><span class="lbl">Weekly</span>
      <span class="val" id="wdd">0.00%</span></div>
    <div class="pb"><div class="pf" id="wdb" style="width:0%"></div></div>
    <div class="row" style="margin-top:6px"><span class="lbl">Account</span>
      <span class="val" id="add">0.00%</span></div>
    <div class="pb"><div class="pf" id="adb" style="width:0%"></div></div></div>
  <div class="card"><div class="ctitle">Market State</div>
    <div id="mkt-state"></div></div>
</div>

<div class="grid g3">
  <div class="card"><div class="ctitle">Order Flow</div>
    <div id="of-state"></div></div>
  <div class="card"><div class="ctitle">DOM / Liquidity</div>
    <div id="dom-state"></div></div>
  <div class="card"><div class="ctitle">Microstructure</div>
    <div id="micro-state"></div></div>
</div>

<div class="grid g2">
  <div class="card"><div class="ctitle">Equity Curve</div>
    <div class="chart-wrap" id="eq-chart"></div></div>
  <div class="card"><div class="ctitle">Daily Win Rate</div>
    <div class="chart-wrap" id="wr-chart"></div></div>
</div>

<div class="grid g2">
  <div class="card"><div class="ctitle">Session & News</div>
    <div id="sess-state"></div></div>
  <div class="card"><div class="ctitle">ML Layer</div>
    <div id="ml-state"></div></div>
</div>

<div class="grid g1">
  <div class="card"><div class="ctitle">Recent Trades</div>
    <table class="tbl"><thead><tr>
      <th>Time</th><th>Dir</th><th>Entry</th><th>Exit</th>
      <th>P&L</th><th>Quality</th><th>Reason</th><th>Lat</th>
    </tr></thead><tbody id="trades-body"></tbody></table></div>
</div>

<script>
const API='',H={};
const f=(n,d=2)=>n==null?'—':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const row=(l,v,cls='')=>`<div class="row"><span class="lbl">${l}</span><span class="val ${cls}">${v}</span></div>`;
const ddColor=(v,lim)=>v/lim<.5?'var(--g)':v/lim<.8?'var(--y)':'var(--r)';
const pBar=(id,bid,v,lim)=>{const p=Math.min(v/lim*100,100);
  document.getElementById(id).textContent=f(v)+'%';
  const b=document.getElementById(bid);b.style.width=p+'%';b.style.background=ddColor(v,lim);};
const cLayout=(title)=>({
  paper_bgcolor:'transparent',plot_bgcolor:'transparent',
  font:{color:'#8b949e',size:10},
  margin:{l:35,r:8,t:8,b:30},
  xaxis:{gridcolor:'#21262d',tickfont:{size:9}},
  yaxis:{gridcolor:'#21262d',tickfont:{size:9}},
  showlegend:false,
});

async function load(){
  try{
    const [ov,tr,ec,wc]=await Promise.all([
      fetch(`${API}/api/overview`,{headers:H}).then(r=>r.json()),
      fetch(`${API}/api/trades?limit=20`,{headers:H}).then(r=>r.json()),
      fetch(`${API}/api/charts/equity`,{headers:H}).then(r=>r.json()),
      fetch(`${API}/api/charts/winrate`,{headers:H}).then(r=>r.json()),
    ]);
    render(ov,tr,ec,wc);
  }catch(e){console.error(e);}
}

function render(ov,tr,ec,wc){
  const h=ov.health||{},acct=ov.account||{},risk=ov.risk||{};
  const trade=ov.trade||{},mkt=ov.market||{};
  const of=ov.of||{},dom=ov.dom||{},micro=ov.micro||{};
  const sess=ov.session||{},q=ov.quality||{},ml=ov.ml||{},vol=ov.vol||{};

  // Status
  const ok=h.healthy;
  document.getElementById('sd').style.background=ok?'var(--g)':'var(--r)';
  document.getElementById('st').textContent=ok?'Live':'Degraded';
  document.getElementById('ts').textContent='Updated '+new Date().toLocaleTimeString();

  // Account
  document.getElementById('bal').textContent='$'+f(acct.balance,0);
  document.getElementById('eq-sub').textContent='Equity: $'+f(acct.equity,0);
  const pnl=risk.daily_pnl||0;
  const pe=document.getElementById('dpnl');
  pe.textContent=(pnl>=0?'+':'')+'$'+f(pnl);
  pe.className='kv '+(pnl>=0?'g':'r');
  document.getElementById('dtrades').textContent=(risk.daily_trades||0)+' trades today';

  // Quality
  const ql=q.long||{},qs2=q.short||{};
  const best=((ql.total||0)>(qs2.total||0))?ql:qs2;
  document.getElementById('qs').textContent=f(best.total,0)||'—';
  document.getElementById('qdir').textContent=best.tradeable?
    ((ql.total>qs2.total?'▲ LONG':'▼ SHORT')+' READY'):'Below threshold';

  // System
  const se=(v,cls)=>`<span class="${cls}">${v}</span>`;
  document.getElementById('mt5s').innerHTML=h.mt5_connected?se('✓ Connected','g'):se('✗ Down','r');
  document.getElementById('doms').innerHTML=h.dom_active?se('✓ Active','g'):se('Fallback','y');
  document.getElementById('feeds').textContent=f(h.feed_age_ms,0)+'ms';
  document.getElementById('circs').innerHTML=risk.circuit_broken?se('TRIPPED','r'):se('OK','g');

  // DD bars
  pBar('ddd','ddb',risk.daily_dd_pct||0,3);
  pBar('wdd','wdb',risk.weekly_dd_pct||0,7);
  pBar('add','adb',risk.account_dd_pct||0,10);

  // Position
  const pe2=document.getElementById('pos-info');
  if(trade.active){
    const dc=trade.direction==='LONG'?'g':'r';
    pe2.innerHTML=`<div class="kv ${dc}" style="font-size:16px">${trade.direction==='LONG'?'▲':'▼'} ${trade.direction}</div>`+
      row('Entry','$'+f(trade.entry))+row('SL','$'+f(trade.sl),'r')+
      row('TP','$'+f(trade.tp))+
      row('P&L',(trade.pnl>=0?'+':'')+'$'+f(trade.pnl),trade.pnl>=0?'g':'r')+
      row('R',f(trade.r,2)+'R')+
      row('BE',trade.breakeven?'✓ Set':'—')+row('Trail',trade.trailing?'✓ Active':'—');
  } else {
    pe2.innerHTML='<div class="kv" style="color:var(--m);font-size:15px">Flat</div>';
  }

  // Market
  document.getElementById('mkt-state').innerHTML=
    row('Bid/Ask','$'+f(mkt.bid,2)+' / $'+f(mkt.ask,2))+
    row('Spread',f((mkt.spread||0)*100,0)+' pts')+
    row('ATR M5',f(mkt.atr_m5,2))+
    row('Vol Regime',mkt.vol_regime||'—')+
    row('Vol %ile',f(mkt.vol_pct,0)+'%')+
    row('VWAP',mkt.vwap?'$'+f(mkt.vwap,2):'—')+
    row('VWAP Slope',f(mkt.vwap_slope,5));

  // Order flow
  document.getElementById('of-state').innerHTML=
    row('Score',f(of.of_score,1)+'/100',of.of_score>=60?'g':of.of_score<=40?'r':'y')+
    row('Direction',of.direction||'—')+
    row('CVD',f(of.cvd,0))+
    row('Buy Pressure',f(of.buy_pressure,1)+'%')+
    row('Tick Imb.',f(of.tick_imb,1))+
    row('Velocity',f(of.tick_vel,5))+
    row('Vol Expand.',of.vol_expansion?'✓ YES':'No');

  // DOM
  document.getElementById('dom-state').innerHTML=
    row('Mode',dom.mode||'—',dom.mode==='DOM'?'g':'y')+
    row('Score',f(dom.liq_score,0)+'/100')+
    (dom.mode==='DOM'?
      row('Imbalance',f(dom.imbalance,3))+
      row('Buy Wall',dom.buy_wall?'✓ YES':'No')+
      row('Sell Wall',dom.sell_wall?'✓ YES':'No')+
      row('Bid Vacuum',dom.bid_vacuum?'⚠ YES':'No')+
      row('Stacked Bids',dom.stacked_bids?'✓ YES':'No')
    :
      row('Tick Freq.',f(dom.tick_freq,2)+'/s')+
      row('Synth Delta',f(dom.synth_delta,1))+
      row('Agg Buy Est',f((dom.agg_buy_est||0)*100,1)+'%')+
      row('Vol Burst',dom.vol_burst?'✓ YES':'No')
    );

  // Microstructure
  const ms_items=[
    ['Trend',micro.trend||'—'],['Structure',micro.structure_bias||'—'],
    ['BOS Bull',micro.bos_bull?'✓ YES':'—'],['BOS Bear',micro.bos_bear?'✓ YES':'—'],
    ['CHoCH Bull',micro.choch_bull?'✓ YES':'—'],['Liq Grab↓',micro.liq_grab_down?'✓ YES':'—'],
    ['Liq Grab↑',micro.liq_grab_up?'✓ YES':'—'],['FVG Bull',micro.bull_fvg?'✓ IN':'—'],
    ['Reversal P.',f(micro.reversal_prob,2)],['Contin. P.',f(micro.continuation_prob,2)],
  ];
  document.getElementById('micro-state').innerHTML=ms_items.map(([l,v])=>row(l,v)).join('');

  // Session
  document.getElementById('sess-state').innerHTML=
    row('London',sess.is_london?'✓ Active':'—',sess.is_london?'g':'')+
    row('Overlap',sess.is_overlap?'✓ Active':'—',sess.is_overlap?'g':'')+
    row('Quality',f(sess.session_quality,0)+'/100')+
    row('News Blackout',sess.news_blackout?'⚠ YES':'Clear',sess.news_blackout?'y':'g')+
    row('Sentiment',sess.news_sentiment||'NEUTRAL')+
    (sess.next_event?row('Next Event',(sess.next_event||'').slice(0,30)):'')+
    (sess.min_to_event!=null?row('In',f(sess.min_to_event,0)+'m'):'');

  // ML
  document.getElementById('ml-state').innerHTML=
    row('Enabled',ml.enabled?'Yes':'No')+
    row('Trained',ml.trained?'✓ Yes':'Warming up',ml.trained?'g':'y')+
    row('History',ml.n_history||0)+
    row('Win Rate',f(ml.win_rate,1)+'%')+
    row('Min Samples',ml.min_samples||50);

  // Trades table
  const tbody=document.getElementById('trades-body');
  if(!tr||!tr.length){
    tbody.innerHTML='<tr><td colspan="8" style="color:var(--m);text-align:center">No trades</td></tr>';
  } else {
    tbody.innerHTML=tr.slice(0,15).map(t=>{
      const pnl=t.realized_pnl||0;
      const pc=pnl>=0?'g':'r';
      const dc=t.direction==='LONG'?'g':'r';
      return `<tr>
        <td>${(t.entry_time||'').slice(11,16)}</td>
        <td class="${dc}">${t.direction==='LONG'?'▲':'▼'} ${t.direction}</td>
        <td>$${f(t.entry_price,2)}</td>
        <td>${t.close_price?'$'+f(t.close_price,2):'—'}</td>
        <td class="${pc}">${pnl>=0?'+':''}$${f(pnl,2)}</td>
        <td>${f(t.quality_score,0)}</td>
        <td style="color:var(--m)">${(t.close_reason||'OPEN').slice(0,10)}</td>
        <td>${f(t.latency_ms,0)}ms</td>
      </tr>`;
    }).join('');
  }

  // Charts
  if(ec&&ec.dates&&ec.dates.length){
    const clr=ec.values[ec.values.length-1]>=0?'#2ea043':'#da3633';
    Plotly.react('eq-chart',[{x:ec.dates,y:ec.values,type:'scatter',
      fill:'tozeroy',line:{color:clr,width:1.5},
      fillcolor:clr.replace(')',',.15)').replace('#2ea043','rgba(46,160,67').replace('#da3633','rgba(218,54,51'),
    }],cLayout(),[{responsive:true}]);
  }
  if(wc&&wc.dates&&wc.dates.length){
    const cols=wc.values.map(v=>v>=50?'#2ea043':'#da3633');
    Plotly.react('wr-chart',[{x:wc.dates,y:wc.values,type:'bar',
      marker:{color:cols},}],
      {...cLayout(),yaxis:{...cLayout().yaxis,range:[0,100]}});
  }
}

load();setInterval(load,5000);
</script>
</body></html>"""
