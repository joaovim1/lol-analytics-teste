from __future__ import annotations
import math, os, random, re, threading, tempfile
from uuid import uuid4
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Literal
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

YEAR=int(os.getenv('OE_YEAR',datetime.now(timezone.utc).year)); DATA_DIR=Path(__file__).resolve().parents[1]/'data'; DATA_DIR.mkdir(exist_ok=True)
CSV_PATH=DATA_DIR/f'{YEAR}_LoL_esports_match_data_from_OraclesElixir.csv'
GZIP_PATH=DATA_DIR/f'{YEAR}_LoL_esports_match_data_from_OraclesElixir.gzip'
CACHE_PATH=DATA_DIR/f'{YEAR}_match_data.cache.pkl'
SOURCE_URL=os.getenv('OE_CSV_URL',f'https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com/{YEAR}_LoL_esports_match_data_from_OraclesElixir.gzip')
SCHEDULE_URL=os.getenv('SCHEDULE_API_URL','https://lol.fandom.com/api.php')
app=FastAPI(title='LoL Competitive Analytics',version='2.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://localhost:3000'],allow_methods=['*'],allow_headers=['*'])
df=pd.DataFrame(); state={'status':'starting','year':YEAR,'source':SOURCE_URL,'progress':0}
load_thread:threading.Thread|None=None
data_lock=threading.Lock()
MAX_CSV_BYTES=250*1024*1024

def clean(v:Any):
    if pd.isna(v): return None
    if hasattr(v,'item'): v=v.item()
    if isinstance(v,(pd.Timestamp,datetime)): return v.isoformat()
    return int(v) if isinstance(v,float) and v.is_integer() else v
def records(frame): return [{k:clean(v) for k,v in row.items()} for row in frame.to_dict('records')]
def team_rows(frame): return frame[frame.position.astype(str).str.lower()=='team']
def player_rows(frame): return frame[frame.position.astype(str).str.lower()!='team']

def set_state(**values):
    global state
    state={**state,**values}

def download_source():
    tmp=GZIP_PATH.with_suffix('.download')
    with requests.get(SOURCE_URL,stream=True,timeout=(15,300)) as response:
        response.raise_for_status()
        total=int(response.headers.get('content-length') or 0); downloaded=0
        with tmp.open('wb') as out:
            for chunk in response.iter_content(4*1024*1024):
                if not chunk: continue
                out.write(chunk);downloaded+=len(chunk)
                progress=round(downloaded/total*70) if total else 0
                set_state(status='downloading',progress=progress,downloaded_bytes=downloaded,total_bytes=total or None)
    os.replace(tmp,GZIP_PATH)

def load_csv(force=False):
    if not data_lock.acquire(blocking=False): return state
    try:
        return _load_csv(force)
    finally:
        data_lock.release()

def _load_csv(force=False):
    global df,state
    state={'status':'loading_cache','year':YEAR,'source':SOURCE_URL,'progress':2};warning=None
    try:
        if CACHE_PATH.exists() and not force:
            df=pd.read_pickle(CACHE_PATH)
            state={'status':'ready','year':YEAR,'source':SOURCE_URL,'progress':100,'rows':len(df),'games':int(df.gameid.nunique()),'columns':len(df.columns),'cached_file':str(CACHE_PATH),'cache':'binary'}
            return state
        if force or (not GZIP_PATH.exists() and not CSV_PATH.exists()):
            download_source()
        set_state(status='parsing',progress=75)
        if GZIP_PATH.exists():
            loaded=pd.read_csv(GZIP_PATH,compression='gzip',low_memory=False)
        else:
            loaded=pd.read_csv(CSV_PATH,low_memory=False)
        set_state(status='optimizing',progress=90)
        if 'date' in loaded: loaded['date']=pd.to_datetime(loaded.date,errors='coerce',utc=True)
        for col in ['league','teamname','teamid','playername','playerid','position','side','gameid']:
            if col in loaded: loaded[col]=loaded[col].astype('category')
        loaded.to_pickle(CACHE_PATH,protocol=5)
        df=loaded
        state={'status':'ready','year':YEAR,'source':SOURCE_URL,'progress':100,'rows':len(df),'games':int(df.gameid.nunique()),'columns':len(df.columns),'cached_file':str(CACHE_PATH),'cache':'binary','download_warning':warning}
    except Exception as exc:
        state={'status':'error','message':str(exc),'year':YEAR,'source':SOURCE_URL,'progress':0}
    return state

