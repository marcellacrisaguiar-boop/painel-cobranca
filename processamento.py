"""
processamento.py — Lê arquivo bruto da safra, aplica filtros e regras.
CONECTADAS carregado do Supabase automaticamente.
"""

import os
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Cache global ──────────────────────────────────────────────────────────────
_PORT_CACHE = {}
_CONECTADAS_DATA_UPLOAD = None

def get_data_upload_conectadas():
    return _CONECTADAS_DATA_UPLOAD

def conectadas_carregado():
    return bool(_PORT_CACHE)

def _get_sb():
    try:
        from supabase import create_client
        url = os.getenv('SUPABASE_URL', '')
        key = os.getenv('SUPABASE_KEY', '')
        if not url or not key: return None
        return create_client(url, key)
    except Exception as e:
        print(f"[Supabase] Erro ao conectar: {e}")
        return None

# ── Normalizar número ─────────────────────────────────────────────────────────
def _fmt_num(v):
    if v is None or v == '': return ''
    s = str(v).strip().replace(' ','').replace('-','').replace('(','').replace(')','')
    if s.endswith('.0'): s = s[:-2]
    try:    return str(int(float(s))) if s else ''
    except: return s

# ── Montar cache CONECTADAS ───────────────────────────────────────────────────
def _build_cache(con: pd.DataFrame):
    global _PORT_CACHE, _CONECTADAS_DATA_UPLOAD
    con = con.copy()
    con['NUM_STR'] = con['NUMERO_LINHA'].apply(_fmt_num)
    con['TEL_STR'] = con['TELEFONE_PORTADO'].apply(_fmt_num)

    mask_num = con['NUM_STR'] != ''
    mask_tel = con['TEL_STR'] != ''

    d_nome  = con[mask_num].set_index('NUM_STR')['NOME'].to_dict()
    d_tel   = con[mask_num].set_index('NUM_STR')['TELEFONE_PORTADO'].apply(_fmt_num).to_dict()
    d_linha = con[mask_num].set_index('NUM_STR')['NUMERO_LINHA'].apply(_fmt_num).to_dict()
    d_port  = con[mask_num].set_index('NUM_STR')['PORTABILIDADE'].to_dict()

    d_nome.update( con[mask_tel].set_index('TEL_STR')['NOME'].to_dict())
    d_tel.update(  con[mask_tel].set_index('TEL_STR')['TELEFONE_PORTADO'].apply(_fmt_num).to_dict())
    d_linha.update(con[mask_tel].set_index('TEL_STR')['NUMERO_LINHA'].apply(_fmt_num).to_dict())
    d_port.update( con[mask_tel].set_index('TEL_STR')['PORTABILIDADE'].to_dict())

    _PORT_CACHE = {'nome': d_nome, 'tel': d_tel, 'linha': d_linha, 'port': d_port}
    _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')
    print(f"[CONECTADAS] Cache: {len(d_nome)} entradas")

def _carregar_conectadas_supabase():
    global _PORT_CACHE
    try:
        sb = _get_sb()
        if not sb: return False
        todos = []
        offset = 0
        while True:
            res = sb.table('conectadas').select(
                'NOME,TELEFONE_PORTADO,NUMERO_LINHA,PORTABILIDADE'
            ).range(offset, offset+999).execute()
            if not res.data: break
            todos.extend(res.data)
            if len(res.data) < 1000: break
            offset += 1000
        if not todos: return False
        _build_cache(pd.DataFrame(todos))
        print(f"[CONECTADAS] ✓ Supabase: {len(todos)} registros")
        return True
    except Exception as e:
        print(f"[CONECTADAS] Erro: {e}")
        return False

def garantir_conectadas():
    if not _PORT_CACHE:
        _carregar_conectadas_supabase()

# ── Constantes ────────────────────────────────────────────────────────────────
PAGA_S = {'Paga','Pagamento Cartão de Crédito','Ordem Pagto','Parcelada','Em Negociação'}

MES_SAFRA = {
    'JANEIRO':1,'FEVEREIRO':2,'MARÇO':3,'ABRIL':4,'MAIO':5,'JUNHO':6,
    'JULHO':7,'AGOSTO':8,'SETEMBRO':9,'OUTUBRO':10,'NOVEMBRO':11,'DEZEMBRO':12,
}

