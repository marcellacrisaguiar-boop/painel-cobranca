"""
banco.py — Persistência via Supabase com fallback local.
"""

import os
import pandas as pd
from datetime import date
from pathlib import Path

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

DATA_DIR  = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
CTRL_FILE = DATA_DIR / 'controle.parquet'
HIST_FILE = DATA_DIR / 'historico.parquet'
SNAP_FILE = DATA_DIR / 'snapshots.parquet'
ENVI_FILE = DATA_DIR / 'historico_envios.parquet'

_sb = None
def _get_sb():
    global _sb
    if _sb is None and SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

def _safe_read(path):
    try:
        if path.exists(): return pd.read_parquet(path)
    except: pass
    return pd.DataFrame()

def _safe_write(df, path):
    try: df.to_parquet(path, index=False)
    except Exception as e: print(f"[local] {e}")

def _date_str(v):
    if isinstance(v, date): return v.strftime('%Y-%m-%d')
    return v

def _clean(df):
    """Converte datas para string antes de enviar ao Supabase."""
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].apply(lambda v: _date_str(v) if isinstance(v, date) else v)
    return df.where(pd.notnull(df), None)

# ── CONTROLE ──────────────────────────────────────────────────────────────────
def carregar_controle() -> pd.DataFrame:
    try:
        sb = _get_sb()
        if not sb: return _safe_read(CTRL_FILE)
        todos = []
        offset = 0
        while True:
            res = sb.table('controle_envio').select('*').range(offset, offset+999).execute()
            if not res.data: break
            todos.extend(res.data)
            if len(res.data) < 1000: break
            offset += 1000
        df = pd.DataFrame(todos)
        if len(df) > 0 and 'id' in df.columns: df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_controle: {e}")
        return _safe_read(CTRL_FILE)

def salvar_controle(df: pd.DataFrame):
    try:
        sb = _get_sb()
        if not sb: return _safe_write(df, CTRL_FILE)
        sb.table('controle_envio').delete().neq('id', 0).execute()
        if len(df) == 0: return
        records = _clean(df).to_dict('records')
        for i in range(0, len(records), 500):
            sb.table('controle_envio').insert(records[i:i+500]).execute()
        _safe_write(df, CTRL_FILE)
    except Exception as e:
        print(f"[Supabase] salvar_controle: {e}")
        _safe_write(df, CTRL_FILE)

# ── HISTÓRICO DE PAGAMENTOS ───────────────────────────────────────────────────
def carregar_historico() -> pd.DataFrame:
    try:
        sb = _get_sb()
        if not sb: return _safe_read(HIST_FILE)
        res = _get_sb().table('historico_pagamentos').select('*').execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if len(df) > 0 and 'id' in df.columns: df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_historico: {e}")
        return _safe_read(HIST_FILE)

def salvar_historico(df: pd.DataFrame):
    try:
        sb = _get_sb()
        if not sb: return _safe_write(df, HIST_FILE)
        sb.table('historico_pagamentos').delete().neq('id', 0).execute()
        if len(df) == 0: return
        records = _clean(df).to_dict('records')
        for i in range(0, len(records), 500):
            sb.table('historico_pagamentos').insert(records[i:i+500]).execute()
        _safe_write(df, HIST_FILE)
    except Exception as e:
        print(f"[Supabase] salvar_historico: {e}")
        _safe_write(df, HIST_FILE)

# ── SNAPSHOTS ─────────────────────────────────────────────────────────────────
def carregar_snapshots() -> pd.DataFrame:
    try:
        sb = _get_sb()
        if not sb: return _safe_read(SNAP_FILE)
        res = sb.table('snapshots_estorno').select('*').order('DATA').execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if len(df) > 0 and 'id' in df.columns: df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_snapshots: {e}")
        return _safe_read(SNAP_FILE)

def salvar_snapshot(safra, gross, estorno, pagamentos, data=None):
    hoje = data or date.today()
    novo = {'DATA': hoje.strftime('%Y-%m-%d'), 'SAFRA': safra,
            'GROSS': int(gross), 'ESTORNO': int(estorno),
            'PAGAMENTOS': int(pagamentos),
            'PCT_ESTORNO': round(estorno/gross*100, 2) if gross else 0}
    try:
        sb = _get_sb()
        if sb: sb.table('snapshots_estorno').insert(novo).execute()
    except Exception as e:
        print(f"[Supabase] salvar_snapshot: {e}")
    snap = carregar_snapshots()
    _safe_write(snap, SNAP_FILE)
    return snap