@app.on_event('startup')
def startup():
    global load_thread
    load_thread=threading.Thread(target=load_csv,daemon=True,name='dataset-loader');load_thread.start()
def require_data():
    if df.empty: raise HTTPException(503,f"Dataset indisponível: {state.get('message','importando')}")
@app.get('/health')
def health(): return state

def import_csv_file(path):
    global df, state
    cache_tmp=CACHE_PATH.with_suffix('.importing')
    try:
        loaded=pd.read_csv(path,encoding='utf-8-sig',low_memory=False)
        required={'gameid','date','league','teamname','position','side','playername','champion','result','gamelength'}
        missing=required-set(loaded.columns)
        if missing:
            raise ValueError('Colunas obrigatórias ausentes: '+', '.join(sorted(missing)))
        if loaded.empty:
            raise ValueError('O arquivo não contém partidas.')
        if loaded[['gameid','league','teamname','position']].isna().any().any():
            raise ValueError('Há linhas sem identificação da partida, liga, time ou posição.')
        loaded['date']=pd.to_datetime(loaded.date,errors='coerce',utc=True)
        if loaded.date.isna().any():
            raise ValueError('Há partidas com datas inválidas.')
        if team_rows(loaded).empty or player_rows(loaded).empty:
            raise ValueError('O arquivo deve conter linhas de times e jogadores.')
        for col in ['league','teamname','teamid','playername','playerid','position','side','gameid']:
            if col in loaded: loaded[col]=loaded[col].astype('category')
        loaded.to_pickle(cache_tmp,protocol=5)
        os.replace(cache_tmp,CACHE_PATH)
        df=loaded
        state={'status':'ready','year':YEAR,'source':'uploaded_csv','progress':100,
               'rows':len(df),'games':int(df.gameid.nunique()),'columns':len(df.columns),
               'dataset_version':uuid4().hex,'cache':'binary'}
        return state
    finally:
        cache_tmp.unlink(missing_ok=True)

@app.post('/data/import')
async def import_data(request:Request,filename:str=Query(...)):
    if not filename.lower().endswith('.csv'):
        raise HTTPException(422,'Selecione um arquivo .csv.')
    if not data_lock.acquire(blocking=False):
        raise HTTPException(409,'Aguarde a atualização em andamento e tente novamente.')
    path=None
    try:
        with tempfile.NamedTemporaryFile(dir=DATA_DIR,suffix='.csv',delete=False) as out:
            path=Path(out.name)
            size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>MAX_CSV_BYTES:
                    raise HTTPException(413,'O limite por arquivo é 250 MB.')
                out.write(chunk)
        try:
            return await run_in_threadpool(import_csv_file,path)
        except (ValueError,UnicodeError,pd.errors.ParserError) as exc:
            raise HTTPException(422,'CSV inválido: '+str(exc)) from exc
    finally:
        if path is not None: path.unlink(missing_ok=True)
        data_lock.release()

@app.post('/data/refresh')
def refresh():
    global load_thread
    if load_thread and load_thread.is_alive(): return {**state,'message':'Uma importação já está em andamento.'}
    load_thread=threading.Thread(target=load_csv,args=(True,),daemon=True,name='dataset-refresh');load_thread.start()
    return {'status':'refresh_started','year':YEAR,'progress':0}