# Fechamento = 3 meses após a safra
FECHAMENTO_SAFRA = {
    'JANEIRO':'2026-04','FEVEREIRO':'2026-05','MARÇO':'2026-06','ABRIL':'2026-07',
    'MAIO':'2026-08','JUNHO':'2026-09','JULHO':'2026-10','AGOSTO':'2026-11',
    'SETEMBRO':'2026-12','OUTUBRO':'2027-01','NOVEMBRO':'2027-02','DEZEMBRO':'2027-03',
}

# ── STATUS ESTORNO pelo vencimento da 1ª fatura ───────────────────────────────
def _status_estorno(venc_1a, safra):
    """
    Fechamento = 3 meses após safra.
    - Venc <= fechamento - 2 → 2 FATURAS
    - Venc == fechamento - 1 → 1 FATURA
    - Venc >= fechamento     → SEM ESTORNO
    - Datas corrompidas (< 2026) → SEM ESTORNO
    """
    if venc_1a is None or (isinstance(venc_1a, float) and pd.isna(venc_1a)):
        return 'SEM ESTORNO'
    try:
        fech = pd.Period(FECHAMENTO_SAFRA.get(safra.upper(), '2026-06'), 'M')
        p    = pd.Period(venc_1a, 'M')
        if p.year < 2026:        return 'SEM ESTORNO'  # data corrompida
        if p <= fech - 2:        return '2 FATURAS'
        if p == fech - 1:        return '1 FATURA'
        return 'SEM ESTORNO'
    except:
        return 'SEM ESTORNO'

# ── Calcular etapa pelo dias de atraso ────────────────────────────────────────
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

# ── Fatura mais urgente aberta ────────────────────────────────────────────────
def _fatura_urgente(row):
    today = date.today()
    cands = []
    for n in ['1ª','2ª']:
        st = str(row.get(f'{n} fatura - Status da fatura') or '').strip()
        if st != 'Aberta': continue
        vr = row.get(f'{n} fatura - Data de vencimento')
        try:
            if isinstance(vr, str):        venc = datetime.strptime(vr,'%d/%m/%Y').date()
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

