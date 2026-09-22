# LoL Match Lab

Aplicação full-stack para analytics de LoL competitivo usando FastAPI, React, TypeScript e ECharts.

## Recursos

- Download e importação automática do CSV anual do Oracle's Elixir ao iniciar
- Cache local para funcionar com o último CSV salvo
- Filtro por liga competitiva e times da liga
- Aba Confrontos de hoje com todas as ligas e horário de Brasília
- Jogos de hoje já registrados são lidos do CSV; confrontos futuros usam a agenda pública
- Botão para simular diretamente cada confronto de hoje usando histórico e estilos
- Partidas com as duas linhas de time, dez jogadores e todas as colunas originais
- Simulação usando os últimos 3, 5, 10 ou 20 jogos
- 5.000 cenários Monte Carlo e faixas P25/P75
- Estilo dos times: agressividade, early game, objetivos, ritmo e visão
- Estilo dos jogadores: agressividade, participação, farm, dano e visão
- O perfil de estilo influencia kills, ritmo, gold, torres, dragões e barões

Quando uma coluna não existe na fonte, a interface mostra N/D; o programa não inventa dados.

## Executar no Windows

Abra um terminal na pasta do projeto:

    cd backend
    run.bat

Na primeira execução aguarde o download e a importação. Depois abra outro terminal:

    cd frontend
    npm install
    npm run dev

Acesse http://localhost:5173. A documentação da API fica em http://localhost:8000/docs.

## Atualização

O arquivo do ano atual é baixado quando ainda não existe. Para forçar a atualização, use POST /data/refresh na documentação da API ou apague o CSV em backend/data antes de iniciar.

Outra URL ou ano podem ser configurados com OE_CSV_URL e OE_YEAR.

## Limitação

Todos os dados significa todas as colunas fornecidas pelo CSV. Eventos não publicados pela fonte não podem ser reconstruídos com precisão. As projeções são estatísticas, não resultados garantidos.