@app.get('/leagues')
def leagues(): require_data(); return sorted(df.league.dropna().astype(str).unique().tolist())
@app.get('/teams')
def teams(league:str|None=None):
    require_data(); frame=team_rows(df)
    if league: frame=frame[frame.league==league]
    cols=[c for c in ['teamname','teamid','league'] if c in frame]
    return records(frame[cols].dropna(subset=['teamname']).drop_duplicates().sort_values('teamname'))

@app.get('/champions')
def champions(league: str | None = None, split: str | None = None):
    require_data()
    required={'gameid','league','position','champion','result'}
    if not required.issubset(df.columns):
        raise HTTPException(422,'Estatísticas de campeões indisponíveis nesta base.')
    frame=player_rows(df)
    if league:
        frame=frame[frame.league.astype(str)==league]
    splits=sorted(frame['split'].dropna().astype(str).unique().tolist()) if 'split' in frame else []
    if split:
        if 'split' not in frame:
            raise HTTPException(422,'Esta base não informa a etapa do campeonato.')
        frame=frame[frame['split'].astype(str)==split]
    # Deduplicate player observations, never team aggregate rows.
    identity=['gameid','participantid'] if 'participantid' in frame and frame['participantid'].notna().all() else [c for c in ['gameid','teamname','position'] if c in frame]
    frame=frame.drop_duplicates(subset=identity).copy()
    games=int(frame.gameid.nunique())
    frame=frame[frame.champion.notna() & frame.champion.astype(str).str.strip().ne('')].copy()
    frame['_result']=pd.to_numeric(frame.result,errors='coerce')
    output=[]
    for champion,rows in frame.groupby('champion',observed=True):
        picks=len(rows)
        wins=int(rows['_result'].eq(1).sum())
        losses=int(rows['_result'].eq(0).sum())
        decided=wins+losses
        output.append({'champion':str(champion),'picks':picks,'wins':wins,'losses':losses,
                       'unknown_results':picks-decided,
                       'win_rate':round(wins/decided*100,2) if decided else None,
                       'pick_rate':round(rows.gameid.nunique()/games*100,2) if games else None})
    output.sort(key=lambda row:(-row['picks'],row['champion']))
    return {'games':games,'splits':splits,'champions':output}
@app.get('/matches')
def matches(league:str|None=None,limit:int=Query(50,ge=1,le=500)):
    require_data(); frame=team_rows(df)
    if league: frame=frame[frame.league==league]
    frame=frame.sort_values('date' if 'date' in frame else 'gameid',ascending=False); out=[]
    for gameid,game in frame.groupby('gameid',sort=False,observed=True):
        if len(game)<2: continue
        cols=[c for c in ['teamname','teamid','side','result','kills','teamkills','gamelength'] if c in game]
        out.append({'gameid':clean(gameid),'league':clean(game.iloc[0].get('league')),'date':clean(game.iloc[0].get('date')),'patch':clean(game.iloc[0].get('patch')),'teams':records(game.sort_values('side')[cols])})
        if len(out)>=limit: break
    return out
@app.get('/matches/{gameid}')
def match_detail(gameid:str):
    require_data(); game=df[df.gameid.astype(str)==gameid]
    if game.empty: raise HTTPException(404,'Partida não encontrada')
    return {'gameid':gameid,'columns':list(df.columns),'teams':records(team_rows(game)),'players':records(player_rows(game)),'all_rows':records(game)}

def normalized(name:str): return re.sub(r'[^a-z0-9]','',str(name).lower())
def resolve_team(name:str):
    names=team_rows(df).teamname.dropna().astype(str).unique().tolist()
    target=normalized(name); exact=next((x for x in names if normalized(x)==target),None)
    if exact:return exact,1.0
    ranked=sorted(((SequenceMatcher(None,target,normalized(x)).ratio(),x) for x in names),reverse=True)
    return (ranked[0][1],round(ranked[0][0],2)) if ranked and ranked[0][0]>=.72 else (None,ranked[0][0] if ranked else 0)

