"""
processamento.py — Lê arquivo bruto da safra, aplica filtros e regras de negócio.
CONECTADAS e SAFRAS são persistidas no Supabase.
"""

import pandas as pd
from datetime import date, datetime
import os
from pathlib import Path

# ── Cache em memória (evita re-carregar a cada interação) ─────────────────────
_PORT_CACHE = {}
_CONECTADAS_DATA_UPLOAD = None

def get_data_upload_conectadas():
    return _CONECTADAS_DATA_UPLOAD

def conectadas_carregado():
    return bool(_PORT_CACHE)

def _get_sb():
    from supabase import create_client
    url = os.getenv('SUPABASE_URL','')
    key = os.getenv('SUPABASE_KEY','')
    if not url or not key:
        return None
    return create_client(url, key)

# ── Carregar CONECTADAS do Supabase ───────────────────────────────────────────
def _carregar_conectadas_supabase():
    global _PORT_CACHE, _CONECTADAS_DATA_UPLOAD
    try:
        sb = _get_sb()
        if not sb: return False
        res = sb.table('conectadas').select('*').execute()
        if not res.data: return False
        con = pd.DataFrame(res.data)
        con['NUM_STR'] = con['NUMERO_LINHA'].fillna('').astype(str).str.strip()
        con['TEL_STR'] = con['TELEFONE_PORTADO'].fillna('').astype(str).str.strip()
        _PORT_CACHE = {
            'nome':  {**con.set_index('TEL_STR')['NOME'].to_dict(),
                       **con.set_index('NUM_STR')['NOME'].to_dict()},
            'tel':   {**con.set_index('TEL_STR')['TELEFONE_PORTADO'].to_dict(),
                       **con.set_index('NUM_STR')['TELEFONE_PORTADO'].to_dict()},
            'linha': {**con.set_index('TEL_STR')['NUMERO_LINHA'].to_dict(),
                       **con.set_index('NUM_STR')['NUMERO_LINHA'].to_dict()},
            'port':  {**con.set_index('TEL_STR')['PORTABILIDADE'].to_dict(),
                       **con.set_index('NUM_STR')['PORTABILIDADE'].to_dict()},
        }
        _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')
        print(f"[CONECTADAS] ✓ Carregado do Supabase: {len(con)} registros")
        return True
    except Exception as e:
        print(f"[CONECTADAS] Erro Supabase: {e}")
        return False

def _build_cache(con: pd.DataFrame):
    global _PORT_CACHE, _CONECTADAS_DATA_UPLOAD
    con['NUM_STR'] = con['NUMERO_LINHA'].fillna('').astype(str).str.strip()
    con['TEL_STR'] = con['TELEFONE_PORTADO'].fillna('').astype(str).str.strip()
    _PORT_CACHE = {
        'nome':  {**con.set_index('TEL_STR')['NOME'].to_dict(),
                   **con.set_index('NUM_STR')['NOME'].to_dict()},
        'tel':   {**con.set_index('TEL_STR')['TELEFONE_PORTADO'].to_dict(),
                   **con.set_index('NUM_STR')['TELEFONE_PORTADO'].to_dict()},
        'linha': {**con.set_index('TEL_STR')['NUMERO_LINHA'].to_dict(),
                   **con.set_index('NUM_STR')['NUMERO_LINHA'].to_dict()},
        'port':  {**con.set_index('TEL_STR')['PORTABILIDADE'].to_dict(),
                   **con.set_index('NUM_STR')['PORTABILIDADE'].to_dict()},
    }
    _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')

def carregar_conectadas_de_bytes(file_bytes, filename):
    """Upload manual via painel — salva no Supabase e atualiza cache."""
    global _PORT_CACHE, _CONECTADAS_DATA_UPLOAD
    try:
        import io
        engine = 'xlrd' if filename.lower().endswith('.xls') else 'openpyxl'
        con = pd.read_excel(io.BytesIO(file_bytes), engine=engine)

        # Salvar no Supabase
        sb = _get_sb()
        if sb:
            try:
                # Selecionar só colunas necessárias
                cols = ['NOME','TELEFONE_PORTADO','NUMERO_LINHA','PORTABILIDADE']
                if 'CPF' in con.columns: cols = ['CPF'] + cols
                con_save = con[[c for c in cols if c in con.columns]].copy()
                con_save = con_save.where(pd.notnull(con_save), None)
                # Limpar e recarregar
                sb.table('conectadas').delete().neq('id', 0).execute()
                records = con_save.to_dict('records')
                for i in range(0, len(records), 500):
                    sb.table('conectadas').insert(records[i:i+500]).execute()
                print(f"[CONECTADAS] ✓ Salvo no Supabase: {len(records)} registros")
            except Exception as e:
                print(f"[CONECTADAS] Erro ao salvar no Supabase: {e}")

        _build_cache(con)
        print(f"[CONECTADAS] ✓ Cache atualizado: {len(con)} registros")
        return True
    except Exception as e:
        print(f"[CONECTADAS] Erro upload: {e}")
        return False

