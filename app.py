import os
import os as _os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime
import io

from processamento import (processar_arquivo, calcular_resumo,
                            conectadas_carregado,
                            get_data_upload_conectadas, garantir_conectadas)
from banco import (carregar_controle, salvar_controle, carregar_historico,
                   atualizar_banco, registrar_envio, registrar_bloqueio,
                   carregar_snapshots, salvar_snapshot,
                   carregar_historico_envios, registrar_envios_historico,
                   salvar_resumo, carregar_resumos)

# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT WEBHOOK — recebe bloqueio do n8n quando cliente clica em BLOQUEAR
# Chamada: GET/POST ?action=bloquear&telefone=11987654321&token=SEU_TOKEN
# ══════════════════════════════════════════════════════════════════════════════
_WEBHOOK_TOKEN = _os.getenv('WEBHOOK_TOKEN', '')

_params = st.query_params
if _params.get('action') == 'bloquear':
    _token = _params.get('token', '')
    _tel   = _params.get('telefone', '')
    if _WEBHOOK_TOKEN and _token != _WEBHOOK_TOKEN:
        st.error('Token inválido.'); st.stop()
    elif not _tel:
        st.error('Telefone não informado.'); st.stop()
    else:
        _ok = registrar_bloqueio(_tel)
        if _ok:
            st.success(f'✅ Cliente {_tel} marcado como BLOQUEADO.')
        else:
            st.warning(f'⚠️ Cliente {_tel} não encontrado.')
        st.stop()

# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Painel de Cobrança", page_icon="📊",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.stApp{background:#0F1117;}
.main .block-container{padding:1.5rem 2rem;max-width:100%;}
[data-testid="stSidebar"]{background:#161B27;border-right:1px solid #1E2535;}
h1{color:#F0F2F8!important;font-weight:700!important;}
h2,h3{color:#C8CBE0!important;font-weight:600!important;}
.mc{background:#161B27;border:1px solid #1E2535;border-radius:12px;padding:1.1rem 1.3rem;margin-bottom:.5rem;}
.mc .lb{font-size:.68rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#3B4163;margin-bottom:.2rem;}
.mc .vl{font-size:1.9rem;font-weight:700;color:#E8EAF0;font-family:'DM Mono',monospace;line-height:1.1;}
.mc .sb{font-size:.75rem;color:#5C6480;margin-top:.2rem;}
.mc .tr{font-size:.72rem;font-weight:600;margin-top:.25rem;}
.mc.verde .vl{color:#4ADE80;} .mc.verm .vl{color:#F87171;}
.mc.amar .vl{color:#FBBF24;} .mc.azul .vl{color:#60A5FA;}
.mc.roxo .vl{color:#A78BFA;}
.stButton>button{border-radius:8px;font-weight:600;border:none;transition:all .2s;}
.stButton>button:first-child{background:#2563EB;color:white;}
.stButton>button:hover{opacity:.88;transform:translateY(-1px);}
hr{border-color:#1E2535;margin:1.2rem 0;}
[data-testid="stTabs"] button{color:#5C6480!important;font-weight:500;}
[data-testid="stTabs"] button[aria-selected="true"]{color:#60A5FA!important;border-bottom-color:#60A5FA!important;}
.ok-box{background:#14532D22;border:1px solid #4ADE8044;border-radius:8px;padding:.7rem 1rem;color:#4ADE80;font-size:.85rem;margin:.4rem 0;}
.warn-box{background:#78350F22;border:1px solid #FBBF2444;border-radius:8px;padding:.7rem 1rem;color:#FBBF24;font-size:.85rem;margin:.4rem 0;}
.sec{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#3B4163;margin:1.2rem 0 .6rem 0;}
.pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.72rem;font-weight:600;}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
ETAPA_ORDER = ['Preventivo','Etapa 1','Etapa 2','Etapa 3','Etapa 4',
               'Etapa 5','Etapa 6','Etapa 7','Etapa 8']
ETAPA_COR   = {'Preventivo':'#4ADE80','Etapa 1':'#FBBF24','Etapa 2':'#FBBF24',
               'Etapa 3':'#F87171','Etapa 4':'#F87171','Etapa 5':'#A78BFA',
               'Etapa 6':'#A78BFA','Etapa 7':'#94A3B8','Etapa 8':'#94A3B8'}

def mc(label, value, sub='', tipo='', trend=''):
    trend_html = f'<div class="tr">{trend}</div>' if trend else ''
    return (f'<div class="mc {tipo}"><div class="lb">{label}</div>'
            f'<div class="vl">{value}</div>'
            f'{"<div class=sb>"+sub+"</div>" if sub else ""}'
            f'{trend_html}</div>')

def fmt_brl(v):
    try: return f"R$ {float(v):,.2f}".replace(',','X').replace('.',',').replace('X','.')
    except: return '—'

def fmt_tel(v):
    s = str(int(float(v))) if v else ''
    if len(s)==11: return f"({s[:2]}) {s[2:7]}-{s[7:]}"
    if len(s)==10: return f"({s[:2]}) {s[2:6]}-{s[6:]}"
    return s

def pct(a,b,fmt=True):
    if not b: return '—' if fmt else 0
    v = a/b
    return f"{v:.1%}" if fmt else v

def trend_str(atual, anterior):
    """Retorna HTML com seta e % de variação vs snapshot anterior."""
    if anterior is None or anterior == 0: return ''
    var = (atual - anterior) / anterior
    if var < -0.005:
        return f'<span style="color:#4ADE80">▼ {abs(var):.1%} vs anterior</span>'
    elif var > 0.005:
        return f'<span style="color:#F87171">▲ {var:.1%} vs anterior</span>'
    return f'<span style="color:#5C6480">→ estável</span>'

def exportar_wpp(df):
    cols=['NOME','NUMERO PORTADO','NUMERO LINHA','CPF','SAFRA',
          'FATURA','VALOR','VENCIMENTO','DIAS ATRASO','ETAPA','PORTABILIDADE']
    df_e=df[[c for c in cols if c in df.columns]].copy()
    df_e['NUMERO WHATSAPP']=df_e.get('NUMERO PORTADO',pd.Series(dtype='str')).apply(fmt_tel)
    df_e['VALOR FMT']=df_e.get('VALOR',pd.Series(dtype='float')).apply(fmt_brl)
    return df_e.to_csv(index=False,sep=';',encoding='utf-8-sig')

# ── Session state ─────────────────────────────────────────────────────────────
if 'df_ctrl' not in st.session_state: st.session_state.df_ctrl = carregar_controle()
if 'df_hist' not in st.session_state: st.session_state.df_hist = carregar_historico()
if 'resumos' not in st.session_state: st.session_state.resumos = carregar_resumos()
if 'snaps'        not in st.session_state: st.session_state.snaps        = carregar_snapshots()
if 'hist_envios'  not in st.session_state: st.session_state.hist_envios  = carregar_historico_envios()

# Garantir CONECTADAS carregado do Supabase ao iniciar
garantir_conectadas()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📊 Painel de Cobrança")
    st.markdown(f"<small style='color:#3B4163'>{datetime.now().strftime('%d/%m/%Y %H:%M')}</small>",
                unsafe_allow_html=True)
    st.markdown("---")

    # CONECTADAS
    st.markdown("### 🔗 Base CONECTADAS")
    if conectadas_carregado():
        data_up = get_data_upload_conectadas()
        info = f'✅ CONECTADAS carregado<br><small style="opacity:.7">Atualizado: {data_up}</small>' if data_up else '✅ CONECTADAS carregado'
        st.markdown(f'<div class="ok-box">{info}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="warn-box">⚠️ CONECTADAS não encontrado no Supabase</div>', unsafe_allow_html=True)
        st.markdown("<small style='color:#5C6480'>Importe o CSV diretamente no Supabase → tabela <b>conectadas</b></small>",
                    unsafe_allow_html=True)
        if st.button("🔄 Tentar carregar do Supabase", use_container_width=True):
            garantir_conectadas()
            st.rerun()

    st.markdown("---")

    # Upload safra
    st.markdown("### 📁 Atualizar Relatório")
    uploaded  = st.file_uploader("CSV ou XLSX", type=['csv','xlsx'], label_visibility='collapsed')
    safra_sel = st.selectbox("Safra", ['MARÇO','ABRIL','MAIO','JUNHO','JULHO',
                                        'AGOSTO','SETEMBRO','OUTUBRO','NOVEMBRO','DEZEMBRO'])

    if uploaded and st.button("⚡ Processar e Atualizar", use_container_width=True):
        with st.spinner("Processando..."):
            try:
                garantir_conectadas()  # garante cache antes de processar
                df_novo, res_novo = processar_arquivo(uploaded, safra_sel)
                df_upd, df_hist_new = atualizar_banco(
                    st.session_state.df_ctrl, df_novo, safra_sel)
                st.session_state.df_ctrl = df_upd
                st.session_state.df_hist = pd.concat(
                    [st.session_state.df_hist, df_hist_new], ignore_index=True)
                st.session_state.resumos[safra_sel] = res_novo
                salvar_resumo(safra_sel, res_novo)

                # Salvar snapshot de estorno
                pagamentos_total = len(st.session_state.df_hist[
                    st.session_state.df_hist.get('SAFRA', pd.Series()) == safra_sel
                ]) if 'SAFRA' in st.session_state.df_hist.columns else 0

                snaps = salvar_snapshot(
                    safra=safra_sel,
                    gross=res_novo['N'],
                    estorno=int(res_novo['ET']),
                    pagamentos=pagamentos_total,
                )
                st.session_state.snaps = snaps

                pagaram = len(df_hist_new)
                st.markdown(f'<div class="ok-box">✅ {len(df_novo):,} registros<br>'
                             f'💰 {pagaram:,} pagamento(s)</div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Erro: {e}")

    st.markdown("---")

    # Filtros
    df = st.session_state.df_ctrl
    if df is not None and len(df) > 0:
        st.markdown("### 🔍 Filtros")
        safras_disp  = sorted(df['SAFRA'].dropna().unique().tolist())
        filtro_safra = st.multiselect("Safra", safras_disp, default=safras_disp)
        filtro_etapa = st.multiselect("Etapa", ETAPA_ORDER, default=[])
        filtro_port  = st.selectbox("Portabilidade",['Todas','Concluida','Nao Concluida'])
        c1,c2 = st.columns(2)
        with c1: venc_ini = st.date_input("Venc. de",  value=None)
        with c2: venc_fim = st.date_input("Venc. até", value=None)
    else:
        filtro_safra=[]; filtro_etapa=[]; filtro_port='Todas'; venc_ini=None; venc_fim=None

    st.markdown("---")
    if st.button("🗑️ Limpar dados", use_container_width=True):
        from pathlib import Path
        for f in Path(__file__).parent.glob('data/*.parquet'): f.unlink()
        for k in ['df_ctrl','df_hist','resumos','snaps']:
            st.session_state[k] = pd.DataFrame() if k != 'resumos' else {}
        st.rerun()

# ── Filtrar ───────────────────────────────────────────────────────────────────
df = st.session_state.df_ctrl
if df is not None and len(df) > 0:
    df_f = df.copy()
    if filtro_safra:  df_f = df_f[df_f['SAFRA'].isin(filtro_safra)]
    if filtro_etapa:  df_f = df_f[df_f['ETAPA'].isin(filtro_etapa)]
    if filtro_port != 'Todas': df_f = df_f[df_f['PORTABILIDADE'] == filtro_port]
    if venc_ini: df_f = df_f[pd.to_datetime(df_f['VENCIMENTO'],errors='coerce').dt.date >= venc_ini]
    if venc_fim: df_f = df_f[pd.to_datetime(df_f['VENCIMENTO'],errors='coerce').dt.date <= venc_fim]
else:
    df_f = pd.DataFrame()

# ── Cabeçalho ─────────────────────────────────────────────────────────────────
st.markdown("# 📊 Painel de Cobrança")
safras_at = df['SAFRA'].unique().tolist() if df is not None and len(df) > 0 else []
st.markdown(f"<small style='color:#3B4163'>Safras: {' · '.join(safras_at) or 'Nenhuma'} — Hoje: {date.today().strftime('%d/%m/%Y')}</small>",
            unsafe_allow_html=True)
st.markdown("---")

tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
    "🎯  Controle de Envio","📈  Resumo & Funil",
    "💰  Histórico de Pagamentos","📲  Envios do Dia",
    "📋  Histórico de Envios","⚙️  Tabela de Fluxo"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 — CONTROLE DE ENVIO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab1:
    if len(df_f) == 0:
        st.markdown("""<div style='text-align:center;padding:4rem;color:#3B4163'>
            <div style='font-size:3rem'>📂</div>
            <div style='font-size:1.1rem;color:#5C6480;margin-top:1rem'>Nenhum dado carregado</div>
        </div>""", unsafe_allow_html=True)
    else:
        tot         = len(df_f)
        preventivos = int((df_f['ETAPA']=='Preventivo').sum()) if 'ETAPA' in df_f.columns else 0
        urgentes    = int(df_f['ETAPA'].isin(
            ['Etapa 3','Etapa 4','Etapa 5','Etapa 6','Etapa 7','Etapa 8']).sum()) \
            if 'ETAPA' in df_f.columns else 0
        try:
            val_tot = df_f['VALOR'].apply(
                lambda v: float(str(v).replace('R$','').replace(',','.').strip()) if v else 0
            ).sum()
        except: val_tot = 0

        c1,c2,c3,c4 = st.columns(4)
        with c1: st.markdown(mc("Total filtrado",  f"{tot:,}",          tipo='azul'),  unsafe_allow_html=True)
        with c2: st.markdown(mc("Preventivos D-2", f"{preventivos:,}",  tipo='verde'), unsafe_allow_html=True)
        with c3: st.markdown(mc("Urgentes (E3+)",  f"{urgentes:,}",     tipo='verm'),  unsafe_allow_html=True)
        with c4: st.markdown(mc("Valor em aberto", fmt_brl(val_tot),    tipo='azul'),  unsafe_allow_html=True)

        st.markdown("---")
        col_g, col_p = st.columns([2,1])
        with col_g:
            st.markdown('<div class="sec">Clientes por data de vencimento</div>', unsafe_allow_html=True)
            df_v = df_f.copy()
            df_v['VENC_DT'] = pd.to_datetime(df_v['VENCIMENTO'], errors='coerce')
            vc = df_v.groupby('VENC_DT').size().reset_index(name='QTD').dropna().sort_values('VENC_DT')
            if len(vc):
                hoje_l = date.today()
                fig=go.Figure()
                fig.add_vline(x=str(hoje_l),line_dash="dash",line_color="#F87171",
                              line_width=1.5,annotation_text="Hoje",annotation_font_color="#F87171")
                fig.add_trace(go.Bar(x=vc['VENC_DT'],y=vc['QTD'],
                    marker_color=['#F87171' if d.date()<hoje_l else
                                  '#FBBF24' if d.date()==hoje_l else '#60A5FA'
                                  for d in vc['VENC_DT']],
                    hovertemplate='%{x|%d/%m/%Y}<br>%{y} clientes<extra></extra>'))
                fig.update_layout(paper_bgcolor='#0F1117',plot_bgcolor='#161B27',
                                  font=dict(family='DM Sans',color='#5C6480'),
                                  margin=dict(l=10,r=10,t=10,b=10),height=220,
                                  xaxis=dict(gridcolor='#1E2535',tickformat='%d/%m'),
                                  yaxis=dict(gridcolor='#1E2535'),showlegend=False)
                st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})

        with col_p:
            st.markdown('<div class="sec">Portabilidade</div>', unsafe_allow_html=True)
            if 'PORTABILIDADE' in df_f.columns:
                pc_c = df_f['PORTABILIDADE'].value_counts()
                if len(pc_c):
                    fig2=go.Figure(go.Pie(labels=pc_c.index,values=pc_c.values,hole=0.65,
                        marker_colors=['#60A5FA','#F87171','#94A3B8'],textinfo='percent',
                        hovertemplate='%{label}<br>%{value:,}<extra></extra>'))
                    fig2.update_layout(paper_bgcolor='#0F1117',
                                       font=dict(family='DM Sans',color='#5C6480'),
                                       margin=dict(l=0,r=0,t=0,b=0),height=220,
                                       legend=dict(font=dict(size=10),bgcolor='#0F1117'))
                    st.plotly_chart(fig2,use_container_width=True,config={'displayModeBar':False})

        st.markdown("---")
        ch,ce = st.columns([3,1])
        with ch:
            st.markdown(f'<div class="sec">Clientes ({len(df_f):,} registros — somente Ativos)</div>',
                        unsafe_allow_html=True)
        with ce:
            st.download_button("📲 Exportar para WhatsApp",
                               data=exportar_wpp(df_f).encode('utf-8-sig'),
                               file_name=f"wpp_{date.today().strftime('%Y%m%d')}.csv",
                               mime='text/csv',use_container_width=True)

        COLS=['SAFRA','NOME','NUMERO PORTADO','NUMERO LINHA',
              'FATURA','STATUS 1ª FATURA','STATUS 2ª FATURA',
              'VALOR','VENCIMENTO','DIAS ATRASO',
              'PORTABILIDADE','ETAPA','ENVIO','ULTIMO ENVIO','STATUS PAGAMENTO']
        df_d = df_f[[c for c in COLS if c in df_f.columns]].copy()
        if 'VALOR' in df_d.columns:
            df_d['VALOR'] = pd.to_numeric(df_d['VALOR'],errors='coerce')
        if 'VENCIMENTO' in df_d.columns:
            df_d['VENCIMENTO'] = pd.to_datetime(df_d['VENCIMENTO'],errors='coerce').dt.strftime('%d/%m/%Y')
        # Limpar nan e None
        df_d = df_d.fillna('').replace('nan','').replace('None','')
        # Limpar None → vazio
        df_d = df_d.replace({None: '', 'None': ''})

        st.dataframe(df_d,use_container_width=True,height=420,hide_index=True,
                     column_config={
                         'VALOR':         st.column_config.NumberColumn('Valor',format="R$ %.2f"),
                         'DIAS ATRASO':   st.column_config.NumberColumn('Dias'),
                         'STATUS 1ª FATURA': st.column_config.TextColumn('St. 1ª Fat.'),
                         'STATUS 2ª FATURA': st.column_config.TextColumn('St. 2ª Fat.'),
                     })

        with st.expander("📝 Registrar envio realizado"):
            r1,r2,r3 = st.columns(3)
            with r1: num_in = st.text_input("Número de acesso")
            with r2: et_in  = st.selectbox("Etapa",ETAPA_ORDER)
            with r3: dt_in  = st.date_input("Data do envio",value=date.today())
            if st.button("✅ Confirmar envio"):
                if num_in:
                    registrar_envio(num_in,et_in,et_in,dt_in)
                    st.success("Envio registrado!"); st.rerun()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 — RESUMO & FUNIL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab2:
    df_hist = st.session_state.df_hist
    snaps   = st.session_state.snaps

    if df is None or len(df) == 0:
        st.info("Carregue um arquivo para ver o resumo.")
    else:
        # Funil
        st.markdown('<div class="sec">Funil de cobrança</div>', unsafe_allow_html=True)
        ec = df['ETAPA'].value_counts() if 'ETAPA' in df.columns else pd.Series()
        cols_f = st.columns(len(ETAPA_ORDER))
        for i,et in enumerate(ETAPA_ORDER):
            n=int(ec.get(et,0)); cor=ETAPA_COR.get(et,'#fff')
            with cols_f[i]:
                st.markdown(f"""<div style='text-align:center;background:#161B27;
                    border:1px solid #1E2535;border-top:3px solid {cor};
                    border-radius:8px;padding:.8rem .3rem'>
                    <div style='font-size:.6rem;color:#3B4163;font-weight:700;
                         letter-spacing:.08em;text-transform:uppercase'>{et}</div>
                    <div style='font-size:1.5rem;font-weight:700;color:{cor};
                         font-family:DM Mono,monospace;margin:.2rem 0'>{n:,}</div>
                </div>""",unsafe_allow_html=True)

        st.markdown("---")

        # Resumo por safra com controle de estorno
        st.markdown('<div class="sec">Resumo por safra — controle de estorno</div>',
                    unsafe_allow_html=True)
        safras = sorted(df['SAFRA'].dropna().unique().tolist())

        for safra in safras:
            df_s = df[df['SAFRA'] == safra]
            res  = st.session_state.resumos.get(safra)

            # Calcular métricas do controle
            N  = res['N']  if res else len(df_s)
            NA = res['NA'] if res else int((df_s.get('STATUS ACESSO','') == 'Ativo').sum())
            NC = res['NC'] if res else (N - NA)
            ET = int(res['ET']) if res else 0
            MV = res['MV'] if res else N * 0.38
            RV = res['RV'] if res else ET - MV
            META = 0.38

            # Pagamentos desta safra (baixas)
            if df_hist is not None and len(df_hist) > 0 and 'SAFRA' in df_hist.columns:
                pag_safra = len(df_hist[df_hist['SAFRA'] == safra])
            else:
                pag_safra = 0

            # Snapshots desta safra para comparação
            snap_safra = None
            snap_ant   = None
            if snaps is not None and len(snaps) > 0 and 'SAFRA' in snaps.columns:
                snap_safra = snaps[snaps['SAFRA'] == safra].sort_values('DATA')
                if len(snap_safra) >= 2:
                    snap_ant = snap_safra.iloc[-2]
                elif len(snap_safra) == 1:
                    snap_ant = None

            # % variação estorno vs snapshot anterior
            et_ant = float(snap_ant['PCT_ESTORNO']) if snap_ant is not None else None
            et_pct_atual = pct(ET, N, fmt=False) * 100 if N else 0
            var_estorno = trend_str(et_pct_atual, et_ant)

            # % redução necessária = quanto falta para chegar na meta
            red_necessaria = max(0, ET - MV)
            pct_red_nec    = pct(int(red_necessaria), ET) if ET else '—'

            st.markdown(f"### {safra}")
            c1,c2,c3,c4,c5,c6 = st.columns(6)

            # Buscar cobertura do Supabase
            _cob_data = None
            try:
                import os as _os2
                from supabase import create_client as _cc2
                _sb2 = _cc2(_os2.getenv('SUPABASE_URL',''), _os2.getenv('SUPABASE_KEY',''))
                _r = _sb2.table('safras').select(
                    '"LINHAS_CONECTADAS","FATURAS_ENCONTRADAS","COBERTURA_PCT"'
                ).eq('"SAFRA"', safra).limit(1).execute()
                if _r.data: _cob_data = _r.data[0]
            except: pass

            with c1:
                sub_gross = f"✅ Ativos: {NA:,} ({pct(NA,N)})  ❌ Canc: {NC:,} ({pct(NC,N)})"
                if _cob_data:
                    lin = _cob_data.get('LINHAS_CONECTADAS') or 0
                    fat = _cob_data.get('FATURAS_ENCONTRADAS') or 0
                    cob = float(_cob_data.get('COBERTURA_PCT') or 0)
                    cor_cob = 'verde' if cob >= 88 else 'amarelo' if cob >= 80 else 'verm'
                    sub_gross += f"<br>📡 Cobertura: {cob:.1f}% ({fat:,}/{lin:,})"
                st.markdown(mc("Gross", f"{N:,}", sub=sub_gross, tipo='azul'),
                            unsafe_allow_html=True)
            with c2:
                st.markdown(mc("% Estorno Atual",
                               f"{pct(ET,N)}",
                               sub=f"{ET:,} clientes em risco",
                               tipo='verm',
                               trend=var_estorno),
                            unsafe_allow_html=True)
            with c3:
                st.markdown(mc("Meta de Estorno",
                               f"{META:.0%}",
                               sub=f"Máx. {int(MV):,} clientes",
                               tipo='amar'),
                            unsafe_allow_html=True)
            with c4:
                st.markdown(mc("Baixas (pagamentos)",
                               f"{pag_safra:,}",
                               sub=f"{pct(pag_safra, ET)} do estorno",
                               tipo='verde'),
                            unsafe_allow_html=True)
            with c5:
                st.markdown(mc("Redução Necessária",
                               f"{int(red_necessaria):,}",
                               sub=f"{pct_red_nec} do estorno atual",
                               tipo='roxo'),
                            unsafe_allow_html=True)
            with c6:
                # Evolução do estorno ao longo das atualizações
                if snap_safra is not None and len(snap_safra) >= 2:
                    pct_ant = float(snap_safra.iloc[-2]['PCT_ESTORNO'])
                    pct_atu = float(snap_safra.iloc[-1]['PCT_ESTORNO'])
                    delta   = pct_ant - pct_atu
                    tipo_ev = 'verde' if delta > 0 else 'verm'
                    st.markdown(mc("Evolução",
                                   f"{delta:+.1f}pp",
                                   sub=f"{pct_ant:.1f}% → {pct_atu:.1f}%",
                                   tipo=tipo_ev),
                                unsafe_allow_html=True)
                else:
                    st.markdown(mc("Evolução","—",
                                   sub="Atualização a seguir",
                                   tipo='azul'),
                                unsafe_allow_html=True)

            # Gráfico de evolução do estorno
            if snap_safra is not None and len(snap_safra) > 1:
                fig_ev = go.Figure()
                fig_ev.add_trace(go.Scatter(
                    x=snap_safra['DATA'].astype(str),
                    y=snap_safra['PCT_ESTORNO'],
                    mode='lines+markers',
                    line=dict(color='#F87171', width=2),
                    marker=dict(size=6, color='#F87171'),
                    name='% Estorno',
                    hovertemplate='%{x}<br>%{y:.1f}% estorno<extra></extra>',
                ))
                fig_ev.add_hline(y=META*100, line_dash="dash",
                                  line_color="#FBBF24", line_width=1.5,
                                  annotation_text=f"Meta {META:.0%}",
                                  annotation_font_color="#FBBF24")
                fig_ev.update_layout(
                    paper_bgcolor='#0F1117', plot_bgcolor='#161B27',
                    font=dict(family='DM Sans', color='#5C6480'),
                    margin=dict(l=10,r=10,t=10,b=10), height=160,
                    xaxis=dict(gridcolor='#1E2535'),
                    yaxis=dict(gridcolor='#1E2535', ticksuffix='%'),
                    showlegend=False,
                )
                st.plotly_chart(fig_ev, use_container_width=True, config={'displayModeBar':False})

            # Detalhamento das categorias
            if res and res.get('rows'):
                with st.expander("Ver detalhamento de faturas"):
                    SIM={'1 FATURA ABERTA','2 FATURAS (2 ABERTA)',
                         '2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA'}
                    for label,t,pc_v,sp in res['rows']:
                        if t == 0: continue
                        sim = label in SIM
                        cor = "#F87171" if sim else "#4ADE80"
                        pct_label = f"{t/NA:.0%}" if NA else "—"
                        st.markdown(f"""<div style='display:flex;justify-content:space-between;
                            align-items:center;padding:.35rem .6rem;border-radius:5px;
                            margin-bottom:3px;background:#161B27;border-left:3px solid {cor}'>
                            <span style='font-size:.82rem;color:#9EA5C0'>{label}</span>
                            <div>
                              <span style='font-size:.82rem;font-weight:700;color:{cor}'>{t:,}</span>
                              <span style='font-size:.72rem;color:#3B4163;margin-left:8px'>{pct_label}</span>
                            </div>
                        </div>""",unsafe_allow_html=True)

            st.markdown("---")

        # Gráfico de pagamentos por etapa
        if df_hist is not None and len(df_hist)>0 and 'ETAPA NO PAGAMENTO' in df_hist.columns:
            st.markdown('<div class="sec">Pagamentos registrados por etapa</div>',
                        unsafe_allow_html=True)
            hc=df_hist.groupby('ETAPA NO PAGAMENTO').size().reset_index(name='QTD')
            fig3=go.Figure(go.Bar(x=hc['ETAPA NO PAGAMENTO'],y=hc['QTD'],
                                   marker_color='#60A5FA',
                                   hovertemplate='%{x}<br>%{y} pagamentos<extra></extra>'))
            fig3.update_layout(paper_bgcolor='#0F1117',plot_bgcolor='#161B27',
                               font=dict(family='DM Sans',color='#5C6480'),
                               margin=dict(l=10,r=10,t=10,b=10),height=200,
                               xaxis=dict(gridcolor='#1E2535'),
                               yaxis=dict(gridcolor='#1E2535'))
            st.plotly_chart(fig3,use_container_width=True,config={'displayModeBar':False})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 — HISTÓRICO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab3:
    dh=st.session_state.df_hist
    if dh is None or len(dh)==0:
        st.markdown("""<div style='text-align:center;padding:4rem;color:#3B4163'>
            <div style='font-size:3rem'>💰</div>
            <div style='font-size:1.1rem;color:#5C6480;margin-top:1rem'>Nenhum pagamento ainda</div>
            <div style='font-size:.85rem;margin-top:.5rem'>Aparecem automaticamente ao atualizar o relatório</div>
        </div>""",unsafe_allow_html=True)
    else:
        val_p=0
        if 'VALOR' in dh.columns:
            try: val_p=dh['VALOR'].apply(
                lambda v: float(str(v).replace('R$','').replace(',','.')) if v else 0).sum()
            except: pass
        pe=dh['ETAPA NO PAGAMENTO'].value_counts() if 'ETAPA NO PAGAMENTO' in dh.columns else pd.Series()
        melhor=pe.index[0] if len(pe) else '—'
        h1,h2,h3 = st.columns(3)
        with h1: st.markdown(mc("Total pagamentos",f"{len(dh):,}",tipo='verde'),unsafe_allow_html=True)
        with h2: st.markdown(mc("Valor recuperado",fmt_brl(val_p),tipo='verde'),unsafe_allow_html=True)
        with h3: st.markdown(mc("Etapa c/ + pagamentos",melhor,tipo='azul'),unsafe_allow_html=True)
        st.markdown("---")
        st.dataframe(dh,use_container_width=True,height=420,hide_index=True)
        buf=io.BytesIO(); dh.to_excel(buf,index=False,engine='openpyxl')
        st.download_button("⬇️ Exportar XLSX",data=buf.getvalue(),
                           file_name=f"historico_{date.today().strftime('%Y%m%d')}.xlsx",
                           mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 — ENVIOS DO DIA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab4:
    import requests as _req
    WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL', '')

    # Mapeamento etapa → HSM (configurar no Streamlit Cloud Secrets)
    HSM_MAP = {
        'Preventivo': os.getenv('HSM_PREVENTIVO', 'hsm_preventivo'),
        'Etapa 1':    os.getenv('HSM_ETAPA1',     'hsm_etapa1'),
        'Etapa 2':    os.getenv('HSM_ETAPA2',     'hsm_etapa2'),
        'Etapa 3':    os.getenv('HSM_ETAPA3',     'hsm_etapa3'),
        'Etapa 4':    os.getenv('HSM_ETAPA4',     'hsm_etapa4'),
        'Etapa 5':    os.getenv('HSM_ETAPA5',     'hsm_etapa5'),
        'Etapa 6':    os.getenv('HSM_ETAPA6',     'hsm_etapa6'),
        'Etapa 7':    os.getenv('HSM_ETAPA7',     'hsm_etapa7'),
        'Etapa 8':    os.getenv('HSM_ETAPA8',     'hsm_etapa8'),
    }

    st.markdown("### 📲 Envios do Dia")
    st.markdown("<small style='color:#3B4163'>Clientes que devem receber mensagem hoje, agrupados por etapa</small>",
                unsafe_allow_html=True)

    if df is None or len(df) == 0:
        st.info("Carregue um arquivo de safra para ver os envios do dia.")
    else:
        hoje = date.today()
        df_envio = df[df['ETAPA'].notna()].copy()
        # Converter ULTIMO ENVIO para date com segurança (pode vir como string do Supabase)
        if 'ULTIMO ENVIO' in df_envio.columns:
            df_envio['_ULT_DT'] = pd.to_datetime(df_envio['ULTIMO ENVIO'], errors='coerce').dt.date
        else:
            df_envio['_ULT_DT'] = None
        df_envio_hoje = df_envio[
            df_envio['_ULT_DT'].isna() |
            df_envio['_ULT_DT'].apply(lambda d: d < hoje if pd.notna(d) and d is not None else True)
        ].copy()

        por_etapa = df_envio_hoje['ETAPA'].value_counts()
        total_hoje = len(df_envio_hoje)
        prev_n = int(por_etapa.get('Preventivo', 0))

        c1,c2,c3 = st.columns(3)
        with c1: st.markdown(mc('A enviar hoje', f'{total_hoje:,}', tipo='azul'), unsafe_allow_html=True)
        with c2: st.markdown(mc('Preventivos', f'{prev_n:,}', tipo='verde'), unsafe_allow_html=True)
        with c3: st.markdown(mc('Em atraso (E1+)', f'{total_hoje - prev_n:,}', tipo='verm'), unsafe_allow_html=True)

        st.markdown('---')

        # Webhook e HSMs configurados via Streamlit Secrets — sem necessidade de digitar
        if not WEBHOOK_URL:
            st.warning("⚠️ Webhook n8n não configurado. Adicione N8N_WEBHOOK_URL nos Secrets do Streamlit Cloud.")
        else:
            st.markdown(f'<div class="ok-box">✅ Webhook configurado · HSMs mapeados por etapa</div>',
                        unsafe_allow_html=True)

        st.markdown('---')

        for etapa in ETAPA_ORDER:
            df_et = df_envio_hoje[df_envio_hoje['ETAPA'] == etapa]
            if len(df_et) == 0:
                continue

            cor = ETAPA_COR.get(etapa, '#fff')
            col_hdr, col_btn = st.columns([3, 1])
            with col_hdr:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:10px;margin:.8rem 0 .4rem'>"
                    f"<div style='width:10px;height:10px;border-radius:50%;background:{cor}'></div>"
                    f"<span style='font-weight:600;color:#E8EAF0'>{etapa}</span>"
                    f"<span style='color:#3B4163;font-size:.82rem'>{len(df_et):,} clientes</span>"
                    f"</div>", unsafe_allow_html=True)
        # ── Resumo do dia ─────────────────────────────────────────────────────
        st.markdown('<div class="sec">Mensagens enviadas hoje</div>', unsafe_allow_html=True)
        hist_env = st.session_state.hist_envios
        cols_res = st.columns(len(ETAPA_ORDER))
        for i, et in enumerate(ETAPA_ORDER):
            cor  = ETAPA_COR.get(et, '#fff')
            n_env = 0
            if hist_env is not None and len(hist_env) > 0 and et in hist_env.columns:
                n_env = int(hist_env[et].apply(
                    lambda v: str(v)[:10] == str(hoje) if pd.notna(v) and v else False
                ).sum())
            with cols_res[i]:
                st.markdown(f"""<div style='text-align:center;background:#161B27;
                    border:1px solid #1E2535;border-top:2px solid {cor};
                    border-radius:8px;padding:.5rem .3rem;margin-bottom:.8rem'>
                    <div style='font-size:.6rem;color:#3B4163;font-weight:700;
                         letter-spacing:.08em;text-transform:uppercase'>{et}</div>
                    <div style='font-size:1.3rem;font-weight:700;color:{cor};
                         font-family:DM Mono,monospace'>{n_env:,}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown('---')

        for etapa in ETAPA_ORDER:
            df_et = df_envio_hoje[df_envio_hoje['ETAPA'] == etapa]
            if len(df_et) == 0:
                continue

            cor = ETAPA_COR.get(etapa, '#fff')
            col_hdr, col_btn = st.columns([3, 1])
            with col_hdr:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:10px;margin:.8rem 0 .4rem'>"
                    f"<div style='width:10px;height:10px;border-radius:50%;background:{cor}'></div>"
                    f"<span style='font-weight:600;color:#E8EAF0'>{etapa}</span>"
                    f"<span style='color:#3B4163;font-size:.82rem'>{len(df_et):,} clientes</span>"
                    f"</div>", unsafe_allow_html=True)
            with col_btn:
                if st.button(f'📲 Disparar {etapa}', key=f'btn_{etapa}', use_container_width=True):
                    st.session_state[f'confirmar_{etapa}'] = True

            # Modal de confirmação
            if st.session_state.get(f'confirmar_{etapa}'):
                st.warning(f'⚠️ Confirmar envio de **{len(df_et):,} clientes** para **{etapa}**?')
                col_sim, col_nao = st.columns(2)
                with col_sim:
                    if st.button(f'✅ Confirmar envio', key=f'sim_{etapa}', use_container_width=True):
                        if not WEBHOOK_URL:
                            st.error('Configure a URL do webhook n8n.')
                        else:
                            records = []
                            for _, r in df_et.iterrows():
                                tel_p = str(r.get('NUMERO PORTADO','') or '').strip()
                                nl    = str(r.get('NUMERO LINHA','') or '').strip()
                                venc  = r.get('VENCIMENTO')
                                try:
                                    venc_fmt = pd.to_datetime(venc, errors='coerce').strftime('%d/%m/%Y')
                                except: venc_fmt = ''
                                records.append({
                                    'CPF': str(r.get('CPF','') or ''),
                                    'SAFRA': str(r.get('SAFRA','') or ''),
                                    'ETAPA': etapa,
                                    'HSM': HSM_MAP.get(etapa,''),
                                    'PORTABILIDADE': str(r.get('PORTABILIDADE','') or ''),
                                    'FATURA': int(r.get('FATURA',1) or 1),
                                    'DIAS_ATRASO': int(r.get('DIAS ATRASO',0) or 0),
                                    'TELEFONE_PORTADO': tel_p,
                                    'NUMERO_LINHA': nl,
                                    'hsm_numero': tel_p,
                                    'hsm_nome': str(r.get('NOME','') or ''),
                                    'hsm_valor': fmt_brl(r.get('VALOR')),
                                    'hsm_vencimento': venc_fmt,
                                })
                            try:
                                with st.spinner(f'Enviando {len(records):,} mensagens...'):
                                    resp = _req.post(WEBHOOK_URL,
                                        json={'etapa': etapa, 'hsm': HSM_MAP.get(etapa,''),
                                              'total': len(records), 'data': str(hoje),
                                              'clientes': records},
                                        timeout=30)
                                if resp.status_code in (200, 201):
                                    # Atualizar ULTIMO ENVIO no controle — string para evitar ArrowTypeError
                                    mask = st.session_state.df_ctrl['ETAPA'] == etapa
                                    st.session_state.df_ctrl.loc[mask, 'ULTIMO ENVIO'] = str(hoje)
                                    salvar_controle(st.session_state.df_ctrl)
                                    # Registrar no histórico de envios
                                    registrar_envios_historico(df_et, etapa, hoje)
                                    st.session_state.hist_envios = carregar_historico_envios()
                                    st.session_state.pop(f'confirmar_{etapa}', None)
                                    st.success(f'✅ {len(records):,} mensagens enviadas com sucesso! ({etapa})')
                                    st.rerun()
                                else:
                                    st.error(f'Erro webhook: {resp.status_code} — {resp.text[:200]}')
                            except Exception as e:
                                st.error(f'Erro: {e}')
                with col_nao:
                    if st.button('❌ Cancelar', key=f'nao_{etapa}', use_container_width=True):
                        st.session_state.pop(f'confirmar_{etapa}', None)
                        st.rerun()


            cols_show = ['NOME','NUMERO PORTADO','NUMERO LINHA','FATURA',
                         'STATUS 1ª FATURA','STATUS 2ª FATURA',
                         'VALOR','VENCIMENTO','DIAS ATRASO','PORTABILIDADE']
            df_show = df_et[[c for c in cols_show if c in df_et.columns]].copy()
            if 'VALOR' in df_show.columns:
                df_show['VALOR'] = pd.to_numeric(df_show['VALOR'], errors='coerce')
            if 'VENCIMENTO' in df_show.columns:
                df_show['VENCIMENTO'] = pd.to_datetime(
                    df_show['VENCIMENTO'], errors='coerce').dt.strftime('%d/%m/%Y')
            df_show = df_show.replace({None: '', 'None': ''})
            st.dataframe(df_show, use_container_width=True,
                         height=min(250, 38 + len(df_show)*35),
                         hide_index=True,
                         column_config={
                             'VALOR': st.column_config.NumberColumn('Valor', format='R$ %.2f'),
                             'DIAS ATRASO': st.column_config.NumberColumn('Dias'),
                         })
            csv_et = exportar_wpp(df_et)
            st.download_button(f'⬇️ Baixar lista {etapa}',
                               data=csv_et.encode('utf-8-sig'),
                               file_name=f'{etapa.lower().replace(" ","_")}_{hoje}.csv',
                               mime='text/csv', key=f'dl_{etapa}')
            st.markdown('<hr style="margin:.6rem 0;opacity:.15">', unsafe_allow_html=True)

        # ── Painel de bloqueados ──────────────────────────────────────────────
        st.markdown('---')
        st.markdown('<div class="sec">Clientes que solicitaram bloqueio</div>', unsafe_allow_html=True)
        df_bloq = df[df['STATUS PAGAMENTO'] == 'BLOQUEADO'] if df is not None and len(df) > 0 else pd.DataFrame()
        if len(df_bloq) == 0:
            st.markdown("<small style='color:#3B4163'>Nenhum cliente solicitou bloqueio ainda.</small>",
                        unsafe_allow_html=True)
        else:
            st.markdown(mc('Bloqueados', f'{len(df_bloq):,}',
                           sub='Não receberão novos envios', tipo='verm'),
                        unsafe_allow_html=True)
            cols_b = ['SAFRA','NOME','NUMERO PORTADO','NUMERO LINHA',
                      'FATURA','VALOR','VENCIMENTO','PORTABILIDADE']
            df_b = df_bloq[[c for c in cols_b if c in df_bloq.columns]].copy()
            df_b = df_b.replace({None:'','None':''})
            st.dataframe(df_b, use_container_width=True, height=200, hide_index=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 5 — HISTÓRICO DE ENVIOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab5:
    st.markdown("### 📋 Histórico de Envios por Cliente")
    st.markdown("<small style='color:#3B4163'>Uma linha por cliente — colunas mostram a data de cada envio por etapa</small>",
                unsafe_allow_html=True)

    df_he = st.session_state.hist_envios
    if df_he is None or len(df_he) == 0:
        st.markdown("""<div style='text-align:center;padding:4rem;color:#3B4163'>
            <div style='font-size:3rem'>📋</div>
            <div style='font-size:1.1rem;color:#5C6480;margin-top:1rem'>Nenhum envio registrado ainda</div>
            <div style='font-size:.85rem;margin-top:.5rem'>Os envios aparecem aqui automaticamente após cada disparo</div>
        </div>""", unsafe_allow_html=True)
    else:
        # Métricas
        total_clientes = len(df_he)
        # Quantos receberam pelo menos 1 mensagem
        etapa_cols = [c for c in ETAPA_ORDER if c in df_he.columns]
        receberam  = int(df_he[etapa_cols].notna().any(axis=1).sum()) if etapa_cols else 0

        h1, h2, h3 = st.columns(3)
        with h1: st.markdown(mc('Clientes no histórico', f'{total_clientes:,}', tipo='azul'), unsafe_allow_html=True)
        with h2: st.markdown(mc('Receberam mensagem', f'{receberam:,}', tipo='verde'), unsafe_allow_html=True)
        with h3:
            # Etapa com mais envios
            mais_enviada = '—'
            if etapa_cols:
                contagens = {et: int(df_he[et].notna().sum()) for et in etapa_cols if et in df_he.columns}
                if contagens:
                    mais_enviada = max(contagens, key=contagens.get)
            st.markdown(mc('Etapa mais enviada', mais_enviada, tipo='roxo'), unsafe_allow_html=True)

        st.markdown('---')

        # Filtros
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            safras_he = ['Todas'] + sorted(df_he['SAFRA'].dropna().unique().tolist()) \
                        if 'SAFRA' in df_he.columns else ['Todas']
            filtro_he_safra = st.selectbox('Safra', safras_he, key='he_safra')
        with col_f2:
            filtro_he_etapa = st.selectbox('Etapa enviada', ['Todas'] + ETAPA_ORDER, key='he_etapa')

        df_he_f = df_he.copy()
        if filtro_he_safra != 'Todas' and 'SAFRA' in df_he_f.columns:
            df_he_f = df_he_f[df_he_f['SAFRA'] == filtro_he_safra]
        if filtro_he_etapa != 'Todas' and filtro_he_etapa in df_he_f.columns:
            df_he_f = df_he_f[df_he_f[filtro_he_etapa].notna()]

        # Colunas a exibir
        base_cols = ['SAFRA','NOME','NUMERO PORTADO','NUMERO LINHA','CPF','PORTABILIDADE']
        etapa_display = [c for c in ETAPA_ORDER if c in df_he_f.columns]
        show_cols = [c for c in base_cols if c in df_he_f.columns] + etapa_display

        df_he_show = df_he_f[show_cols].copy()
        df_he_show = df_he_show.fillna('').replace('None','')

        st.dataframe(df_he_show, use_container_width=True, height=450, hide_index=True)

        # Export
        buf = io.BytesIO()
        df_he_show.to_excel(buf, index=False, engine='openpyxl')
        st.download_button('⬇️ Exportar XLSX',
                           data=buf.getvalue(),
                           file_name=f'historico_envios_{date.today().strftime("%Y%m%d")}.xlsx',
                           mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


with tab6:
    st.markdown("### Funil de Cobrança — Regras de Envio")
    fluxo=[
        ("D-2 antes do vencimento","Preventivo","Lembrete","Todos","🟢"),
        ("0 a 6 dias","—","Aguardar","—","⚪"),
        ("7 a 10 dias","Etapa 1","Cobrança","Todos","🟡"),
        ("11 a 15 dias","Etapa 2","Cobrança","Todos","🟡"),
        ("16 a 23 dias","Etapa 3","Cobrança","Todos","🔴"),
        ("24 a 30 dias","Etapa 4","Cobrança","Todos","🔴"),
        ("31 a 42 dias","Etapa 5","Alto Potencial","Port. Concluída","🟣"),
        ("43 a 50 dias","Etapa 6","Alto Potencial","Port. Concluída","🟣"),
        ("51 a 62 dias","Etapa 7","Alto Potencial","Port. Concluída","⚫"),
        ("63 a 70 dias","Etapa 8","Alto Potencial","Port. Concluída","⚫"),
    ]
    df_fl=pd.DataFrame(fluxo,columns=['Dias de Atraso','Etapa','Tipo','Portabilidade',''])
    st.dataframe(df_fl,use_container_width=True,hide_index=True,height=400)
    st.markdown("---")
    st.markdown("""
**Regras:**
- Fatura mais urgente: quando há 2 abertas, considera a de **menor vencimento**
- Etapas 5-8: **exclusivo** para Portabilidade Concluída
- Cancelados/Bloqueados: apenas no resumo de estorno
- A cada atualização, um **snapshot** é salvo para rastrear a evolução % semana a semana
    """)
