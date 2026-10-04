import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import {
  ConversationProvider,
  useConversationControls,
  useConversationInput,
  useConversationMode,
  useConversationStatus,
} from "@elevenlabs/react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import "./styles.css";

const API = import.meta.env.VITE_CRUCIBLE_API || "http://localhost:8780";
const SYMBOLS = ["GOOGL", "NVDA", "AAPL", "MSFT", "META", "TSLA", "XAUUSD=X", "SPY", "QQQ"];
const TV_SYMBOLS = { GOOGL: "NASDAQ:GOOGL", NVDA: "NASDAQ:NVDA", AAPL: "NASDAQ:AAPL", MSFT: "NASDAQ:MSFT", META: "NASDAQ:META", TSLA: "NASDAQ:TSLA", "XAUUSD=X": "OANDA:XAUUSD", SPY: "AMEX:SPY", QQQ: "NASDAQ:QQQ" };
const SERIES_COLORS = ["#6ee7ff", "#9b8cff", "#4dd7aa", "#f6c86a", "#ff7a9b", "#76a7ff", "#c6f68d", "#f38c6b"];

function fmtMetric(m) {
  const v = m?.value;
  if (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v))) return "—";
  if (m.format === "percent") return `${(Number(v) * 100).toFixed(2)}%`;
  if (m.format === "price") return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (m.format === "dollar") return Number(v).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (m.format === "bps") return `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)} bps`;
  if (m.format === "sigma") return `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}σ`;
  if (m.format === "score100") return `${Number(v).toFixed(0)}/100`;
  if (m.format === "multiple") return `${Number(v).toFixed(2)}×`;
  if (typeof v === "number") return Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
  return String(v);
}

function MetricStrip({ metrics = [] }) {
  if (!metrics.length) return null;
  return <div className="metricStrip">
    {metrics.slice(0, 6).map((m, i) => <div className="metricCard" key={`${m.label}-${i}`}>
      <div className="metricLabel">{m.label}</div>
      <div className="metricValue">{fmtMetric(m)}</div>
    </div>)}
  </div>;
}

function ChartCard({ chart }) {
  const series = chart.series || [];
  const common = <>
    <CartesianGrid stroke="#1c2735" strokeDasharray="4 4" vertical={false} />
    <XAxis dataKey={chart.xKey} stroke="#6f7d90" tick={{ fontSize: 11 }} minTickGap={24} />
    <YAxis stroke="#6f7d90" tick={{ fontSize: 11 }} width={58} />
    <Tooltip contentStyle={{ background: "#0b121c", border: "1px solid #29384c", borderRadius: 10 }} />
    {series.length > 1 && <Legend />}
  </>;
  let body;
  if (chart.type === "bar") {
    body = <BarChart data={chart.data}>{common}{series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={SERIES_COLORS[i % SERIES_COLORS.length]} radius={[6, 6, 0, 0]} />)}</BarChart>;
  } else if (chart.type === "area") {
    body = <AreaChart data={chart.data}>{common}{series.map((s, i) => <Area key={s.key} dataKey={s.key} name={s.label} type="monotone" stroke={SERIES_COLORS[i % SERIES_COLORS.length]} fill={SERIES_COLORS[i % SERIES_COLORS.length]} fillOpacity={0.10 + i * 0.04} />)}</AreaChart>;
  } else {
    body = <LineChart data={chart.data}>{common}{series.map((s, i) => <Line key={s.key} dataKey={s.key} name={s.label} type="monotone" stroke={SERIES_COLORS[i % SERIES_COLORS.length]} dot={false} strokeWidth={2.2} connectNulls />)}</LineChart>;
  }
  return <section className="chartCard">
    <div className="panelTitle">{chart.title}</div>
    <div className="chartWrap"><ResponsiveContainer width="100%" height="100%">{body}</ResponsiveContainer></div>
  </section>;
}

function TableCard({ table }) {
  const rows = table.rows || [];
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]).slice(0, 8);
  return <section className="tableCard">
    <div className="panelTitle">{table.title}</div>
    <div className="tableScroller"><table><thead><tr>{cols.map(c => <th key={c}>{c.replaceAll("_", " ")}</th>)}</tr></thead>
      <tbody>{rows.slice(0, 20).map((r, i) => <tr key={i}>{cols.map(c => <td key={c}>{typeof r[c] === "number" ? Number(r[c]).toLocaleString(undefined,{maximumFractionDigits:3}) : String(r[c] ?? "")}</td>)}</tr>)}</tbody>
    </table></div>
  </section>;
}