@app.get('/schedule/today')
def schedule_today(date:str|None=None):
    require_data()
    tz=ZoneInfo('America/Sao_Paulo')
    day=datetime.strptime(date,'%Y-%m-%d').date() if date else datetime.now(tz).date()
    start=datetime.combine(day,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc)
    end=datetime.combine(day,datetime.max.time(),tzinfo=tz).astimezone(timezone.utc)
    completed=[]
    dated=df[(df.date>=start)&(df.date<=end)] if 'date' in df else df.iloc[0:0]
    for gameid,game in team_rows(dated).groupby('gameid',sort=False,observed=True):
        sides=game.sort_values('side')
        if len(sides)>=2:
            completed.append({'gameid':clean(gameid),'datetime':clean(game.iloc[0].get('date')),'league':clean(game.iloc[0].get('league')),'team1':clean(sides.iloc[0].get('teamname')),'team2':clean(sides.iloc[1].get('teamname')),'mapped_team1':clean(sides.iloc[0].get('teamname')),'mapped_team2':clean(sides.iloc[1].get('teamname')),'matchable':True,'status':'completed','source':'Oracle Elixir CSV'})
    params={'action':'cargoquery','format':'json','tables':'MatchSchedule=MS','fields':'MS.Team1=team1,MS.Team2=team2,MS.DateTime_UTC=datetime,MS.OverviewPage=league,MS.Tournament=tournament,MS.BestOf=bestof','where':f"MS.DateTime_UTC >= '{start:%Y-%m-%d %H:%M:%S}' AND MS.DateTime_UTC <= '{end:%Y-%m-%d %H:%M:%S}'",'order_by':'MS.DateTime_UTC','limit':'500'}
    try:
        response=requests.get(SCHEDULE_URL,params=params,headers={'User-Agent':'LoLMatchLab/2.1 analytics project'},timeout=25);response.raise_for_status()
        raw=response.json().get('cargoquery',[]);items=[]
        for entry in raw:
            x=entry.get('title',entry);mapped1,c1=resolve_team(x.get('team1',''));mapped2,c2=resolve_team(x.get('team2',''))
            items.append({**x,'mapped_team1':mapped1,'mapped_team2':mapped2,'matchable':bool(mapped1 and mapped2),'mapping_confidence':{'team1':round(c1,2),'team2':round(c2,2)}})
        return {'date':str(day),'timezone':'America/Sao_Paulo','sources':['Oracle Elixir CSV','Leaguepedia MatchSchedule'],'completed':completed,'scheduled':items,'matches':items+completed}
    except Exception as exc:
        return {'date':str(day),'timezone':'America/Sao_Paulo','sources':['Oracle Elixir CSV'],'completed':completed,'scheduled':[],'matches':completed,'schedule_warning':f'Agenda futura indisponível: {exc}'}

class SimRequest(BaseModel):
    team_a: str
    team_b: str | None = None
    sample: int = 3
    simulations: int = 5000
    best_of: Literal[1, 3, 5] | None = None
ALIASES={'kills':['kills','teamkills'],'deaths':['deaths','teamdeaths'],'assists':['assists'],'dragons':['dragons'],'barons':['barons'],'towers':['towers'],'gold':['totalgold'],'duration':['gamelength']}
def recent(team,n,players=False):
    frame=(player_rows(df) if players else team_rows(df)); frame=frame[frame.teamname==team]
    if 'date' in frame: frame=frame.sort_values('date',ascending=False)
    ids=frame.gameid.drop_duplicates().head(n); return frame[frame.gameid.isin(ids)]
def mean(frame,metric):
    col=next((c for c in ALIASES[metric] if c in frame),None)
    if not col:return 0.0
    values=pd.to_numeric(frame[col],errors='coerce').dropna(); return float(values.mean()) if len(values) else 0.0
def poisson(lam):
    limit,k,product=math.exp(-max(.01,lam)),0,1.0
    while product>limit:k+=1;product*=random.random()
    return k-1
def score(value,low,high):
    if value is None or pd.isna(value): return None
    return round(max(0,min(100,(float(value)-low)/(high-low)*100)))