def garantir_conectadas():
    """Garante que o cache está carregado — tenta Supabase se vazio."""
    if not _PORT_CACHE:
        _carregar_conectadas_supabase()

def _fmt_num(v):
    try:    return str(int(float(v))) if v else ''
    except: return str(v) if v else ''

PAGA_S = {'Paga','Pagamento Cartão de Crédito','Ordem Pagto','Parcelada','Em Negociação'}

MES_SAFRA = {
    'JANEIRO':1,'FEVEREIRO':2,'MARÇO':3,'ABRIL':4,'MAIO':5,'JUNHO':6,
    'JULHO':7,'AGOSTO':8,'SETEMBRO':9,'OUTUBRO':10,'NOVEMBRO':11,'DEZEMBRO':12,
}
FECHAMENTO_SAFRA = {
    'JANEIRO':'2026-04','FEVEREIRO':'2026-05','MARÇO':'2026-06','ABRIL':'2026-07',
    'MAIO':'2026-08','JUNHO':'2026-09','JULHO':'2026-10','AGOSTO':'2026-11',
    'SETEMBRO':'2026-12','OUTUBRO':'2027-01','NOVEMBRO':'2027-02','DEZEMBRO':'2027-03',
}

def calcular_etapa(dias, portin):
    if dias is None: return None
    PC = 'Portabilidade Concluida'
    if dias <= -2:           return 'Preventivo'
    if 0  <= dias <= 6:      return None
    if 7  <= dias <= 10:     return 'Etapa 1'
    if 11 <= dias <= 15:     return 'Etapa 2'
    if 16 <= dias <= 23:     return 'Etapa 3'
    if 24 <= dias <= 30:     return 'Etapa 4'
    if portin == PC:
        if 31 <= dias <= 42: return 'Etapa 5'
        if 43 <= dias <= 50: return 'Etapa 6'
        if 51 <= dias <= 62: return 'Etapa 7'
        if 63 <= dias <= 70: return 'Etapa 8'
    return None

def _status_estorno(venc, safra):
    if pd.isna(venc): return 'SEM ESTORNO'
    fech = pd.Period(FECHAMENTO_SAFRA.get(safra.upper(),'2026-06'), 'M')
    try:    p = pd.Period(venc, 'M')
    except: return 'SEM ESTORNO'
    if p <= fech - 1: return '2 FATURAS'
    if p == fech:     return '1 FATURA'
    return 'SEM ESTORNO'

def _fatura_urgente(row):
    today = date.today()
    cands = []
    for n in ['1ª','2ª']:
        st = str(row.get(f'{n} fatura - Status da fatura') or '').strip()
        if st != 'Aberta': continue
        vr = row.get(f'{n} fatura - Data de vencimento')
        try:
            if isinstance(vr, str):       venc = datetime.strptime(vr,'%d/%m/%Y').date()
            elif isinstance(vr, datetime): venc = vr.date()
            elif isinstance(vr, date):     venc = vr
            else:                          continue
        except: continue
        val_raw = str(row.get(f'{n} fatura - Preço da fatura') or '')\
                      .replace('R$','').replace(',','.').strip()
        try:    val = float(val_raw)
        except: val = None
        cands.append((venc, 1 if n=='1ª' else 2, val))
    if not cands: return None
    cands.sort()
    venc, num, val = cands[0]
    return {'num':num, 'valor':val, 'vencimento':venc, 'dias':(today-venc).days}

