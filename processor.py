from __future__ import annotations

import io
import re
import unicodedata
from typing import Dict, List, Tuple, Optional

import pandas as pd


# ========== I/O ==========

def _read_all_sheets_from_bytes(b: bytes) -> Dict[str, pd.DataFrame]:
    """Read ALL sheets from Excel bytes -> {sheet_name: DataFrame}."""
    return pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")


def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    """If first row looks like headers, promote it to header."""
    if df.empty:
        return df
    try:
        first = df.iloc[0].astype(str).str.strip().str.lower()
        if (first != "").mean() >= 0.5 and len(set(first)) == len(first):
            out = df.iloc[1:].copy()
            out.columns = list(df.iloc[0])
            return out
    except Exception:
        pass
    return df


# ========== Text utils ==========

def _clean_series(s: pd.Series) -> pd.Series:
    s = s.astype(object)
    s = s.where(~pd.isna(s), "")
    s = s.replace({"nan": "", "None": "", None: ""})
    return s.astype(str)


def _norm(s: str) -> str:
    """Unicode-safe normalization (не ломаем грузинский/русский)."""
    if s is None:
        s = ""
    s = unicodedata.normalize("NFKD", str(s)).lower()
    s = re.sub(r"\([^)]*\)", " ", s)  # вырезаем скобки
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ========== Heuristics & aliases ==========

_DESC_KEYS = {
    # EN/RU
    "description", "desc", "наименование", "наим", "описание", "наим.",
    # KA (включая встречавшуюся опечатку)
    "დასახელება", "დაასხელება",
}

_UNIT_KEYS = {
    "unit", "ед", "ед.", "единица", "ед.изм", "ед. изм.", "measure",
    "ერთეული", "सაზომი ერთეული", "განზ.", "საზომი ერთეული"
}

_QTY_KEYS = {"qty", "quantity", "кол-во", "количество", "кол во", "რაოდენობა"}

_PRICE_KEYS = {"unit price", "price", "rate", "ედ.цена", "единичная цена", "цена", "ერთ. ფასი"}

_AMOUNT_LIKE = {
    "amount", "sum", "total", "subtotal", "итого", "сумма",
    "სრული ფასი", "სულ", "სულ მონტაჟი"
}

# листовые стоп-слова (малоинформативные)
_SHEET_STOP = {
    "summary", "cover", "contents", "readme", "info", "лист1", "sheet1",
    "итого", "итог", "свод", "сводная", "boq", "rfq",
    "სულ", "ჯამი", "მთავარი", "main"
}


def _pick_by_name(cols_lower: Dict[str, str], aliases: set[str]) -> Optional[str]:
    for a in aliases:
        if a in cols_lower:
            return cols_lower[a]
    for k, orig in cols_lower.items():
        for a in aliases:
            if a in k:
                return orig
    return None


def _first_numeric_col(df: pd.DataFrame, exclude: set[str]) -> Optional[str]:
    best = None
    best_ratio = 0.0
    for c in df.columns:
        if c in exclude:
            continue
        ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        if ratio > best_ratio:
            best_ratio, best = ratio, c
    return best


def _valid_data_sheet(df: pd.DataFrame) -> bool:
    """Heuristic: must have > 1 column, some text, some numbers."""
    if df is None or df.shape[1] <= 1 or df.dropna(how="all").empty:
        return False
    # some numeric content
    num_ratio = 0.0
    for c in df.columns:
        r = pd.to_numeric(df[c], errors="coerce").notna().mean()
        num_ratio = max(num_ratio, r)
    text_like = any(df[c].dtype == "O" for c in df.columns)
    return (num_ratio > 0.2) and text_like


def _sheet_key(name: str) -> List[str]:
    """Нормализованное имя листа -> список токенов без стоп-слов."""
    tokens = [w for w in _norm(name).split() if w not in _SHEET_STOP]
    return tokens


def _jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    return len(A & B) / len(A | B)


# ========== BOQ parsing (multi-sheet -> single table) ==========