def colmean(rows,names,per_minute=False):
    col=next((c for c in names if c in rows),None)
    if not col:return None
    values=pd.to_numeric(rows[col],errors='coerce')
    if per_minute and 'gamelength' in rows: values=values/(pd.to_numeric(rows.gamelength,errors='coerce')/60)
    values=values.replace([math.inf,-math.inf],pd.NA).dropna()
    return float(values.mean()) if len(values) else None
def team_style(rows):
    kills=colmean(rows,['kills','teamkills'],True); duration=colmean(rows,['gamelength'])
    gd15=colmean(rows,['golddiffat15']); dragons=colmean(rows,['dragons']); barons=colmean(rows,['barons']); towers=colmean(rows,['towers'])
    fb=colmean(rows,['firstblood']); ft=colmean(rows,['firsttower'])
    objectives=None if dragons is None else (dragons+(barons or 0)*1.8+(towers or 0)*.25)
    early_parts=[x for x in [score(gd15,-2000,2000),score(fb,0,1),score(ft,0,1)] if x is not None]
    return {'aggressiveness':score(kills,.15,.7),'early_game':round(sum(early_parts)/len(early_parts)) if early_parts else None,'objectives':score(objectives,1.5,7),'pace':score(duration,2400,1500),'vision':score(colmean(rows,['visionscore'],True),3,9)}
def player_style(rows):
    kills=colmean(rows,['kills'],True); assists=colmean(rows,['assists'],True); cs=colmean(rows,['total cs','totalcs'],True)
    damage=colmean(rows,['damagetochampions'],True); vision=colmean(rows,['visionscore'],True); wards=colmean(rows,['wardsplaced'],True)
    kp=colmean(rows,['kills']); ap=colmean(rows,['assists']); teamkills=colmean(rows,['teamkills'])
    participation=None if teamkills in (None,0) else ((kp or 0)+(ap or 0))/teamkills
    return {'aggression':score((kills or 0)+(assists or 0)*.35,.05,.65),'participation':score(participation,.35,.85),'farm':score(cs,3,11),'damage':score(damage,200,1000),'vision':score((vision or 0)+(wards or 0)*2,0,5)}