def processar_arquivo(uploaded_file, safra: str):
    garantir_conectadas()
    con = _PORT_CACHE

    # Ler arquivo
    name = uploaded_file.name.lower()
    if name.endswith('.csv'):
        df_raw = pd.read_csv(uploaded_file, encoding='utf-8', sep=None, engine='python')
    else:
        df_raw = pd.read_excel(uploaded_file, engine='openpyxl')

    df = df_raw.copy()
    df['Data da ativação'] = pd.to_datetime(df['Data da ativação'], format='%d/%m/%Y', errors='coerce')
    df['1ª fatura - Data de vencimento'] = pd.to_datetime(
        df['1ª fatura - Data de vencimento'], format='%d/%m/%Y', errors='coerce')

    # Regra 1: somente mês da safra
    mes_num = MES_SAFRA.get(safra.upper(), 3)
    df = df[(df['Data da ativação'].dt.month == mes_num) &
            (df['Data da ativação'].dt.year  == 2026)].copy()

    # Regra 2: venc 1ª >= mês ativação
    mask = (df['1ª fatura - Data de vencimento'].notna() &
            df['Data da ativação'].notna() &
            (df['1ª fatura - Data de vencimento'].dt.to_period('M') <
             df['Data da ativação'].dt.to_period('M')))
    df = df[~mask].copy()
    df['Status do número de acesso'] = df['Status do número de acesso'].str.strip()

    def get_port(num):
        v = con.get('port',{}).get(_fmt_num(num))
        return v if v and not (isinstance(v,float) and pd.isna(v)) else 0

    df['PORTIN'] = df['Número de acesso'].apply(get_port)
    df['STATUS ESTORNO'] = df['1ª fatura - Data de vencimento'].apply(
        lambda v: _status_estorno(v, safra))

    # Salvar safra no Supabase
    _salvar_safra_supabase(df, safra)

    # Construir controle — somente ATIVOS com fatura aberta
    rows = []
    for _, row in df.iterrows():
        status = str(row.get('Status do número de acesso') or '').strip()
        fat = _fatura_urgente(row) if status == 'Ativo' else None
        if not fat: continue

        portin = str(row.get('PORTIN') or '')
        et     = calcular_etapa(fat['dias'], portin)
        na     = _fmt_num(row.get('Número de acesso',''))
        st1    = str(row.get('1ª fatura - Status da fatura') or '').strip()
        st2    = str(row.get('2ª fatura - Status da fatura') or '').strip()
        status_pag = st1 if fat['num'] == 1 else st2

        if portin == 'Portabilidade Concluida':   port_label = 'Concluida'
        elif portin not in ('','0',0):             port_label = 'Nao Concluida'
        else:                                      port_label = ''

        rows.append({
            'SAFRA':            safra,
            'CPF':              str(row.get('Cpf','') or ''),
            'NOME':             con.get('nome',{}).get(na,''),
            'PROPOSTA':         str(row.get('Código externo','') or ''),
            'NUMERO DE ACESSO': na,
            'NUMERO PORTADO':   _fmt_num(con.get('tel',{}).get(na,'')),
            'NUMERO LINHA':     _fmt_num(con.get('linha',{}).get(na,'')),
            'STATUS ACESSO':    status,
            'FATURA':           fat['num'],
            'STATUS 1ª FATURA': st1,
            'STATUS 2ª FATURA': st2,
            'VALOR':            fat['valor'],
            'VENCIMENTO':       fat['vencimento'],
            'DIAS ATRASO':      fat['dias'],
            'PORTABILIDADE':    port_label,
            'ETAPA':            et,
            'ENVIO':            None,
            'ULTIMO ENVIO':     None,
            'STATUS PAGAMENTO': status_pag,
        })

    df_ctrl = pd.DataFrame(rows)
    resumo   = calcular_resumo_base(df, safra)
    return df_ctrl, resumo

def _salvar_safra_supabase(df: pd.DataFrame, safra: str):
    """Salva/atualiza registros da safra no Supabase."""
    try:
        sb = _get_sb()
        if not sb: return
        # Remover registros antigos desta safra e reinserir
        sb.table('safras').delete().eq('"SAFRA"', safra).execute()
        cols_map = {
            'Cpf': 'CPF',
            'Número de acesso': 'NUMERO DE ACESSO',
            'Status do número de acesso': 'STATUS DO ACESSO',
            'Data da ativação': 'DATA DA ATIVACAO',
            '1ª fatura - Status da fatura': 'STATUS 1 FATURA',
            '1ª fatura - Data de vencimento': 'VENCIMENTO 1 FATURA',
            '1ª fatura - Preço da fatura': 'VALOR 1 FATURA',
            '2ª fatura - Status da fatura': 'STATUS 2 FATURA',
            '2ª fatura - Data de vencimento': 'VENCIMENTO 2 FATURA',
            '2ª fatura - Preço da fatura': 'VALOR 2 FATURA',
            'STATUS ESTORNO': 'STATUS ESTORNO',
            'PORTIN': 'PORTIN',
        }
        df_save = df[[c for c in cols_map.keys() if c in df.columns]].rename(columns=cols_map).copy()
        df_save['SAFRA'] = safra
        # Converter datas
        for col in ['DATA DA ATIVACAO','VENCIMENTO 1 FATURA','VENCIMENTO 2 FATURA']:
            if col in df_save.columns:
                df_save[col] = pd.to_datetime(df_save[col], errors='coerce').dt.strftime('%Y-%m-%d')
        records = df_save.where(pd.notnull(df_save), None).to_dict('records')
        for i in range(0, len(records), 500):
            sb.table('safras').insert(records[i:i+500]).execute()
        print(f"[SAFRAS] ✓ {safra}: {len(records)} registros salvos")
    except Exception as e:
        print(f"[SAFRAS] Erro ao salvar: {e}")