# ── HISTÓRICO DE ENVIOS ───────────────────────────────────────────────────────
def carregar_historico_envios() -> pd.DataFrame:
    try:
        sb = _get_sb()
        if not sb: return _safe_read(ENVI_FILE)
        todos = []
        offset = 0
        while True:
            res = sb.table('historico_envios').select('*').range(offset, offset+999).execute()
            if not res.data: break
            todos.extend(res.data)
            if len(res.data) < 1000: break
            offset += 1000
        df = pd.DataFrame(todos) if todos else pd.DataFrame()
        if len(df) > 0 and 'id' in df.columns: df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_historico_envios: {e}")
        return _safe_read(ENVI_FILE)

def registrar_envios_historico(df_enviados: pd.DataFrame, etapa: str, data_envio: date):
    """
    Atualiza historico_envios — uma linha por cliente, coluna por etapa.
    Cria linha se não existir, atualiza coluna da etapa se já existir.
    """
    if df_enviados is None or len(df_enviados) == 0: return

    col_etapa = etapa  # ex: 'Preventivo', 'Etapa 1', etc.
    data_str  = data_envio.strftime('%Y-%m-%d')

    try:
        sb = _get_sb()
        if not sb:
            _registrar_envios_local(df_enviados, etapa, data_envio)
            return

        for _, row in df_enviados.iterrows():
            cpf   = str(row.get('CPF','') or '')
            safra = str(row.get('SAFRA','') or '')
            if not cpf or not safra: continue

            # Verificar se já existe linha para este CPF+SAFRA
            res = sb.table('historico_envios')\
                    .select('id')\
                    .eq('"CPF"', cpf)\
                    .eq('"SAFRA"', safra)\
                    .execute()

            record = {
                '"CPF"':            cpf,
                '"NOME"':           str(row.get('NOME','') or ''),
                '"NUMERO PORTADO"': str(row.get('NUMERO PORTADO','') or ''),
                '"NUMERO LINHA"':   str(row.get('NUMERO LINHA','') or ''),
                '"SAFRA"':          safra,
                '"PORTABILIDADE"':  str(row.get('PORTABILIDADE','') or ''),
                f'"{col_etapa}"':   data_str,
            }

            if res.data:
                # Atualizar linha existente — só a coluna da etapa
                sb.table('historico_envios')\
                  .update({f'"{col_etapa}"': data_str})\
                  .eq('"CPF"', cpf).eq('"SAFRA"', safra).execute()
            else:
                # Inserir nova linha
                sb.table('historico_envios').insert({
                    'CPF': cpf,
                    'NOME': str(row.get('NOME','') or ''),
                    'NUMERO PORTADO': str(row.get('NUMERO PORTADO','') or ''),
                    'NUMERO LINHA': str(row.get('NUMERO LINHA','') or ''),
                    'SAFRA': safra,
                    'PORTABILIDADE': str(row.get('PORTABILIDADE','') or ''),
                    col_etapa: data_str,
                }).execute()

        print(f"[ENVIOS] ✓ {len(df_enviados)} registros salvos — {etapa}")
    except Exception as e:
        print(f"[Supabase] registrar_envios_historico: {e}")
        _registrar_envios_local(df_enviados, etapa, data_envio)

def _registrar_envios_local(df_enviados, etapa, data_envio):
    """Fallback local para histórico de envios."""
    df_hist = _safe_read(ENVI_FILE)
    data_str = data_envio.strftime('%d/%m/%Y')
    rows = []
    for _, row in df_enviados.iterrows():
        cpf   = str(row.get('CPF','') or '')
        safra = str(row.get('SAFRA','') or '')
        if not cpf: continue
        existing = df_hist[
            (df_hist['CPF'].astype(str) == cpf) &
            (df_hist['SAFRA'].astype(str) == safra)
        ] if len(df_hist) > 0 and 'CPF' in df_hist.columns else pd.DataFrame()

        if len(existing) > 0:
            df_hist.loc[existing.index[0], etapa] = data_str
        else:
            new_row = {
                'CPF': cpf, 'NOME': str(row.get('NOME','') or ''),
                'NUMERO PORTADO': str(row.get('NUMERO PORTADO','') or ''),
                'NUMERO LINHA': str(row.get('NUMERO LINHA','') or ''),
                'SAFRA': safra,
                'PORTABILIDADE': str(row.get('PORTABILIDADE','') or ''),
                etapa: data_str,
            }
            rows.append(new_row)

    if rows:
        df_hist = pd.concat([df_hist, pd.DataFrame(rows)], ignore_index=True)
    _safe_write(df_hist, ENVI_FILE)

