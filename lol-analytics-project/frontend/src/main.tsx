import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactECharts from "echarts-for-react";
import "./style.css";
import "./styles-extra.css";
const API = "http://localhost:8000";
const get = async (p: string) => {
  const r = await fetch(API + p);
  if (!r.ok) throw Error(await r.text());
  return r.json();
};
const val = (x: any) =>
  x == null ? "—" : typeof x === "object" ? JSON.stringify(x) : x;
function App() {
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [status, setStatus] = useState<any>({ status: "starting" }),
    [leagues, setLeagues] = useState<string[]>([]),
    [league, setLeague] = useState(""),
    [teams, setTeams] = useState<any[]>([]),
    [a, setA] = useState(""),
    [b, setB] = useState(""),
    [sample, setSample] = useState(3),
    [mode, setMode] = useState("match"),
    [bestOf, setBestOf] = useState(""),
    [result, setResult] = useState<any>(),
    [tab, setTab] = useState("simulator"),
    [matches, setMatches] = useState<any[]>([]),
    [today, setToday] = useState<any>({ matches: [] }),
    [championData, setChampionData] = useState<any>(null),
    [championSplit, setChampionSplit] = useState(""),
    [championError, setChampionError] = useState(""),
    [match, setMatch] = useState<any>(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  async function boot() {
    try {
      const s = await get("/health");
      setStatus(s);
      if (s.status === "ready") {
        const ls = await get("/leagues");
        setLeagues(ls);
        setLeague((old: string) => old === "__all__" || ls.includes(old) ? old : ls[0] || "");
      }
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function importCSV(file?: File) {
    if (!file) return;
    if (file.size > 250 * 1024 * 1024) {
      setImportMessage("O limite por arquivo é 250 MB."); return;
    }
    setImporting(true);
    setImportMessage("Enviando e validando o arquivo…");
    try {
      const response = await fetch(API + "/data/import?filename=" + encodeURIComponent(file.name), {
        method: "POST", headers: { "Content-Type": "text/csv" }, body: file,
      });
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "Não foi possível importar o arquivo.");
      setResult(undefined); setMatch(undefined); setChampionData(null); setChampionSplit("");
      setError("");
      await boot();
      setImportMessage(`Dados atualizados: ${data.games} jogos e ${data.rows} linhas.`);
    } catch (e: any) {
      setImportMessage(e.message || "Falha ao importar o arquivo.");
    } finally { setImporting(false); }
  }
  useEffect(() => {
    boot();
    const id = setInterval(boot, 3000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (!league) return;
    let cancelled = false;
    const filter = league === "__all__" ? "" : "?league=" + encodeURIComponent(league);
    get("/teams" + filter).then((x: any[]) => {
      if (cancelled) return;
      setTeams(x);
      setA((old) => x.some(t => t.teamname === old) ? old : x[0]?.teamname || "");
      setB((old) => x.some(t => t.teamname === old) ? old : x[1]?.teamname || "");
    }).catch((e) => { if (!cancelled) setError(e.message); });
    get("/matches?limit=100" + (league === "__all__" ? "" : "&league=" + encodeURIComponent(league)))
      .then((x) => { if (!cancelled) setMatches(x); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [league, status.dataset_version]);
  useEffect(() => {
    if (status.status !== "ready") return;
    let cancelled = false;
    get("/schedule/today")
      .then(x => { if (!cancelled) setToday(x); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [status.status, status.dataset_version]);
  async function simulate() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(API + "/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_a: a,
          team_b: mode === "single" ? null : b,
          best_of: bestOf ? Number(bestOf) : null,
          sample,
          simulations: 5000,
        }),
      });
      if (!r.ok) throw Error(await r.text());
      setResult(await r.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    if (tab !== "champions" || status.status !== "ready" || !league) return;
    let cancelled = false;
    setChampionData(null);
    setChampionError("");
    const query = new URLSearchParams();
    if (league !== "__all__") query.set("league", league);
    if (championSplit) query.set("split", championSplit);
    get("/champions?" + query.toString())
      .then((data) => { if (!cancelled) setChampionData(data); })
      .catch(() => { if (!cancelled) setChampionError("Não foi possível carregar as estatísticas de campeões."); });
    return () => { cancelled = true; };
  }, [tab, league, championSplit, status.status, status.dataset_version]);
  async function detail(id: string) {
    setLoading(true);
    try {
      setMatch(await get("/matches/" + encodeURIComponent(id)));
      setTab("data");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  async function simulateToday(m: any) {
    if (!m.matchable) return;
    setLoading(true);
    setError("");
    const seriesFormat = [1, 3, 5].includes(Number(m.bestof)) ? Number(m.bestof) : null;
    try {
      const r = await fetch(API + "/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_a: m.mapped_team1,
          team_b: m.mapped_team2,
          best_of: seriesFormat,
          sample,
          simulations: 5000,
        }),
      });
      if (!r.ok) throw Error(await r.text());
      setLeague("__all__");
      setMode("match");
      setBestOf(seriesFormat ? String(seriesFormat) : "");
      setA(m.mapped_team1);
      setB(m.mapped_team2);
      setResult(await r.json());
      setTab("simulator");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  const metrics = result
    ? [
        ["Kills", "kills"],
        ["Deaths", "deaths"],
        ["Assists", "assists"],
        ["Dragões", "dragons"],
        ["Barões", "barons"],
        ["Torres", "towers"],
        ["Gold", "gold"],
        ["Duração (s)", "duration"],
      ]
    : [];
  const playerCols = useMemo(
    () => (result?.players?.length ? Object.keys(result.players[0]) : []),
    [result],
  );
  const teamOptions = Array.from(new Set([
    ...teams.map((t) => t.teamname),
    a,
    b,
  ].filter(Boolean))).sort();
  return (
    <main>
      <header>
        <div>
          <span className="eyebrow">
            COMPETITIVE ANALYTICS • ORACLE'S ELIXIR
          </span>
          <h1>LoL Match Lab</h1>
          <p>
            Compare equipes, jogadores e o desempenho recente.
          </p>
        </div>
        <div className={"status " + status.status}>
          <i></i>
          {status.status === "ready"
            ? status.games + " jogos disponíveis"
            : status.status === "error"
              ? "Erro na importação"
              : "Importando dados • " + (status.progress || 0) + "%"}
        </div>
      </header>
      <section className="csv-import">
        <label htmlFor="csv-upload">Importar novo CSV</label>
        <input id="csv-upload" type="file" accept=".csv,text/csv"
          disabled={importing || loading}
          onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; importCSV(file); }} />
        <p>Selecione a base completa atualizada. Ela substituirá os dados atuais após a validação. Limite: 250 MB.</p>
        {importMessage && <p role="status">{importMessage}</p>}
      </section>
      <nav>
        {[
          ["simulator", "Simulador"],
          ["today", "Confrontos de hoje"],
          ["matches", "Partidas da liga"],
          ["champions", "Campeões"],
          ["data", "Todos os dados"],
        ].map((x) => (
          <button
            className={tab === x[0] ? "active" : ""}
            onClick={() => setTab(x[0])}
          >
            {x[1]}
          </button>
        ))}
      </nav>
      <section className="league">
        <label>
          Liga competitiva
          <select value={league} onChange={(e) => { setChampionSplit(""); setLeague(e.target.value); }}>
            <option value="__all__">Todas as ligas</option>
            {leagues.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
      </section>
      {error && <div className="error">{error}</div>}
      {status.status !== "ready" ? (
        <section className="empty">
          <div className="spinner" />
          <h2>Carregando partidas de {status.year}</h2>
          <div className="import-progress">
            <i style={{ width: (status.progress || 0) + "%" }} />
          </div>
          <p>
            {status.status === "downloading"
              ? "Baixando arquivo: " +
                Math.round((status.downloaded_bytes || 0) / 1024 / 1024) +
                " MB"
              : status.status === "parsing"
                ? "Lendo as partidas e os jogadores…"
                : status.status === "optimizing"
                  ? "Preparando as estatísticas…"
                  : status.status === "error"
                    ? status.message
                    : "Carregando partidas…"}
          </p>
        </section>
      ) : tab === "simulator" ? (
        <>
          <section className="selector">
            <label>Modo
              <select value={mode} onChange={(e) => { setMode(e.target.value); setResult(null); }}>
                <option value="match">Confronto</option>
                <option value="single">Um time</option>
              </select>
            </label>
            <label>
              Time A
              <select value={a} onChange={(e) => setA(e.target.value)}>
                {teamOptions.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
            {mode === "match" && <><b>VS</b>
            <label>
              Time B
              <select value={b} onChange={(e) => setB(e.target.value)}>
                {teamOptions.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
            </>}
            <label>
              Amostra (mapas)
              <select
                value={sample}
                onChange={(e) => setSample(+e.target.value)}
              >
                {[1, 2, 3, 5, 10, 20].map((n) => (
                  <option key={n} value={n}>{n === 1 ? "Último jogo" : "Últimos " + n}</option>
                ))}
              </select>
            </label>
            <label>Formato da série
              <select value={bestOf} onChange={(e) => setBestOf(e.target.value)}>
                <option value="">Não informado</option>
                {[1,3,5].map((n) => <option key={n} value={n}>MD{n}</option>)}
              </select>
            </label>
            <button
              className="primary"
              onClick={simulate}
              disabled={loading || !a || (mode === "match" && (!b || a === b))}
            >
              {loading ? "Calculando…" : mode === "single" ? "Analisar time" : "Simular confronto"}
            </button>
          </section>
          {result && (
            <>
              <p className="note">
                {result.series?.best_of ? "MD" + result.series.best_of + " • " + result.series.wins_needed + " vitória(s) para vencer." : "Formato da série não informado."}
                {" "}Estatísticas por mapa. Amostra: {result.a.sample} jogo(s) de {result.a.team}
                {result.b ? " e " + result.b.sample + " de " + result.b.team : ""}.
              </p>
              <section className="hero">
                <div>
                  <small>{league === "__all__" ? "Confronto" : league}</small>
                  <h2>{result.a.team}</h2>
                  <strong>{result.a.kills}</strong>
                  <span>{result.b ? "kills projetadas" : "média de kills"}</span>
                </div>
                {result.b && <><div className="center">
                  <span>FORMA RECENTE</span>
                  <b>×</b>
                  <small>5.000 cenários</small>
                </div>
                <div className="right">
                  <small>{league === "__all__" ? "Confronto" : league}</small>
                  <h2>{result.b.team}</h2>
                  <strong>{result.b.kills}</strong>
                  <span>kills projetadas</span>
                </div>
                </>}
              </section>
              <section className="grid">
                {metrics.map(([label, key]) => (
                  <article>
                    <span>{label}</span>
                    <div>
                      <b>{val(result.a[key])}</b>
                      {result.b && <><i /><b>{val(result.b[key])}</b></>}
                    </div>
                  </article>
                ))}
              </section>
              <section className="styles">
                <StyleCard
                  team={result.a.team}
                  data={result.team_styles[result.a.team]}
                />
                {result.b && <StyleCard
                  team={result.b.team}
                  data={result.team_styles[result.b.team]}
                />}
              </section>
              {result.b && <section className="chart">
                <h3>Faixa projetada de kills</h3>
                <ReactECharts
                  option={{
                    textStyle: { color: "#ccd3df" },
                    tooltip: {},
                    legend: { textStyle: { color: "#ccd3df" } },
                    xAxis: {
                      type: "category",
                      data: ["P25", "Média", "P75"],
                      axisLabel: { color: "#8791a3" },
                    },
                    yAxis: {
                      type: "value",
                      axisLabel: { color: "#8791a3" },
                      splitLine: { lineStyle: { color: "#252b36" } },
                    },
                    series: [
                      {
                        name: result.a.team,
                        type: "bar",
                        data: [
                          result.a.kills_p25,
                          result.a.kills,
                          result.a.kills_p75,
                        ],
                      },
                      {
                        name: result.b.team,
                        type: "bar",
                        data: [
                          result.b.kills_p25,
                          result.b.kills,
                          result.b.kills_p75,
                        ],
                      },
                    ],
                  }}
                />
              </section>}
              <RateCharts history={result.history || {}} />
              <section className="tablebox">
                <h3>Todos os jogadores da amostra</h3>
                <Table rows={result.players} columns={playerCols} />
              </section>
              <p className="note">{result.note}</p>
            </>
          )}
        </>
      ) : tab === "champions" ? (
        <section className="tablebox">
          <h2>Campeões mais escolhidos • {league === "__all__" ? "Todas as ligas" : league}</h2>
          <label>
            Etapa
            <select value={championSplit} onChange={(e) => setChampionSplit(e.target.value)}>
              <option value="">Todas as etapas</option>
              {Array.from(new Set([...(championData?.splits || []), championSplit].filter(Boolean))).map((s: any) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          {championError ? <p className="error">{championError}</p> : !championData ? <p>Carregando campeões…</p> : <>
            <p>{championData.games} jogos analisados. Ordenado por número de picks.</p>
            <p className="note">Taxa de vitória calculada sobre picks com resultado conhecido. Taxa de escolha: porcentagem de jogos em que o campeão apareceu.</p>
            {!championData.champions.length ? <p>Nenhum campeão encontrado neste filtro.</p> : <Table
              columns={["Campeão", "Picks", "Vitórias", "Derrotas", "Sem resultado", "Win rate", "Taxa de escolha"]}
              rows={championData.champions.map((c: any) => ({
                "Campeão": c.champion, "Picks": c.picks, "Vitórias": c.wins,
                "Derrotas": c.losses, "Sem resultado": c.unknown_results,
                "Win rate": c.win_rate == null ? "—" : c.win_rate.toLocaleString("pt-BR") + "%",
                "Taxa de escolha": c.pick_rate == null ? "—" : c.pick_rate.toLocaleString("pt-BR") + "%",
              }))}
            />}
          </>}
        </section>
      ) : tab === "today" ? (
        <section className="matches">
          <h2>Confrontos de hoje • todas as ligas</h2>
          <p className="note">
            Horários de Brasília.
          </p>
          {today.schedule_warning && (
            <div className="error">{today.schedule_warning}</div>
          )}
          {!today.matches?.length && (
            <div className="empty compact">
              Nenhum confronto encontrado para hoje.
            </div>
          )}
          {today.matches?.map((m: any, index: number) => (
            <article className="todaymatch" key={(m.gameid || m.datetime) + index}>
              <div>
                <small>
                  {m.datetime
                    ? new Date(m.datetime.replace(" ", "T") + (/Z|[+-]\d\d:\d\d$/.test(m.datetime) ? "" : "Z")).toLocaleString("pt-BR", {
                        timeZone: "America/Sao_Paulo",
                      })
                    : "Horário não informado"}{" "}
                  • {m.league || m.tournament || "Liga"}
                </small>
                <strong>{m.team1} × {m.team2}</strong>
                <span>
                  {m.status === "completed" ? "Finalizado" : "Agendado"}
                </span>
              </div>
              <button
                className="primary"
                disabled={!m.matchable || loading}
                onClick={() => simulateToday(m)}
                title={!m.matchable ? "Histórico indisponível para este confronto" : ""}
              >
                {m.matchable ? "Simular com estilos" : "Sem histórico suficiente"}
              </button>
            </article>
          ))}
        </section>
      ) : tab === "matches" ? (
        <section className="matches">
          <h2>Partidas recentes • {league === "__all__" ? "Todas as ligas" : league}</h2>
          {matches.map((m) => (
            <button className="match" onClick={() => detail(m.gameid)}>
              <div>
                <small>
                  {new Date(m.date).toLocaleString("pt-BR")} • Patch{" "}
                  {val(m.patch)}
                </small>
                <strong>
                  {m.teams.map((t: any) => t.teamname).join(" × ")}
                </strong>
              </div>
              <span>Ver jogadores e todos os campos →</span>
            </button>
          ))}
        </section>
      ) : (
        <section className="tablebox">
          <h2>Dados completos da partida</h2>
          {!match ? (
            <p>Abra uma partida na aba “Partidas da liga”.</p>
          ) : (
            <>
              <div className="matchtitle">
                {match.teams.map((t: any) => t.teamname).join(" × ")}
                <small>
                  {match.columns.length} colunas originais •{" "}
                  {match.players.length} jogadores
                </small>
              </div>
              <h3>Jogadores</h3>
              <Table rows={match.players} columns={match.columns} />
              <h3>Times</h3>
              <Table rows={match.teams} columns={match.columns} />
            </>
          )}
        </section>
      )}
    </main>
  );
}
function StyleCard({ team, data }: { team: string; data: any }) {
  const labels: any = {
    aggressiveness: "Agressividade",
    early_game: "Early game",
    objectives: "Objetivos",
    pace: "Ritmo",
    vision: "Visão",
  };
  return (
    <article>
      <h3>Estilo recente • {team}</h3>
      {Object.entries(data || {}).map(([k, v]: any) => (
        <div className="stylebar">
          <span>{labels[k] || k}</span>
          <i>
            <b style={{ width: (v ?? 0) + "%" }} />
          </i>
          <strong>{v ?? "N/D"}</strong>
        </div>
      ))}
    </article>
  );
}
function RateCharts({history}: {history: Record<string, any[]>}) {
  return <section>
    <p className="note">Médias por partida: total de ouro ou CS dividido pela duração em minutos. Valores da equipe inteira; não são curvas minuto a minuto. Dados ausentes aparecem como lacunas.</p>
    {Object.entries(history).map(([team, games]) => <div key={team} className="styles">
      {[["gold_per_minute", "Ouro/min"], ["cs_per_minute", "CS/min"]].map(([field, label]) => <section key={field} className="chart">
        <h3>{team} • {label}</h3>
        <ReactECharts option={{
          tooltip: {trigger:"axis"},
          xAxis: {type:"category",data:games.map((g, i) => "J" + (i+1) + " • " + new Date(g.date).toLocaleDateString("pt-BR")),axisLabel:{color:"#9da7b8"}},
          yAxis:{type:"value",axisLabel:{color:"#9da7b8"},splitLine:{lineStyle:{color:"#252b36"}}},
          series:[{name:label,type:"bar",data:games.map(g=>g[field]),itemStyle:{color:field==="gold_per_minute"?"#efc56a":"#63d9b1"}}]
        }} />
      </section>)}
    </div>)}
  </section>;
}
function Table({ rows, columns }: { rows: any[]; columns: string[] }) {
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td>{val(r[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