@app.post('/simulate')
def simulate(req:SimRequest):
    require_data()
    if not req.team_b:
        rows=recent(req.team_a,max(1,min(req.sample,20)))
        if rows.empty: raise HTTPException(404,'Time sem jogos recentes')
        values={key:round(mean(rows,key),2) for key in ALIASES}
        return {'mode':'single','a':{'team':req.team_a,'sample':int(rows.gameid.nunique()),**values},
                'b':None,'team_styles':{req.team_a:team_style(rows)},
                'players':player_averages(req.team_a,req.sample),
                'history':{req.team_a:game_rates(req.team_a,req.sample)},
                'series':series_info(req.best_of),
                'note':'Referência por mapa baseada na média dos jogos selecionados, sem ajuste por adversário.'}
    if req.team_a==req.team_b: raise HTTPException(400,'Escolha dois times diferentes')
    n=max(1,min(req.sample,20)); a,b=recent(req.team_a,n),recent(req.team_b,n)
    if a.empty or b.empty: raise HTTPException(404,'Time sem jogos recentes')
    metrics=list(ALIASES); proj={req.team_a:{},req.team_b:{}}
    styles={req.team_a:team_style(a),req.team_b:team_style(b)}
    for metric in metrics:
        av,bv=mean(a,metric),mean(b,metric)
        if metric=='kills': proj[req.team_a][metric]=.62*av+.38*mean(b,'deaths');proj[req.team_b][metric]=.62*bv+.38*mean(a,'deaths')
        elif metric=='deaths': proj[req.team_a][metric]=proj[req.team_b]['kills'];proj[req.team_b][metric]=proj[req.team_a]['kills']
        else: proj[req.team_a][metric]=.62*av+.38*bv;proj[req.team_b][metric]=.62*bv+.38*av
    # Recent playstyle is part of the model: pace affects fights, early strength affects
    # gold/towers, and objective control affects dragons/barons.
    aggs=[styles[t]['aggressiveness'] for t in proj if styles[t]['aggressiveness'] is not None]
    pace_factor=.88+(sum(aggs)/len(aggs)/100*.24 if aggs else .12)
    adjusted_kills={team:proj[team]['kills']*pace_factor for team in proj}
    for team,opponent in [(req.team_a,req.team_b),(req.team_b,req.team_a)]:
        proj[team]['kills']=adjusted_kills[team];proj[team]['deaths']=adjusted_kills[opponent]
        early=styles[team]['early_game'];opp_early=styles[opponent]['early_game']
        if early is not None and opp_early is not None:
            edge=(early-opp_early)/100;proj[team]['gold']*=1+edge*.035;proj[team]['towers']*=1+edge*.08
        obj=styles[team]['objectives']
        if obj is not None:
            proj[team]['dragons']*=.8+obj/250;proj[team]['barons']*=.8+obj/250
    sims=max(500,min(req.simulations,20000)); dist={t:sorted(poisson(proj[t]['kills']) for _ in range(sims)) for t in proj}
    def summary(t): return {'team':t,'sample':int((a if t==req.team_a else b).gameid.nunique()),**{m:round(v,2) for m,v in proj[t].items()},'kills_p25':dist[t][int(.25*sims)],'kills_p75':dist[t][int(.75*sims)]}
    players=player_averages(req.team_a,n)+player_averages(req.team_b,n)
    return {'mode':'match','model':'recent-form-playstyle-v3','note':'Projeção por mapa, não resultado garantido.','a':summary(req.team_a),'b':summary(req.team_b),'team_styles':styles,'players':players,'source_rows':len(a)+len(b),'series':series_info(req.best_of),'history':{t:game_rates(t,n) for t in proj}}

def series_info(best_of):
    return {'best_of':best_of,'wins_needed':best_of//2+1 if best_of else None}

def player_averages(team,n):
    players=[]
    pf=recent(team,max(1,min(n,20)),True)
    for (player,position),rows in pf.groupby(['playername','position'],dropna=False,observed=True):
        item={'team':team,'player':clean(player),'role':clean(position),'games':int(rows.gameid.nunique())}
        for metric in ['kills','deaths','assists','totalgold','earnedgold','total cs','damagetochampions','visionscore','wardsplaced','wardskilled']:
            if metric in rows:
                vals=pd.to_numeric(rows[metric],errors='coerce').dropna()
                item[metric.replace(' ','_')]=round(float(vals.mean()),2) if len(vals) else None
        item['style']=player_style(rows)
        players.append(item)
    return players

def game_rates(team,n):
    rows=recent(team,max(1,min(n,20))).sort_values('date')
    output=[]
    for _,row in rows.drop_duplicates('gameid').iterrows():
        duration=pd.to_numeric(row.get('gamelength'),errors='coerce')
        minutes=duration/60 if pd.notna(duration) and duration>0 else None
        gold=pd.to_numeric(row.get('totalgold'),errors='coerce')
        cs=pd.to_numeric(row.get('total cs',row.get('totalcs')),errors='coerce')
        if pd.isna(cs):
            participants=player_rows(df)
            participants=participants[(participants.gameid==row.gameid)&(participants.teamname==team)]
            column=next((c for c in ['total cs','totalcs'] if c in participants),None)
            if column:
                counts=pd.to_numeric(participants[column],errors='coerce')
                if len(counts)==5 and counts.notna().all(): cs=counts.sum()
        output.append({'gameid':str(row.gameid),'date':clean(row.get('date')),
                       'gold_per_minute':round(float(gold)/minutes,2) if minutes and pd.notna(gold) else None,
                       'cs_per_minute':round(float(cs)/minutes,2) if minutes and pd.notna(cs) else None})
    return output