# ── Processar arquivo de safra ────────────────────────────────────────────────
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

    # Parse data de ativação
    df['Data da ativação'] = pd.to_datetime(
        df['Data da ativação'], format='%d/%m/%Y', errors='coerce')

    # ── FILTRO 1: somente mês E ano exatos da safra ───────────────────────────
    mes_num = MES_SAFRA.get(safra.upper(), 3)
    df = df[
        (df['Data da ativação'].dt.month == mes_num) &
        (df['Data da ativação'].dt.year  == 2026)
    ].copy()

    # Parse vencimentos
    df['1ª fatura - Data de vencimento'] = pd.to_datetime(
        df['1ª fatura - Data de vencimento'], format='%d/%m/%Y', errors='coerce')
    df['2ª fatura - Data de vencimento'] = pd.to_datetime(
        df['2ª fatura - Data de vencimento'], format='%d/%m/%Y', errors='coerce')

    # ── FILTRO 2: venc 1ª >= mês de ativação ─────────────────────────────────
    mask = (df['1ª fatura - Data de vencimento'].notna() &
            df['Data da ativação'].notna() &
            (df['1ª fatura - Data de vencimento'].dt.to_period('M') <
             df['Data da ativação'].dt.to_period('M')))
    df = df[~mask].copy()

    df['Status do número de acesso'] = df['Status do número de acesso'].str.strip()

    # PORTIN via CONECTADAS
    def get_port(num):
        na_ = _fmt_num(num)
        v = con.get('port',{}).get(na_)
        if not v or (isinstance(v, float) and pd.isna(v)):
            tel_ = con.get('tel',{}).get(na_,'')
            v = con.get('port',{}).get(tel_) if tel_ else None
        return v if v and not (isinstance(v, float) and pd.isna(v)) else 0

    df['PORTIN'] = df['Número de acesso'].apply(get_port)

    # STATUS ESTORNO — sempre calculado pelo painel
    df['STATUS ESTORNO'] = df['1ª fatura - Data de vencimento'].apply(
        lambda v: _status_estorno(v, safra))

    # Salvar safra no Supabase (cliente por cliente)
    linhas_con = len(con.get('nome', {})) // 2 if con else 0
    _salvar_safra_supabase(df, safra, linhas_con)

    # ── Construir controle — somente ATIVOS com fatura aberta ─────────────────
    rows = []
    for _, row in df.iterrows():
        status = str(row.get('Status do número de acesso') or '').strip()
        fat = _fatura_urgente(row) if status == 'Ativo' else None
        if not fat: continue

        portin = str(row.get('PORTIN') or '')
        et  = calcular_etapa(fat['dias'], portin)
        na  = _fmt_num(row.get('Número de acesso',''))
        st1 = str(row.get('1ª fatura - Status da fatura') or '').strip()
        st2 = str(row.get('2ª fatura - Status da fatura') or '').strip()

        nome_con  = con.get('nome',{}).get(na,'')
        tel_port  = _fmt_num(con.get('tel',{}).get(na,''))
        num_linha = _fmt_num(con.get('linha',{}).get(na,''))

        if portin == 'Portabilidade Concluida':  port_label = 'Concluida'
        elif portin not in ('','0',0):            port_label = 'Nao Concluida'
        else:                                     port_label = ''

        rows.append({
            'SAFRA':            safra,
            'CPF':              str(row.get('Cpf','') or ''),
            'NOME':             nome_con,
            'PROPOSTA':         str(row.get('Código externo','') or ''),
            'NUMERO DE ACESSO': na,
            'NUMERO PORTADO':   tel_port,
            'NUMERO LINHA':     num_linha,
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
            'STATUS PAGAMENTO': st1 if fat['num'] == 1 else st2,
        })

    df_ctrl = pd.DataFrame(rows)
    resumo  = calcular_resumo_base(df, safra)

    achou = sum(1 for r in rows if r['NOME'])
    print(f"[CRUZAMENTO] {safra}: {achou}/{len(rows)} ({achou/len(rows):.0%}) com nome") if rows else None

    return df_ctrl, resumo

# ── Salvar safra no Supabase (cliente por cliente, substitui) ─────────────────
def _salvar_safra_supabase(df: pd.DataFrame, safra: str, linhas_conectadas: int = 0):
    try:
        sb = _get_sb()
        if not sb: return
        faturas_enc = len(df)
        cobertura   = round(faturas_enc / linhas_conectadas * 100, 1) if linhas_conectadas else 0

        # Substituir registros da safra
        sb.table('safras').delete().eq('SAFRA', safra).execute()

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
        df_save = df[[c for c in cols_map if c in df.columns]].rename(columns=cols_map).copy()
        df_save['SAFRA']               = safra
        df_save['LINHAS_CONECTADAS']   = linhas_conectadas
        df_save['FATURAS_ENCONTRADAS'] = faturas_enc
        df_save['COBERTURA_PCT']       = cobertura

        for col in ['DATA DA ATIVACAO','VENCIMENTO 1 FATURA','VENCIMENTO 2 FATURA']:
            if col in df_save.columns:
                df_save[col] = pd.to_datetime(df_save[col], errors='coerce').dt.strftime('%Y-%m-%d')

        records = df_save.where(pd.notnull(df_save), None).to_dict('records')
        for i in range(0, len(records), 500):
            sb.table('safras').insert(records[i:i+500]).execute()
        print(f"[SAFRAS] ✓ {safra}: {faturas_enc} registros | cobertura {cobertura}%")
    except Exception as e:
        print(f"[SAFRAS] Erro: {e}")