def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    """
    Собираем все листы BOQ в одну таблицу (один DataFrame).
    """
    all_sheets = _read_all_sheets_from_bytes(boq_bytes)
    rows = []

    for sheet_name, df in all_sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df = _raise_header_if_first_row_looks_like_headers(df)
        df = df.dropna(how="all")
        if not _valid_data_sheet(df):
            continue

        cols_lower = {str(c).strip().lower(): c for c in df.columns}

        c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
        c_qty = _pick_by_name(cols_lower, _QTY_KEYS)
        c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)

        if not c_qty:
            c_qty = _first_numeric_col(df, exclude=set())
        if not c_desc:
            scores = []
            for c in df.columns:
                s = _clean_series(df[c])
                scores.append((s.map(len).mean(), c))
            scores.sort(reverse=True)
            c_desc = scores[0][1]

        desc = _clean_series(df[c_desc])
        qty = pd.to_numeric(df[c_qty], errors="coerce").fillna(0)
        unit = _clean_series(df[c_unit]) if c_unit else pd.Series([""] * len(df))

        part = pd.DataFrame({
            "Description": desc,
            "Unit": unit,
            "Qty": qty,
            "BOQ Sheet": sheet_name,   # оставим для трассировки
        })
        part["desc_key"] = part["Description"].map(_norm)
        part["unit_key"] = part["Unit"].map(_norm)
        part["boq_sheet_key"] = part["BOQ Sheet"].map(_sheet_key)

        # убрать пустые строки
        part = part[~((part["desc_key"] == "") & (part["Qty"] == 0))]
        if not part.empty:
            rows.append(part)

    if not rows:
        raise ValueError("BOQ: подходящих листов не найдено")

    out = pd.concat(rows, ignore_index=True)
    out.reset_index(drop=True, inplace=True)
    out.insert(0, "No", range(1, len(out) + 1))
    return out


# ========== RFQ parsing (multi-sheet -> keep all, no global collapse) ==========

def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    """
    Читаем все листы RFQ и сохраняем КАЖДУЮ ценовую строку как есть.
    Ничего не агрегируем глобально (чтобы одинаковые описания в разных подсистемах не смешивались).
    """
    all_sheets = _read_all_sheets_from_bytes(rfq_bytes)
    rows = []

    for sheet_name, df in all_sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df = _raise_header_if_first_row_looks_like_headers(df)
        df = df.dropna(how="all")
        if not _valid_data_sheet(df):
            continue

        cols_lower = {str(c).strip().lower(): c for c in df.columns}
        c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
        c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
        c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

        if not c_desc:
            # самый "текстовый" объектный столбец
            text_scores = []
            for c in df.columns:
                if df[c].dtype == "O":
                    s = _clean_series(df[c])
                    text_scores.append((s.map(len).mean(), c))
            text_scores.sort(reverse=True)
            c_desc = text_scores[0][1] if text_scores else df.columns[0]

        if not c_price:
            # любая сильная числовая колонка, кроме qty/amount-like
            exclude = set()
            q = _pick_by_name(cols_lower, _QTY_KEYS)
            if q:
                exclude.add(q)
            for k, orig in cols_lower.items():
                if any(w in k for w in _AMOUNT_LIKE):
                    exclude.add(orig)
            c_price = _first_numeric_col(df, exclude)

        if not c_price:
            # лист без цен — пропускаем
            continue

        desc = _clean_series(df[c_desc])
        unit = _clean_series(df[c_unit]) if c_unit else pd.Series([""] * len(df))
        price = pd.to_numeric(df[c_price], errors="coerce").fillna(0)

        part = pd.DataFrame({
            "Description": desc,
            "Unit": unit,
            "Unit Price": price,
            "RFQ Sheet": sheet_name,
        })
        part["desc_key"] = part["Description"].map(_norm)
        part["unit_key"] = part["Unit"].map(_norm)
        part["rfq_sheet_key"] = part["RFQ Sheet"].map(_sheet_key)
        part = part[part["Unit Price"] > 0]

        if not part.empty:
            rows.append(part)

    if not rows:
        raise ValueError("RFQ: ценовые листы не найдены")

    rfq_all = pd.concat(rows, ignore_index=True)
    return rfq_all


# ========== Fuzzy helpers ==========

def _best_match_key(dk: str, supplier_keys: List[str]) -> Optional[str]:
    """Exact -> prefix -> Jaccard token similarity."""
    if not dk:
        return None
    if dk in supplier_keys:
        return dk
    pref = dk[:24]
    for k in supplier_keys:
        if k.startswith(pref) or dk.startswith(k):
            return k
    t = set(dk.split())
    best_k, best_s = None, 0.0
    for k in supplier_keys:
        tt = set(k.split())
        if not tt:
            continue
        inter = len(t & tt)
        union = len(t | tt)
        s = inter / union
        if s > 0.58 and s > best_s:
            best_k, best_s = k, s
    return best_k


# ========== Matching (sheet-aware, then global fallback) ==========

