"""
processamento.py — Lê arquivo bruto da safra, aplica filtros e regras de negócio.
"""

import pandas as pd
from datetime import date, datetime
import os
from pathlib import Path

# ── Cache do CONECTADAS ───────────────────────────────────────────────────────
_PORT_CACHE = {}
_CONECTADAS_DATA_UPLOAD = None

def get_data_upload_conectadas():
    return _CONECTADAS_DATA_UPLOAD

def _carregar_conectadas(extra_path=None):
    """
    Procura CONECTADAS.xlsx/.xls em vários locais possíveis.
    extra_path: caminho adicional passado pelo app (ex: upload manual).
    """
    global _PORT_CACHE
    if _PORT_CACHE:
        return _PORT_CACHE

    # Locais para procurar — do mais específico ao mais genérico
    candidates = []
    if extra_path:
        candidates.append(Path(extra_path))

    script_dir = Path(__file__).resolve().parent
    cwd        = Path(os.getcwd())

    for folder in [script_dir, cwd, cwd.parent]:
        for name in ['CONECTADAS.xlsx', 'CONECTADAS.xls', 'conectadas.xlsx', 'conectadas.xls']:
            candidates.append(folder / name)

    for path in candidates:
        if path.exists():
            try:
                engine = 'xlrd' if str(path).endswith('.xls') else 'openpyxl'
                con = pd.read_excel(str(path), engine=engine)
                con['NUM_STR'] = con['NUMERO_LINHA'].fillna(0).astype(int).astype(str).str.strip()
                con['TEL_STR'] = con['TELEFONE_PORTADO'].fillna(0).astype(int).astype(str).str.strip()
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
                global _CONECTADAS_DATA_UPLOAD
                from datetime import datetime
                _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')
                print(f"[CONECTADAS] ✓ Carregado: {path} ({len(con)} registros)")
                return _PORT_CACHE
            except Exception as e:
                print(f"[CONECTADAS] Erro em {path}: {e}")

    print(f"[CONECTADAS] Não encontrado. Procurei em: {[str(c) for c in candidates[:6]]}")
    return {}

def carregar_conectadas_de_bytes(file_bytes, filename):
    """Carrega CONECTADAS a partir de bytes (upload via Streamlit)."""
    global _PORT_CACHE
    try:
        import io
        engine = 'xlrd' if filename.lower().endswith('.xls') else 'openpyxl'
        con = pd.read_excel(io.BytesIO(file_bytes), engine=engine)
        con['NUM_STR'] = con['NUMERO_LINHA'].fillna(0).astype(int).astype(str).str.strip()
        con['TEL_STR'] = con['TELEFONE_PORTADO'].fillna(0).astype(int).astype(str).str.strip()
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
        global _CONECTADAS_DATA_UPLOAD
        from datetime import datetime
        _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')
        print(f"[CONECTADAS] ✓ Carregado via upload: {len(con)} registros")
        return True
    except Exception as e:
        print(f"[CONECTADAS] Erro no upload: {e}")
        return False

def conectadas_carregado():
    return bool(_PORT_CACHE)

def resetar_conectadas():
    """Limpa o cache para forçar recarregamento de uma nova versão do CONECTADAS."""
    global _PORT_CACHE
    _PORT_CACHE = {}

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
            if isinstance(vr, str):          venc = datetime.strptime(vr,'%d/%m/%Y').date()
            elif isinstance(vr, datetime):    venc = vr.date()
            elif isinstance(vr, date):        venc = vr
            else:                             continue
        except: continue
        val_raw = str(row.get(f'{n} fatura - Preço da fatura') or '') \
                      .replace('R$','').replace(',','.').strip()
        try:    val = float(val_raw)
        except: val = None
        cands.append((venc, 1 if n=='1ª' else 2, val))
    if not cands: return None
    cands.sort()
    venc, num, val = cands[0]
    return {'num':num, 'valor':val, 'vencimento':venc, 'dias':(today-venc).days}

def processar_arquivo(uploaded_file, safra: str):
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

    # PORTIN
    con = _carregar_conectadas()
    def get_port(num):
        v = con.get('port',{}).get(_fmt_num(num))
        return v if v and not (isinstance(v,float) and pd.isna(v)) else 0
    df['PORTIN'] = df['Número de acesso'].apply(get_port)

    # STATUS ESTORNO
    df['STATUS ESTORNO'] = df['1ª fatura - Data de vencimento'].apply(
        lambda v: _status_estorno(v, safra))

    # Construir controle — somente ATIVOS com fatura aberta
    rows = []
    for _, row in df.iterrows():
        status = str(row.get('Status do número de acesso') or '').strip()

        # Contabilizar cancelados no resumo mas NÃO na lista de cobrança
        fat = _fatura_urgente(row) if status == 'Ativo' else None
        if not fat: continue

        portin = str(row.get('PORTIN') or '')
        et     = calcular_etapa(fat['dias'], portin)
        na     = _fmt_num(row.get('Número de acesso',''))

        if portin == 'Portabilidade Concluida':    port_label = 'Concluida'
        elif portin not in ('','0',0):             port_label = 'Nao Concluida'
        else:                                      port_label = ''

        st1 = str(row.get('1ª fatura - Status da fatura') or '').strip()
        st2 = str(row.get('2ª fatura - Status da fatura') or '').strip()
        # Status de pagamento = status real da fatura mais urgente
        status_pag = st1 if fat['num'] == 1 else st2
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
            'STATUS 1ª FATURA': st1 or '',
            'STATUS 2ª FATURA': st2 or '',
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

    # Resumo usa df completo (inclusive cancelados)
    resumo = calcular_resumo_base(df, safra)
    return df_ctrl, resumo

def calcular_resumo_base(df_base: pd.DataFrame, safra: str) -> dict:
    """Resumo analítico a partir do dataframe bruto filtrado."""
    if df_base is None or len(df_base) == 0:
        return _empty_resumo()

    PC = 'Portabilidade Concluida'
    ip  = lambda p: p == PC
    is_ = lambda p: p != PC

    if 'PORTIN' not in df_base.columns:
        return _empty_resumo()

    df_at = df_base[df_base['Status do número de acesso'] == 'Ativo']
    df_in = df_base[df_base['Status do número de acesso'] != 'Ativo']
    N=len(df_base); NA=len(df_at); NC=len(df_in)
    PF=int(df_base['PORTIN'].apply(ip).sum()); SF=int(df_base['PORTIN'].apply(is_).sum())
    PA=int(df_at['PORTIN'].apply(ip).sum());   SA=int(df_at['PORTIN'].apply(is_).sum())
    PC_=int(df_in['PORTIN'].apply(ip).sum());  SC=int(df_in['PORTIN'].apply(is_).sum())

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

def calcular_resumo(df: pd.DataFrame) -> dict:
    """Resumo a partir do df de controle (já processado)."""
    if df is None or len(df) == 0: return _empty_resumo()
    def _p(a,b): return a/b if b else 0
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