def calcular_resumo_base(df_base: pd.DataFrame, safra: str) -> dict:
    if df_base is None or len(df_base) == 0: return _empty_resumo()
    PC = 'Portabilidade Concluida'
    ip  = lambda p: p == PC
    is_ = lambda p: p != PC
    if 'PORTIN' not in df_base.columns: return _empty_resumo()
    df_at = df_base[df_base['Status do número de acesso']=='Ativo']
    df_in = df_base[df_base['Status do número de acesso']!='Ativo']
    N=len(df_base); NA=len(df_at); NC=len(df_in)
    PF=int(df_base['PORTIN'].apply(ip).sum()); SF=int(df_base['PORTIN'].apply(is_).sum())
    PA=int(df_at['PORTIN'].apply(ip).sum()); SA=int(df_at['PORTIN'].apply(is_).sum())
    PC_=int(df_in['PORTIN'].apply(ip).sum()); SC=int(df_in['PORTIN'].apply(is_).sum())
    CATS=['SEM ESTORNO','1 FATURA PAGA','1 FATURA ABERTA','2 FATURAS - 2 PGS',
          '2 FATURAS (2 ABERTA)','2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA']
    SIM={'1 FATURA ABERTA','2 FATURAS (2 ABERTA)','2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA'}
    def sit(row):
        se=str(row.get('STATUS ESTORNO') or '')
        if se=='SEM ESTORNO': return 'SEM ESTORNO'
        s1=str(row.get('1ª fatura - Status da fatura') or '').strip()
        s2=str(row.get('2ª fatura - Status da fatura') or '').strip()
        f1p=s1 in PAGA_S; f1a=s1=='Aberta'; f2p=s2 in PAGA_S; f2a=s2=='Aberta'
        if se=='1 FATURA': return '1 FATURA ABERTA' if f1a else '1 FATURA PAGA' if f1p else 'SEM ESTORNO'
        if se=='2 FATURAS':
            if f1a and f2a: return '2 FATURAS (2 ABERTA)'
            if f1p and f2a: return '2 FATURAS (1 PAGA 2 ABERTA)'
            if f1a and f2p: return '2 FATURAS ( 1 ABERTO 2 PAGA'
            if f1p and f2p: return '2 FATURAS - 2 PGS'
            if f1p: return '1 FATURA PAGA'
            if f1a: return '1 FATURA ABERTA'
        return 'SEM ESTORNO'
    db=df_base.copy(); db['_S']=db.apply(sit,axis=1)
    da=db[db['Status do número de acesso']=='Ativo']
    rows=[]
    for cat in CATS:
        t=int((da['_S']==cat).sum()); pc=int(((da['_S']==cat)&da['PORTIN'].apply(ip)).sum())
        rows.append((cat,t,pc,t-pc))
    ET=sum(r[1] for r in rows if r[0] in SIM)+NC
    EP=sum(r[2] for r in rows if r[0] in SIM)+PC_
    ES=sum(r[3] for r in rows if r[0] in SIM)+SC
    META=0.38; MV=META*N; RV=ET-MV
    return dict(safra=safra,N=N,NA=NA,NC=NC,PF=PF,SF=SF,PA=PA,SA=SA,PC_=PC_,SC=SC,
                rows=rows,ET=ET,EP=EP,ES=ES,CT=ET,CP=EP,CS=ES,META=META,MV=MV,RV=RV)

def calcular_resumo(df):
    if df is None or len(df)==0: return _empty_resumo()
    N=len(df)
    NA=int((df['STATUS ACESSO']=='Ativo').sum()) if 'STATUS ACESSO' in df.columns else N
    NC=N-NA
    SIM_ET={'Etapa 1','Etapa 2','Etapa 3','Etapa 4','Etapa 5','Etapa 6','Etapa 7','Etapa 8','Preventivo'}
    ET=int(df['ETAPA'].isin(SIM_ET).sum())+NC if 'ETAPA' in df.columns else NC
    META=0.38; MV=META*N; RV=ET-MV
    return dict(N=N,NA=NA,NC=NC,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=ET,EP=0,ES=0,CT=ET,CP=0,CS=0,META=META,MV=MV,RV=RV)

def _empty_resumo():
    return dict(N=0,NA=0,NC=0,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=0,EP=0,ES=0,CT=0,CP=0,CS=0,META=0.38,MV=0,RV=0)
