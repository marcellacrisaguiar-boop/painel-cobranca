"""
banco.py — Persistência do painel (local Parquet ou Supabase).
"""

import os
import pandas as pd
from datetime import date
from pathlib import Path

DATA_DIR  = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
CTRL_FILE    = DATA_DIR / 'controle.parquet'
HIST_FILE    = DATA_DIR / 'historico.parquet'
SNAPSHOT_FILE= DATA_DIR / 'snapshots.parquet'  # histórico semanal de estorno

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

_sb = None
def _get_sb():
    global _sb
    if _sb is None and USE_SUPABASE:
        from supabase import create_client
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

def _safe_read(path) -> pd.DataFrame:
    try:
        if path.exists(): return pd.read_parquet(path)
    except: pass
    return pd.DataFrame()

def _safe_write(df, path):
    try: df.to_parquet(path, index=False)
    except Exception as e: print(f"[banco] Erro {path}: {e}")

# ── CONTROLE ──────────────────────────────────────────────────────────────────
def carregar_controle() -> pd.DataFrame:
    if USE_SUPABASE:
        try:
            res = _get_sb().table('controle_envio').select('*').execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e: print(f"[Supabase] {e}")
    return _safe_read(CTRL_FILE)

def salvar_controle(df: pd.DataFrame):
    if USE_SUPABASE:
        try:
            records = df.where(pd.notnull(df), None).to_dict('records')
            _get_sb().table('controle_envio').upsert(
                records, on_conflict='NUMERO DE ACESSO,FATURA,SAFRA').execute()
            return
        except Exception as e: print(f"[Supabase] {e}")
    _safe_write(df, CTRL_FILE)

# ── HISTÓRICO DE PAGAMENTOS ───────────────────────────────────────────────────
def carregar_historico() -> pd.DataFrame:
    if USE_SUPABASE:
        try:
            res = _get_sb().table('historico_pagamentos').select('*').execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e: print(f"[Supabase] {e}")
    return _safe_read(HIST_FILE)

def salvar_historico(df: pd.DataFrame):
    if USE_SUPABASE:
        try:
            _get_sb().table('historico_pagamentos').upsert(
                df.where(pd.notnull(df), None).to_dict('records')).execute()
            return
        except Exception as e: print(f"[Supabase] {e}")
    _safe_write(df, HIST_FILE)

# ── SNAPSHOTS DE ESTORNO (controle semanal) ────────────────────────────────────
def carregar_snapshots() -> pd.DataFrame:
    return _safe_read(SNAPSHOT_FILE)

def salvar_snapshot(safra: str, gross: int, estorno: int, pagamentos: int, data=None):
    """
    Registra um snapshot de estorno a cada atualização de arquivo.
    Permite calcular variação % semana a semana.
    """
    snap = carregar_snapshots()
    novo = pd.DataFrame([{
        'DATA':       data or date.today(),
        'SAFRA':      safra,
        'GROSS':      gross,
        'ESTORNO':    estorno,
        'PAGAMENTOS': pagamentos,
        'PCT_ESTORNO': round(estorno / gross * 100, 2) if gross else 0,
    }])
    snap = pd.concat([snap, novo], ignore_index=True)
    _safe_write(snap, SNAPSHOT_FILE)
    return snap

# ── ATUALIZAÇÃO ───────────────────────────────────────────────────────────────
def atualizar_banco(df_ctrl_atual: pd.DataFrame,
                    df_novo: pd.DataFrame,
                    safra: str) -> tuple[pd.DataFrame, pd.DataFrame]:

    HIST_COLS = ['ENVIO', 'ULTIMO ENVIO', 'STATUS PAGAMENTO']
    KEY_COLS  = ['NUMERO DE ACESSO', 'FATURA']
    COLS_OBRIGATORIAS = KEY_COLS + HIST_COLS + ['SAFRA']

    # Garantir colunas no df_novo
    for c in COLS_OBRIGATORIAS:
        if c not in df_novo.columns:
            df_novo[c] = None

    # Sem histórico anterior — primeira carga
    if df_ctrl_atual is None or len(df_ctrl_atual) == 0:
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    # Detectar controle corrompido (colunas faltando) — resetar automaticamente
    cols_faltando = [c for c in COLS_OBRIGATORIAS if c not in df_ctrl_atual.columns]
    if cols_faltando:
        print(f"[banco] Controle corrompido — colunas faltando: {cols_faltando}. Resetando.")
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    df_outras = df_ctrl_atual[df_ctrl_atual['SAFRA'] != safra].copy()
    df_safra  = df_ctrl_atual[df_ctrl_atual['SAFRA'] == safra].copy()

    # Safra ainda não existia no controle — primeira vez que sobe essa safra
    if len(df_safra) == 0:
        df_final = pd.concat([df_outras, df_novo], ignore_index=True)
        salvar_controle(df_final)
        return df_final, pd.DataFrame()

    # Garantir colunas no controle existente
    for c in KEY_COLS + HIST_COLS:
        if c not in df_safra.columns:
            df_safra[c] = None

    ctrl_idx = set(zip(df_safra['NUMERO DE ACESSO'].fillna('').astype(str),
                       df_safra['FATURA'].fillna('').astype(str)))
    novo_idx  = set(zip(df_novo['NUMERO DE ACESSO'].fillna('').astype(str),
                        df_novo['FATURA'].fillna('').astype(str)))

    # Quem pagou (estava no ctrl, sumiu do novo)
    pagaram_keys = ctrl_idx - novo_idx
    df_pagaram = df_safra[
        df_safra.apply(
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

    # Preservar histórico de envios para quem continua em aberto
    cols_preservar = [c for c in KEY_COLS + HIST_COLS if c in df_safra.columns]
    df_preservado  = df_safra[
        df_safra.apply(
            lambda r: (str(r.get('NUMERO DE ACESSO','')), str(r.get('FATURA',''))) in novo_idx,
            axis=1)][cols_preservar].copy()

    if len(df_preservado) > 0:
        df_merged = df_novo.merge(
            df_preservado.rename(columns={c: c+'_OLD' for c in HIST_COLS if c in df_preservado.columns}),
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

# ── Registrar bloqueio (cliente clicou em BLOQUEAR no WhatsApp) ──────────────
def registrar_bloqueio(telefone_portado: str) -> bool:
    """
    Marca o cliente como BLOQUEADO pelo TELEFONE_PORTADO.
    Cliente sai dos envios do dia automaticamente.
    Retorna True se encontrou e atualizou, False se não encontrou.
    """
    df = carregar_controle()
    if df is None or len(df) == 0:
        return False

    # Buscar por NUMERO PORTADO
    tel = str(telefone_portado).strip()
    mask = df['NUMERO PORTADO'].astype(str).str.strip() == tel

    if not mask.any():
        return False

    df.loc[mask, 'STATUS PAGAMENTO'] = 'BLOQUEADO'
    df.loc[mask, 'ETAPA']            = None   # sai do funil
    salvar_controle(df)
    return True

# ── Registrar envio ───────────────────────────────────────────────────────────
def registrar_envio(numero_acesso: str, etapa: str, tipo: str, data_envio: date):
    df = carregar_controle()
    if df is None or len(df) == 0: return
    mask = df['NUMERO DE ACESSO'].astype(str) == str(numero_acesso)
    df.loc[mask, 'ENVIO']        = data_envio
    df.loc[mask, 'ULTIMO ENVIO'] = data_envio
    salvar_controle(df)