function Evidence({ sources = [], toolTrace = [] }) {
  return <div className="evidenceGrid">
    <section className="evidenceCard">
      <div className="panelTitle">Investigation trace</div>
      <div className="traceList">{toolTrace.map((t, i) => <div className="trace" key={i}><span>✓</span>{t}</div>)}</div>
    </section>
    <section className="evidenceCard">
      <div className="panelTitle">Grounded evidence</div>
      {sources.length ? <div className="sourceList">{sources.slice(0, 10).map((src, i) => {
        const href = String(src.url || "").startsWith("/") ? `${API}${src.url}` : src.url;
        return <a key={i} href={href} target="_blank" rel="noreferrer"><span>{String(i+1).padStart(2,"0")}</span><div>{src.title}{src.published ? <small>{src.published}</small> : null}</div></a>;
      })}</div> : <div className="emptyTiny">No external web source was required. Numerical answers come from the recorded/project data shown above.</div>}
    </section>
  </div>;
}

function VoiceOrb({ status, isSpeaking, isListening }) {
  const active = status === "connected";
  const cls = ["orb", active ? "active" : "", isSpeaking ? "speaking" : "", isListening ? "listening" : ""].join(" ");
  return <div className="orbShell"><div className={cls}><div className="orbCore" /></div><div className="orbState">{status === "connecting" ? "CONNECTING" : isSpeaking ? "CRUCIBLE SPEAKING" : isListening ? "LISTENING" : active ? "LIVE" : "OFFLINE"}</div></div>;
}


function TradingViewStage({ symbol }) {
  const host = useRef(null);
  useEffect(() => {
    if (!host.current) return;
    host.current.innerHTML = "";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "100%";
    widget.style.width = "100%";
    host.current.appendChild(widget);
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.type = "text/javascript";
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: TV_SYMBOLS[symbol] || `NASDAQ:${symbol}`,
      interval: "60",
      timezone: "America/New_York",
      theme: "dark",
      style: "1",
      locale: "en",
      allow_symbol_change: true,
      calendar: false,
      details: true,
      hide_side_toolbar: false,
      hide_top_toolbar: false,
      hide_legend: false,
      hide_volume: false,
      save_image: true,
      withdateranges: true,
      support_host: "https://www.tradingview.com",
    });
    host.current.appendChild(script);
    return () => { if (host.current) host.current.innerHTML = ""; };
  }, [symbol]);
  return <section className="tvCard">
    <div className="stageTitleRow"><div><span>LIVE MARKET SURFACE</span><b>{TV_SYMBOLS[symbol] || symbol}</b></div><div className="liveDot">LIVE</div></div>
    <div ref={host} className="tradingview-widget-container tvHost" />
    <div className="tvFoot">TradingView is the visual surface · numerical analysis comes from the market-data layer.</div>
  </section>;
}

