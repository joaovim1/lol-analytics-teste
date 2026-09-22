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
  const [status, setStatus] = useState<any>({ status: "starting" }),
    [leagues, setLeagues] = useState<string[]>([]),
    [league, setLeague] = useState(""),
    [teams, setTeams] = useState<any[]>([]),
    [a, setA] = useState(""),
    [b, setB] = useState(""),
    [sample, setSample] = useState(3),
    [result, setResult] = useState<any>(),
    [tab, setTab] = useState("simulator"),
    [matches, setMatches] = useState<any[]>([]),
    [today, setToday] = useState<any>({ matches: [] }),
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
        setLeague((old: string) => old || ls[0] || "");
      }
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => {
    boot();
    const id = setInterval(boot, 3000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (!league) return;
    get("/teams?league=" + encodeURIComponent(league)).then((x: any[]) => {
      setTeams(x);
      setA(x[0]?.teamname || "");
      setB(x[1]?.teamname || "");
    });
    get("/matches?limit=100&league=" + encodeURIComponent(league)).then(
      setMatches,
    );
  }, [league]);
  useEffect(() => {
    if (status.status !== "ready") return;
    get("/schedule/today")
      .then(setToday)
      .catch((e) => setError(e.message));
  }, [status.status]);
  async function simulate() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(API + "/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_a: a,
          team_b: b,
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
    try {
      const r = await fetch(API + "/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_a: m.mapped_team1,
          team_b: m.mapped_team2,
          sample,
          simulations: 5000,
        }),
      });
      if (!r.ok) throw Error(await r.text());
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
  return (
    <main>
      <header>
        <div>
          <span className="eyebrow">
            COMPETITIVE ANALYTICS • ORACLE'S ELIXIR
          </span>
          <h1>Etonip LoL Lab</h1>
          <p>
            Partidas, jogadores e projeções baseadas no CSV competitivo atual.
          </p>
        </div>
        <div className={"status " + status.status}>
          <i></i>
          {status.status === "ready"
            ? status.games + " jogos • " + status.rows + " linhas"
            : "Importando dados…"}
        </div>
      </header>
      <nav>
        {[
          ["simulator", "Simulador"],
          ["today", "Confrontos de hoje"],
          ["matches", "Partidas da liga"],
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
          <select value={league} onChange={(e) => setLeague(e.target.value)}>
            {leagues.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
        <span>O CSV é baixado e importado automaticamente ao iniciar.</span>
      </section>
      {error && <div className="error">{error}</div>}
      {status.status !== "ready" ? (
        <section className="empty">
          <div className="spinner" />
          <h2>Preparando o dataset de {status.year}</h2>
          <p>Na primeira execução pode levar alguns minutos.</p>
        </section>
      ) : tab === "simulator" ? (
        <>
          <section className="selector">
            <label>
              Time A
              <select value={a} onChange={(e) => setA(e.target.value)}>
                {teams.map((t) => (
                  <option>{t.teamname}</option>
                ))}
              </select>
            </label>
            <b>VS</b>
            <label>
              Time B
              <select value={b} onChange={(e) => setB(e.target.value)}>
                {teams.map((t) => (
                  <option>{t.teamname}</option>
                ))}
              </select>
            </label>
            <label>
              Amostra
              <select
                value={sample}
                onChange={(e) => setSample(+e.target.value)}
              >
                {[3, 5, 10, 20].map((n) => (
                  <option value={n}>Últimos {n}</option>
                ))}
              </select>
            </label>
            <button
              className="primary"
              onClick={simulate}
              disabled={loading || !a || !b || a === b}
            >
              {loading ? "Calculando…" : "Simular confronto"}
            </button>
          </section>
          {result && (
            <>
              <section className="hero">
                <div>
                  <small>{league}</small>
                  <h2>{result.a.team}</h2>
                  <strong>{result.a.kills}</strong>
                  <span>kills projetadas</span>
                </div>
                <div className="center">
                  <span>FORMA RECENTE</span>
                  <b>×</b>
                  <small>5.000 cenários</small>
                </div>
                <div className="right">
                  <small>{league}</small>
                  <h2>{result.b.team}</h2>
                  <strong>{result.b.kills}</strong>
                  <span>kills projetadas</span>
                </div>
              </section>
              <section className="grid">
                {metrics.map(([label, key]) => (
                  <article>
                    <span>{label}</span>
                    <div>
                      <b>{val(result.a[key])}</b>
                      <i />
                      <b>{val(result.b[key])}</b>
                    </div>
                  </article>
                ))}
              </section>
              <section className="styles">
                <StyleCard
                  team={result.a.team}
                  data={result.team_styles[result.a.team]}
                />
                <StyleCard
                  team={result.b.team}
                  data={result.team_styles[result.b.team]}
                />
              </section>
              <section className="chart">
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
              </section>
              <section className="tablebox">
                <h3>Todos os jogadores da amostra</h3>
                <Table rows={result.players} columns={playerCols} />
              </section>
              <p className="note">{result.note}</p>
            </>
          )}
        </>
      ) : tab === "today" ? (
        <section className="matches">
          <h2>Confrontos de hoje • todas as ligas</h2>
          <p className="note">
            Horários de Brasília. Jogos concluídos vêm do CSV; confrontos
            futuros vêm da agenda pública.
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
                  {m.status === "completed" ? "Registrado no CSV" : "Agendado"}
                </span>
              </div>
              <button
                className="primary"
                disabled={!m.matchable || loading}
                onClick={() => simulateToday(m)}
                title={!m.matchable ? "Times ainda não associados ao histórico do CSV" : ""}
              >
                {m.matchable ? "Simular com estilos" : "Sem histórico suficiente"}
              </button>
            </article>
          ))}
        </section>
      ) : tab === "matches" ? (
        <section className="matches">
          <h2>Partidas recentes • {league}</h2>
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