def align_offers(boq: pd.DataFrame, supplier_to_df: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    """
    Логика:
    1) Для каждой строки BOQ определяем её листовые токены (boq_sheet_key).
    2) По каждому поставщику ранжируем листы RFQ по похожести имени листа (Jaccard токенов).
    3) Ищем в лучшем RFQ-листе: exact (desc+unit) -> exact (desc) -> fuzzy(desc).
       Если не нашли — переходим к следующему RFQ-листу (по рангу).
       Если нигде не нашли — глобальный фоллбэк: fuzzy по всему RFQ.
    4) Notes/System колонку не создаём вовсе.
    """
    suppliers = sorted(supplier_to_df.keys())
    base = boq.copy()

    for s in suppliers:
        base[(s, "Unit Price")] = 0.0
        base[(s, "Total")] = 0.0
        base[(s, "Match")] = ""
        base[(s, "Notes")] = ""

    for s, df in supplier_to_df.items():
        # Индексы по листам RFQ
        by_sheet: Dict[str, pd.DataFrame] = {}
        for sh, sub in df.groupby("RFQ Sheet"):
            by_sheet[sh] = sub.copy()

        # Глобальные наборы для фоллбэка
        global_desc_keys = df["desc_key"].tolist()

        prices, totals, matches, notes = [], [], [], []
        for _, row in base.iterrows():
            dk = row["desc_key"]
            uk = row.get("unit_key", "")
            qty = float(row["Qty"])
            boq_tokens = row.get("boq_sheet_key", [])

            # Ранжирование листов RFQ по похожести имени (токены)
            sheet_scores = []
            for sh, sub in by_sheet.items():
                rfq_tokens = sub["rfq_sheet_key"].iloc[0] if not sub.empty else []
                sim = _jaccard(boq_tokens, rfq_tokens)
                sheet_scores.append((sim, sh))
            # Чем выше похожесть — тем раньше проверяем
            sheet_scores.sort(reverse=True)

            price = 0.0
            match_tag = "—"
            note = "No line in RFQ"
            used_sh = None

            # По листам — от наиболее похожего к менее похожим
            for sim, sh in sheet_scores:
                sub = by_sheet[sh]

                # 1) exact (desc+unit) в этом листе
                exact_du = sub[(sub["desc_key"] == dk) & (sub["unit_key"] == uk)]
                if not exact_du.empty:
                    price = float(exact_du["Unit Price"].iloc[0])
                    match_tag = "✅"
                    note = f"Exact in sheet: {sh}"
                    used_sh = sh
                    break

                # 2) exact (desc) — любая единица — в этом листе
                exact_d = sub[sub["desc_key"] == dk]
                if not exact_d.empty:
                    price = float(exact_d["Unit Price"].iloc[0])
                    if uk and uk not in exact_d["unit_key"].tolist():
                        match_tag = "❗"
                        note = f"Unit mismatch in sheet: {sh}"
                    else:
                        match_tag = "✅"
                        note = f"Exact (any unit) in sheet: {sh}"
                    used_sh = sh
                    break

                # 3) fuzzy(desc) в этом листе
                cand_keys = sub["desc_key"].unique().tolist()
                dk2 = _best_match_key(dk, cand_keys)
                if dk2:
                    sub2 = sub[sub["desc_key"] == dk2]
                    # приоритет — совпавшая единица, иначе первая попавшаяся
                    same_unit = sub2[sub2["unit_key"] == uk]
                    pick = same_unit.iloc[0] if not same_unit.empty else sub2.iloc[0]
                    price = float(pick["Unit Price"])
                    if not same_unit.empty:
                        match_tag = "✅"
                        note = f"Fuzzy (same unit) in sheet: {sh}"
                    else:
                        match_tag = "❗" if uk and uk != pick["unit_key"] else "✅"
                        note = f"Fuzzy in sheet: {sh}"
                    used_sh = sh
                    break

            # Глобальный фоллбэк, если ничего не нашли на листах
            if price == 0.0:
                dk2 = _best_match_key(dk, global_desc_keys)
                if dk2:
                    sub2 = df[df["desc_key"] == dk2]
                    same_unit = sub2[sub2["unit_key"] == uk]
                    pick = same_unit.iloc[0] if not same_unit.empty else sub2.iloc[0]
                    price = float(pick["Unit Price"])
                    if not same_unit.empty:
                        match_tag = "✅"
                        note = "Fuzzy (global, same unit)"
                    else:
                        match_tag = "❗" if uk and uk != pick["unit_key"] else "✅"
                        note = "Fuzzy (global)"
                # иначе остается дефолт: 0.0 / "—" / "No line in RFQ"

            prices.append(price)
            totals.append(price * qty)
            matches.append(match_tag)
            notes.append(note)

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = matches
        base[(s, "Notes")] = notes

    # Итоговый плоский отчёт (без Notes (System))
    cols = ["No", "BOQ Sheet", "Description", "Unit", "Qty"]
    for s in suppliers:
        cols += [(s, "Unit Price"), (s, "Total"), (s, "Match"), (s, "Notes")]

    flat = pd.DataFrame()
    for c in cols:
        if isinstance(c, tuple):
            flat[f"{c[0]}: {c[1]}"] = base[c]
        else:
            if c in base.columns:
                flat[c] = base[c]

    return suppliers, flat