# ── Resumo analítico ──────────────────────────────────────────────────────────
def calcular_resumo_base(df_base: pd.DataFrame, safra: str) -> dict:
    if df_base is None or len(df_base) == 0: return _empty_resumo()
    PC  = 'Portabilidade Concluida'
    ip  = lambda p: p == PC
    is_ = lambda p: p != PC
    if 'PORTIN' not in df_base.columns: return _empty_resumo()

    df_at = df_base[df_base['Status do número de acesso'] == 'Ativo']
    df_in = df_base[df_base['Status do número de acesso'] != 'Ativo']
    N=len(df_base); NA=len(df_at); NC=len(df_in)
    PF=int(df_base['PORTIN'].apply(ip).sum()); SF=int(df_base['PORTIN'].apply(is_).sum())
    PA=int(df_at['PORTIN'].apply(ip).sum());   SA=int(df_at['PORTIN'].apply(is_).sum())
    PC_=int(df_in['PORTIN'].apply(ip).sum());  SC=int(df_in['PORTIN'].apply(is_).sum())

    CATS = ['SEM ESTORNO','1 FATURA PAGA','1 FATURA ABERTA','2 FATURAS - 2 PGS',
            '2 FATURAS (2 ABERTA)','2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA']
    SIM  = {'1 FATURA ABERTA','2 FATURAS (2 ABERTA)',
            '2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA'}

    def sit(row):
        se = str(row.get('STATUS ESTORNO') or '').strip()
        s1 = str(row.get('1ª fatura - Status da fatura') or '').strip()
        s2 = str(row.get('2ª fatura - Status da fatura') or '').strip()
        f1p=s1 in PAGA_S; f1a=s1=='Aberta'; f2p=s2 in PAGA_S; f2a=s2=='Aberta'
        if se == 'SEM ESTORNO': return 'SEM ESTORNO'
        if se == '1 FATURA':
            if f1a: return '1 FATURA ABERTA'
            if f1p: return '1 FATURA PAGA'
            return 'SEM ESTORNO'
        if se == '2 FATURAS':
            if f1a and f2a: return '2 FATURAS (2 ABERTA)'
            if f1p and f2a: return '2 FATURAS (1 PAGA 2 ABERTA)'
            if f1a and f2p: return '2 FATURAS ( 1 ABERTO 2 PAGA'
            if f1p and f2p: return '2 FATURAS - 2 PGS'
            if f1p: return '1 FATURA PAGA'
            if f1a: return '1 FATURA ABERTA'
        return 'SEM ESTORNO'

    db = df_base.copy()
    db['_S'] = db.apply(sit, axis=1)
    da = db[db['Status do número de acesso'] == 'Ativo']

    rows_r = []
    for cat in CATS:
        t  = int((da['_S'] == cat).sum())
        pc = int(((da['_S'] == cat) & da['PORTIN'].apply(ip)).sum())
        rows_r.append((cat, t, pc, t-pc))

    ET=sum(r[1] for r in rows_r if r[0] in SIM)+NC
    EP=sum(r[2] for r in rows_r if r[0] in SIM)+PC_
    ES=sum(r[3] for r in rows_r if r[0] in SIM)+SC
    META=0.38; MV=META*N; RV=ET-MV

    return dict(safra=safra,N=N,NA=NA,NC=NC,PF=PF,SF=SF,PA=PA,SA=SA,PC_=PC_,SC=SC,
                rows=rows_r,ET=ET,EP=EP,ES=ES,CT=ET,CP=EP,CS=ES,META=META,MV=MV,RV=RV)

def calcular_resumo(df):
    if df is None or len(df) == 0: return _empty_resumo()
    N  = len(df)
    NA = int((df['STATUS ACESSO']=='Ativo').sum()) if 'STATUS ACESSO' in df.columns else N
    NC = N - NA
    SIM_ET = {'Etapa 1','Etapa 2','Etapa 3','Etapa 4',
              'Etapa 5','Etapa 6','Etapa 7','Etapa 8','Preventivo'}
    ET = int(df['ETAPA'].isin(SIM_ET).sum()) + NC if 'ETAPA' in df.columns else NC
    META=0.38; MV=META*N; RV=ET-MV
    return dict(N=N,NA=NA,NC=NC,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=ET,EP=0,ES=0,CT=ET,CP=0,CS=0,META=META,MV=MV,RV=RV)

def _empty_resumo():
    return dict(N=0,NA=0,NC=0,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=0,EP=0,ES=0,CT=0,CP=0,CS=0,META=0.38,MV=0,RV=0)
