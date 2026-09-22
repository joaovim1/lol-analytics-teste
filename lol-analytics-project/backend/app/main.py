from __future__ import annotations
import math, os, random, re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

YEAR=int(os.getenv('OE_YEAR',datetime.now(timezone.utc).year)); DATA_DIR=Path(__file__).resolve().parents[1]/'data'; DATA_DIR.mkdir(exist_ok=True)
CSV_PATH=DATA_DIR/f'{YEAR}_LoL_esports_match_data_from_OraclesElixir.csv'
SOURCE_URL=os.getenv('OE_CSV_URL',f'https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com/{YEAR}_LoL_esports_match_data_from_OraclesElixir.gzip')
SCHEDULE_URL=os.getenv('SCHEDULE_API_URL','https://lol.fandom.com/api.php')
app=FastAPI(title='LoL Competitive Analytics',version='2.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://localhost:3000'],allow_methods=['*'],allow_headers=['*'])
df=pd.DataFrame(); state={'status':'starting','year':YEAR,'source':SOURCE_URL}

def clean(v:Any):
    if pd.isna(v): return None
    if hasattr(v,'item'): v=v.item()
    if isinstance(v,(pd.Timestamp,datetime)): return v.isoformat()
    return int(v) if isinstance(v,float) and v.is_integer() else v
def records(frame): return [{k:clean(v) for k,v in row.items()} for row in frame.to_dict('records')]
def team_rows(frame): return frame[frame.position.astype(str).str.lower()=='team']
def player_rows(frame): return frame[frame.position.astype(str).str.lower()!='team']

def load_csv(force=False):
    global df,state
    state={'status':'downloading','year':YEAR,'source':SOURCE_URL}; warning=None
    if force or not CSV_PATH.exists():
        tmp=CSV_PATH.with_suffix('.gzip.tmp')
        try:
            with requests.get(SOURCE_URL,stream=True,timeout=(15,180)) as response:
                response.raise_for_status()
                with tmp.open('wb') as out:
                    for chunk in response.iter_content(1024*1024):
                        if chunk: out.write(chunk)
            pd.read_csv(tmp,compression='gzip',low_memory=False).to_csv(CSV_PATH,index=False); tmp.unlink(missing_ok=True)
        except Exception as exc:
            tmp.unlink(missing_ok=True); warning=str(exc)
            if not CSV_PATH.exists(): state={'status':'error','message':warning,'year':YEAR,'source':SOURCE_URL}; return state
    try:
        df=pd.read_csv(CSV_PATH,low_memory=False)
        if 'date' in df: df['date']=pd.to_datetime(df.date,errors='coerce',utc=True)
        state={'status':'ready','year':YEAR,'source':SOURCE_URL,'rows':len(df),'games':int(df.gameid.nunique()),'columns':len(df.columns),'cached_file':str(CSV_PATH),'download_warning':warning}
    except Exception as exc: state={'status':'error','message':str(exc),'year':YEAR,'source':SOURCE_URL}
    return state

@app.on_event('startup')
def startup(): load_csv()
def require_data():
    if df.empty: raise HTTPException(503,f"Dataset indisponível: {state.get('message','importando')}")
@app.get('/health')
def health(): return state
@app.post('/data/refresh')
def refresh(): return load_csv(True)
@app.get('/leagues')
def leagues(): require_data(); return sorted(df.league.dropna().astype(str).unique().tolist())
@app.get('/teams')
def teams(league:str|None=None):
    require_data(); frame=team_rows(df)
    if league: frame=frame[frame.league==league]
    cols=[c for c in ['teamname','teamid','league'] if c in frame]
    return records(frame[cols].dropna(subset=['teamname']).drop_duplicates().sort_values('teamname'))
@app.get('/matches')
def matches(league:str|None=None,limit:int=Query(50,ge=1,le=500)):
    require_data(); frame=team_rows(df)
    if league: frame=frame[frame.league==league]
    frame=frame.sort_values('date' if 'date' in frame else 'gameid',ascending=False); out=[]
    for gameid,game in frame.groupby('gameid',sort=False):
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
    for gameid,game in team_rows(dated).groupby('gameid',sort=False):
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

class SimRequest(BaseModel): team_a:str; team_b:str; sample:int=3; simulations:int=5000
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
    def summary(t): return {'team':t,'sample':n,**{m:round(v,2) for m,v in proj[t].items()},'kills_p25':dist[t][int(.25*sims)],'kills_p75':dist[t][int(.75*sims)]}
    players=[]
    for team in proj:
        pf=recent(team,n,True)
        for (player,position),rows in pf.groupby(['playername','position'],dropna=False):
            item={'team':team,'player':clean(player),'role':clean(position),'games':int(rows.gameid.nunique())}
            for metric in ['kills','deaths','assists','totalgold','earnedgold','total cs','damagetochampions','visionscore','wardsplaced','wardskilled']:
                if metric in rows:
                    vals=pd.to_numeric(rows[metric],errors='coerce').dropna();item[metric.replace(' ','_')]=round(float(vals.mean()),2) if len(vals) else None
            item['style']=player_style(rows);players.append(item)
    return {'model':'recent-form-playstyle-v3','note':'Projeção estatística, não resultado garantido.','a':summary(req.team_a),'b':summary(req.team_b),'team_styles':styles,'players':players,'source_rows':len(a)+len(b)}