function MarketVisionPanel({ symbol, onResult }) {
  const [file, setFile] = useState(null);
  const [prompt, setPrompt] = useState("What is visually important here, and what should I test quantitatively next?");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const analyze = useCallback(async () => {
    if (!file || busy) return;
    setBusy(true); setError("");
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
      });
      const r = await fetch(`${API}/api/vision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_base64: String(dataUrl).split(",", 2)[1], mime_type: file.type || "image/png", question: prompt, symbol }),
      });
      if (!r.ok) throw new Error(await r.text());
      onResult(await r.json());
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }, [file, prompt, symbol, busy, onResult]);

  return <section className="visionCard">
    <div className="stageTitleRow"><div><span>GEMINI MARKET VISION</span><b>Interrogate a chart screenshot</b></div><div className="visionBadge">VISION</div></div>
    <div className="visionDrop">
      <input id="chart-upload" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setFile(e.target.files?.[0] || null)} />
      <label htmlFor="chart-upload">{file ? file.name : "Drop / choose a TradingView screenshot"}</label>
    </div>
    <textarea className="visionPrompt" value={prompt} onChange={e => setPrompt(e.target.value)} />
    <button className="primary visionButton" disabled={!file || busy} onClick={analyze}>{busy ? "Gemini is inspecting…" : "Analyze visual evidence"}</button>
    <div className="visionRule">Pixels provide visual context only. Exact prices, returns and volatility come from market data.</div>
    {error && <div className="errorBox">{error}</div>}
  </section>;
}

const REPOSITORY_PAGES = {
  systematic: { label: "Systematic Trading", subtitle: "Committed strategy research note", url: `${API}/api/systematic-trading-note` },
  massive_research: { label: "Massive · Research Desk", subtitle: "01 / Does the edge survive?", url: `${API}/filing-edge/index.html#research` },
  massive_evidence: { label: "Massive · Filing Evidence", subtitle: "02 / Read the filing. Follow the clock.", url: `${API}/filing-edge/index.html#evidence` },
  massive_capital: { label: "Massive · Capital & Downside", subtitle: "03 / Position sizing and downside stress", url: `${API}/filing-edge/index.html#capital` },
  massive_infra: { label: "Massive · Data Infrastructure", subtitle: "04 / Providers, provenance and Timescale", url: `${API}/filing-edge/index.html#connections` },
};

function RepositoryPage({ page }) {
  return <section className="repositoryPage">
    <div className="repositoryHead"><div><span>REPOSITORY-NATIVE WORKSPACE</span><h2>{page.label}</h2><p>{page.subtitle}</p></div><a href={page.url} target="_blank" rel="noreferrer">Open full page ↗</a></div>
    <iframe key={page.url} src={page.url} title={page.label} className="repositoryFrame" />
  </section>;
}

const MODE_DEFS = [
  { key: "live", icon: "🎙", label: "Live Desk", prompt: "Give me a concise evidence-linked overview of the selected company and current quant workspace." },
  { key: "crucible", icon: "🧪", label: "Crucible", prompt: "Red-team our strategy and show the weakest evidence, robustness attacks, and verdict." },
  { key: "vision", icon: "👁", label: "Market Vision", prompt: null },
  { key: "multiverse", icon: "⏳", label: "Multiverse", prompt: "Run Market Multiverse: double volatility and transaction costs, clearly label this as hypothetical, and show the stress results." },
  { key: "black_box", icon: "🔬", label: "Black Box", prompt: "Open the Black Box for the worst committed traded session and explain where the loss came from." },
  { key: "ghost", icon: "👻", label: "Ghost Desk", prompt: "Run Ghost Desk. Show what the VIX gate saved, what gains it missed, and the counterfactual equity paths." },
  { key: "explain_day", icon: "📅", label: "Explain Day", prompt: "Explain this day. What happened, why did the strategy trade or stay out, and what evidence is actually recorded?" },
  { key: "profit_bridge", icon: "💸", label: "Profit Bridge", prompt: "Where did our profit go? Break gross profit into costs and net profit, and show a separately labeled doubled-cost hypothetical." },
  { key: "replay", icon: "⏪", label: "Replay", prompt: "Start before the market opens for the selected historical replay day. Reveal only information available at that point." },
  { key: "research_trial", icon: "⚖", label: "Research Trial", prompt: "Put our research on trial. Challenge the headline claim and show the strongest relevant limitation and failed or fragile evidence." },
  { key: "systematic", icon: "📘", label: "Systematic Trading", prompt: null },
  { key: "massive_research", icon: "Ⓜ", label: "Massive Research", prompt: null },
  { key: "massive_evidence", icon: "📄", label: "Massive Evidence", prompt: null },
  { key: "massive_capital", icon: "🛡", label: "Massive Capital", prompt: null },
  { key: "massive_infra", icon: "🧱", label: "Massive Infra", prompt: null },
];

function modeForRoute(route) {
  const r = String(route || "");
  if (["crucible","multiverse","black_box","ghost","explain_day","profit_bridge","replay","research_trial"].includes(r)) return r;
  if (r === "vision") return "vision";
  return "live";
}

function ModeDock({ active, onMode }) {
  return <div className="modeDock">{MODE_DEFS.map(m => <button key={m.key} className={active === m.key ? "active" : ""} onClick={() => onMode(m)}><span>{m.icon}</span><b>{m.label}</b></button>)}</div>;
}

function Workspace() {
  const { startSession, endSession, sendUserMessage } = useConversationControls();
  const { status } = useConversationStatus();
  const { isMuted, setMuted } = useConversationInput();
  const { isSpeaking, isListening } = useConversationMode();
  const [symbol, setSymbol] = useState("GOOGL");
  const [activeMode, setActiveMode] = useState("live");
  const [lastRoute, setLastRoute] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [userName, setUserName] = useState("");
  const [showTranscript, setShowTranscript] = useState(true);
  const [view, setView] = useState(null);
  const [chat, setChat] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastTs, setLastTs] = useState("");
  const [health, setHealth] = useState(null);
  const conversationIdRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/latest-turn`, { cache: "no-store" });
        if (!r.ok) return;
        const d = await r.json();
        if (d.ready && d.ts && d.ts !== lastTs && d.view_model) {
          setLastTs(d.ts);
          setView(d.view_model);
          setActiveMode(modeForRoute(d.view_model.route));
          if (d.view_model.route && !["clarify", "scope_refusal"].includes(d.view_model.route)) setLastRoute(d.view_model.route);
          if (d.view_model.symbol) setSymbol(d.view_model.symbol);
          setChat(prev => {
            const q = d.question || d.view_model.question;
            const a = d.answer || d.view_model.answer;
            const out = prev.slice(-16);
            if (q && out.at(-1)?.content !== q && out.at(-2)?.content !== q) out.push({ role: "user", content: q });
            if (a && out.at(-1)?.content !== a) out.push({ role: "assistant", content: a });
            return out;
          });
        }
      } catch (_) {}
    }, 850);
    return () => clearInterval(id);
  }, [lastTs]);

  const pushVoiceContext = useCallback(async (override = {}) => {
    const cid = conversationIdRef.current;
    if (status !== "connected" || !cid) return;
    await fetch(`${API}/api/voice-context`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: cid, symbol, selected_date: selectedDate || null, module: activeMode, user_name: userName || null, ...override }),
    }).catch(() => {});
  }, [symbol, selectedDate, activeMode, userName, status]);

  useEffect(() => { pushVoiceContext(); }, [pushVoiceContext]);

  const startVoice = useCallback(async () => {
    setError("");
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const r = await fetch(`${API}/api/token`);
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      const cid = await startSession({
        conversationToken: d.token,
        overrides: { agent: { firstMessage: "Hi, I'm Crucible, your quant research copilot. What should I call you?" } },
      });
      conversationIdRef.current = cid;
      if (cid) {
        await fetch(`${API}/api/voice-context`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: cid, symbol, selected_date: selectedDate || null, module: activeMode, user_name: userName || null }),
        });
      }
    } catch (e) { setError(String(e?.message || e)); }
  }, [startSession, symbol, selectedDate, activeMode, userName]);

  const runQuestion = useCallback(async (rawQuestion, modeOverride = null) => {
    const q = String(rawQuestion || "").trim();
    if (!q || busy) return;
    const module = modeOverride || activeMode;
    setBusy(true); setError(""); setQuestion("");
    setChat(prev => [...prev.slice(-16), { role: "user", content: q }]);
    try {
      if (status === "connected") {
        const cid = conversationIdRef.current;
        if (cid) {
          await fetch(`${API}/api/voice-context`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: cid, symbol, selected_date: selectedDate || null, module, user_name: userName || null }),
          });
        }
        sendUserMessage(q);
      } else {
        const r = await fetch(`${API}/api/chat`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q, symbol, selected_date: selectedDate || null, module, last_route: lastRoute || null, user_name: userName || null, history: chat.slice(-12) }),
        });
        if (!r.ok) throw new Error(await r.text());
        const vm = await r.json();
        setView(vm);
        setActiveMode(modeForRoute(vm.route));
        if (vm.route && !["clarify", "scope_refusal"].includes(vm.route)) setLastRoute(vm.route);
        if (vm.symbol) setSymbol(vm.symbol);
        setChat(prev => [...prev.slice(-16), { role: "assistant", content: vm.answer }]);
      }
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }, [busy, activeMode, lastRoute, status, symbol, selectedDate, userName, chat, sendUserMessage]);

  const askText = useCallback(() => runQuestion(question), [question, runQuestion]);

  const onMode = useCallback((m) => {
    setActiveMode(m.key);
    if (m.prompt) runQuestion(m.prompt, m.key);
  }, [runQuestion]);

  const acceptVision = useCallback((vm) => {
    setView(vm); setActiveMode("vision");
    if (vm?.symbol) setSymbol(vm.symbol);
    if (vm?.answer) setChat(prev => [...prev.slice(-16), { role: "assistant", content: vm.answer }]);
  }, []);

  const shortcuts = [
    "What's going on with Google today? Show evidence.",
    "Explain more simply.",
    "Show me the evidence behind that answer.",
    "Compare Google versus Nvidia over the last six months.",
  ];

  const marketVisible = ["live", "vision"].includes(activeMode) || ["company_research","market_snapshot","compare","analogs","vision"].includes(view?.route);
  const repositoryPage = REPOSITORY_PAGES[activeMode] || null;

  return <div className="app">
    <header className="topbar">
      <div><div className="brandKicker">AI-NATIVE SYSTEMATIC RESEARCH</div><div className="brand">QUANT <b>CRUCIBLE</b></div></div>
      <div className="topControls">
        <select value={symbol} onChange={e => setSymbol(e.target.value)}>{SYMBOLS.map(s => <option key={s}>{s}</option>)}</select>
        <input className="dateInput" type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} title="Selected research/replay date" />
        <div className={`statusPill ${health?.gemini ? "ok" : ""}`}>Gemini</div>
        <div className={`statusPill ${health?.elevenlabs ? "ok" : ""}`}>ElevenLabs</div>
        <div className="statusPill ok">Read-only</div>
      </div>
    </header>

    <ModeDock active={activeMode} onMode={onMode} />

    <main className="grid">
      <aside className="copilotPanel">
        <div className="voiceSection">
          <VoiceOrb status={status} isSpeaking={isSpeaking} isListening={isListening} />
          <div className="voiceButtons">
            {status !== "connected" ? <button className="primary" onClick={startVoice}>🎙 Start live voice</button> : <button className="danger" onClick={endSession}>End conversation</button>}
            <button className="ghostButton" disabled={status !== "connected"} onClick={() => setMuted(!isMuted)}>{isMuted ? "Unmute" : "Mute"}</button>
            <button className="ghostButton" onClick={() => setShowTranscript(!showTranscript)}>{showTranscript ? "Hide transcript" : "Show transcript"}</button>
            <button className="ghostButton" onClick={() => setChat([])}>Clear transcript</button>
          </div>
          <div className="voiceHint">Voice and text share one conversation and the same selected symbol/date/module. Interruptions are handled by ElevenLabs. Off-topic questions are declined; this copilot is scoped to quant trading, market/company research and project evidence.</div>
        </div>

        {showTranscript && <div className="chatLog">
          {chat.length === 0 && <div className="chatEmpty">Ask by text or voice. Try “Explain this day”, “Where did our profit go?”, “Put our research on trial”, or ask why a company moved and request evidence.</div>}
          {chat.slice(-14).map((m, i) => <div className={`bubble ${m.role}`} key={i}><span>{m.role === "user" ? "YOU" : "CRUCIBLE"}</span>{m.content}</div>)}
        </div>}

        <div className="composer">
          <textarea value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askText(); } }} placeholder={`Ask Gemini about ${symbol}, ${selectedDate || "a trading day"}, or ${activeMode.replaceAll("_", " ")}…`} />
          <button className="primary" onClick={askText} disabled={busy}>{busy ? "Investigating…" : "Ask Gemini"}</button>
        </div>
        <div className="quickList">{shortcuts.map((q, i) => <button key={i} onClick={() => runQuestion(q)}>{q}</button>)}</div>
        {error && <div className="errorBox">{error}</div>}
      </aside>

      <section className="workspace">
        <div className="workspaceHeader">
          <div><div className="route">{(repositoryPage?.label || view?.route || activeMode || "LIVE DESK").replaceAll("_", " ")}</div><h1>{repositoryPage ? repositoryPage.subtitle : (view?.symbol || symbol)}</h1></div>
          <div className="researchBoundary">Gemini understands/retrieves/explains · backend computes · ElevenLabs converses · no trading authority</div>
        </div>
        {repositoryPage ? <RepositoryPage page={repositoryPage} /> : <>
        {marketVisible && <div className="marketStage">
          <TradingViewStage symbol={symbol} />
          <MarketVisionPanel symbol={symbol} onResult={acceptVision} />
        </div>}
        {view ? <>
          <div className="answerCard"><div className="answerEyebrow">EVIDENCE-LINKED ANSWER</div><div>{view.answer}</div></div>
          {(view.actions || []).length > 0 && <div className="actionRail">{view.actions.map((a, i) => <button key={i} onClick={() => runQuestion(a.prompt, activeMode)}>{a.label}</button>)}</div>}
          <MetricStrip metrics={view.metrics} />
          <div className="chartsGrid">{(view.charts || []).map((c, i) => <ChartCard key={i} chart={c} />)}</div>
          <div className="tablesGrid">{(view.tables || []).map((t, i) => <TableCard key={i} table={t} />)}</div>
          <Evidence sources={view.sources} toolTrace={view.toolTrace} />
        </> : <div className="emptyWorkspace">
          <div className="emptyGlow" />
          <div className="emptyLabel">ONE CONVERSATION · MULTIPLE EVIDENCE MODES</div>
          <h2>Talk to the market.<br/>Interrogate the research.</h2>
          <p>Crucible, Market Vision, Multiverse, Black Box, Ghost Desk, Explain Day, Profit Bridge, Historical Replay and Research Trial all use the same Gemini + deterministic evidence engine and the same ElevenLabs voice session.</p>
        </div>}
        </>}
      </section>
    </main>
  </div>;
}

function Root() {
  return <ConversationProvider><Workspace /></ConversationProvider>;
}

ReactDOM.createRoot(document.getElementById("root")).render(<React.StrictMode><Root /></React.StrictMode>);