# ── ATUALIZAÇÃO ───────────────────────────────────────────────────────────────
def atualizar_banco(df_ctrl_atual, df_novo, safra):
    HIST_COLS = ['ENVIO','ULTIMO ENVIO','STATUS PAGAMENTO']
    KEY_COLS  = ['NUMERO DE ACESSO','FATURA']
    OBRIG     = KEY_COLS + HIST_COLS + ['SAFRA']

    for c in OBRIG:
        if c not in df_novo.columns: df_novo[c] = None

    if df_ctrl_atual is None or len(df_ctrl_atual) == 0:
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    cols_faltando = [c for c in OBRIG if c not in df_ctrl_atual.columns]
    if cols_faltando:
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    df_outras = df_ctrl_atual[df_ctrl_atual['SAFRA'] != safra].copy()
    df_safra  = df_ctrl_atual[df_ctrl_atual['SAFRA'] == safra].copy()

    for c in HIST_COLS:
        if c not in df_safra.columns: df_safra[c] = None

    if len(df_safra) == 0:
        df_final = pd.concat([df_outras, df_novo], ignore_index=True)
        salvar_controle(df_final)
        return df_final, pd.DataFrame()

    ctrl_idx = set(zip(df_safra['NUMERO DE ACESSO'].fillna('').astype(str),
                       df_safra['FATURA'].fillna('').astype(str)))
    novo_idx  = set(zip(df_novo['NUMERO DE ACESSO'].fillna('').astype(str),
                        df_novo['FATURA'].fillna('').astype(str)))

    # Quem pagou
    pagaram_keys = ctrl_idx - novo_idx
    df_pagaram = df_safra[df_safra.apply(
        lambda r: (str(r.get('NUMERO DE ACESSO','')), str(r.get('FATURA',''))) in pagaram_keys,
        axis=1)].copy()

    df_hist_new = pd.DataFrame()
    if len(df_pagaram) > 0:
        hoje = date.today()
        keep = ['SAFRA','CPF','NOME','NUMERO DE ACESSO','NUMERO PORTADO',
                'FATURA','VALOR','VENCIMENTO','PORTABILIDADE','ETAPA']
        df_hist_new = df_pagaram[[c for c in keep if c in df_pagaram.columns]].copy()
        df_hist_new.rename(columns={'ETAPA':'ETAPA NO PAGAMENTO'}, inplace=True)
        df_hist_new['DATA PAGAMENTO']     = hoje
        df_hist_new['DIAS ATÉ PAGAMENTO'] = df_hist_new['VENCIMENTO'].apply(
            lambda v: (hoje - v).days if isinstance(v, date) else None)

    # Preservar histórico de envios
    cols_pres = [c for c in KEY_COLS + HIST_COLS if c in df_safra.columns]
    df_pres = df_safra[df_safra.apply(
        lambda r: (str(r.get('NUMERO DE ACESSO','')), str(r.get('FATURA',''))) in novo_idx,
        axis=1)][cols_pres].copy()

    if len(df_pres) > 0:
        df_merged = df_novo.merge(
            df_pres.rename(columns={c: c+'_OLD' for c in HIST_COLS if c in df_pres.columns}),
            on=KEY_COLS, how='left')
        for col in HIST_COLS:
            old_col = col + '_OLD'
            if old_col in df_merged.columns:
                df_merged[col] = df_merged[old_col].combine_first(df_merged[col])
                df_merged.drop(columns=[old_col], inplace=True)
    else:
        df_merged = df_novo.copy()

    df_final = pd.concat([df_outras, df_merged], ignore_index=True)
    salvar_controle(df_final)

    if len(df_hist_new) > 0:
        hist = carregar_historico()
        salvar_historico(pd.concat([hist, df_hist_new], ignore_index=True))

    return df_final, df_hist_new

# ── Registrar bloqueio ────────────────────────────────────────────────────────
def registrar_bloqueio(telefone_portado: str) -> bool:
    df = carregar_controle()
    if df is None or len(df) == 0: return False
    tel  = str(telefone_portado).strip()
    mask = df['NUMERO PORTADO'].astype(str).str.strip() == tel
    if not mask.any(): return False
    df.loc[mask, 'STATUS PAGAMENTO'] = 'BLOQUEADO'
    df.loc[mask, 'ETAPA']            = None
    salvar_controle(df)
    return True

# ── Registrar envio manual ────────────────────────────────────────────────────
def registrar_envio(numero_acesso: str, etapa: str, tipo: str, data_envio: date):
    df = carregar_controle()
    if df is None or len(df) == 0: return
    mask = df['NUMERO DE ACESSO'].astype(str) == str(numero_acesso)
    df.loc[mask, 'ENVIO']        = data_envio
    df.loc[mask, 'ULTIMO ENVIO'] = data_envio
    salvar_controle(df)
