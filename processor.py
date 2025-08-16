from __future__ import annotations

import io
import re
import unicodedata
from typing import Dict, List, Tuple, Optional

import pandas as pd


# ============================ IO & headers ============================

def _read_all_sheets_from_bytes(b: bytes) -> Dict[str, pd.DataFrame]:
    return pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")


def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
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


# ============================ text/number utils ============================

def _clean_series(s: pd.Series) -> pd.Series:
    s = s.astype(object).where(~pd.isna(s), "")
    s = s.replace({"nan": "", "None": "", None: ""})
    return s.astype(str)


def _norm(s: str) -> str:
    if s is None:
        s = ""
    s = unicodedata.normalize("NFKD", str(s)).lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _to_float(x) -> float:
    if isinstance(x, (int, float)) and pd.notna(x):
        return float(x)
    s = str(x)
    if s is None or s.strip() == "":
        return 0.0
    # убрать валюты/пробелы/нечисловые
    s = s.replace("\u00A0", "").replace(" ", "")
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") and s.count("."):
        # последний из разделителей считаем десятичным
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        if s.count(",") and not s.count("."):
            s = s.replace(",", ".")
        # иначе точки остаются как десятичные, запятые как тысячные уже удалены
    try:
        return float(s)
    except Exception:
        return 0.0


# ============================ columns & aliases ============================

_DESC_KEYS = {
    "description", "desc", "наименование", "наим", "описание", "наим.",
    "დასახელება", "დაასხელება",
}

_UNIT_KEYS = {
    "unit", "ед", "ед.", "единица", "ед.изм", "ед. изм.", "measure",
    "ერთეული", "საზომი ერთეული", "განზ.", "საზ. ერთ."
}

_QTY_KEYS = {"qty", "quantity", "кол-во", "количество", "кол во", "რაოდენობა"}

_PRICE_KEYS = {"unit price", "price", "rate", "ед.цена", "единичная цена", "цена", "ერთ. ფასი"}

_AMOUNT_LIKE = {
    "amount", "sum", "total", "subtotal", "итого", "сумма",
    "სრული ფასი", "სულ", "სულ მონტაჟი"
}

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
    if df is None or df.shape[1] <= 1 or df.dropna(how="all").empty:
        return False
    num_ratio = 0.0
    for c in df.columns:
        r = pd.to_numeric(df[c], errors="coerce").notna().mean()
        num_ratio = max(num_ratio, r)
    text_like = any(df[c].dtype == "O" for c in df.columns)
    return (num_ratio > 0.2) and text_like


def _sheet_key(name: str) -> List[str]:
    tokens = [w for w in _norm(name).split() if w not in _SHEET_STOP]
    return tokens


def _jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    return len(A & B) / len(A | B)


# ============================ unit normalization ============================

_UNIT_MAP = {
    # pieces
    "шт": "pcs", "шт.": "pcs", "piece": "pcs", "pcs": "pcs", "pc": "pcs",
    "ც": "pcs", "ცალი": "pcs", "ცალ": "pcs",
    # meter
    "м": "m", "м.": "m", "meter": "m", "m": "m", "მ": "m",
    # m2
    "м2": "m2", "м^2": "m2", "м²": "m2", "sqm": "m2", "m2": "m2", "მ2": "m2", "მ^2": "m2",
    # m3
    "м3": "m3", "м^3": "m3", "м³": "m3", "m3": "m3", "მ3": "m3", "მ^3": "m3",
    # kg
    "кг": "kg", "kg": "kg",
    # set
    "компл": "set", "комплект": "set", "set": "set",
}

def _norm_unit(u: str) -> str:
    if not u:
        return ""
    base = _norm(u).replace(".", "")
    return _UNIT_MAP.get(base, base)


# ============================ BOQ (multi-sheet -> single) ============================

def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    all_sheets = _read_all_sheets_from_bytes(boq_bytes)
    rows = []

    for sheet_name, df in all_sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df = _raise_header_if_first_row_looks_like_headers(df).dropna(how="all")
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
            "Unit": unit.map(_norm_unit),
            "Qty": qty,
            "BOQ Sheet": sheet_name,
        })
        part["desc_key"] = part["Description"].map(_norm)
        part["unit_key"] = part["Unit"].map(_norm_unit)
        part["boq_sheet_key"] = part["BOQ Sheet"].map(_sheet_key)
        part = part[~((part["desc_key"] == "") & (part["Qty"] == 0))]
        if not part.empty:
            rows.append(part)

    if not rows:
        raise ValueError("BOQ: подходящих листов не найдено")

    out = pd.concat(rows, ignore_index=True)
    out.reset_index(drop=True, inplace=True)
    out.insert(0, "No", range(1, len(out) + 1))
    return out


# ============================ RFQ parsers ============================

def _parse_rfq_excel(rfq_bytes: bytes) -> pd.DataFrame:
    all_sheets = _read_all_sheets_from_bytes(rfq_bytes)
    rows = []
    for sheet_name, df in all_sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df = _raise_header_if_first_row_looks_like_headers(df).dropna(how="all")
        if not _valid_data_sheet(df):
            continue

        cols_lower = {str(c).strip().lower(): c for c in df.columns}
        c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
        c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
        c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

        if not c_desc:
            text_scores = []
            for c in df.columns:
                if df[c].dtype == "O":
                    s = _clean_series(df[c])
                    text_scores.append((s.map(len).mean(), c))
            text_scores.sort(reverse=True)
            c_desc = text_scores[0][1] if text_scores else df.columns[0]

        # если явной цены нет — пробуем Amount/Total ÷ Qty
        if not c_price:
            c_amount = None
            for k, orig in cols_lower.items():
                if any(w in k for w in _AMOUNT_LIKE):
                    c_amount = orig
                    break
            qcol = _pick_by_name(cols_lower, _QTY_KEYS)
            if c_amount and qcol:
                df["__computed_price__"] = df[c_amount].apply(_to_float) / df[qcol].apply(_to_float).replace(0, pd.NA)
                c_price = "__computed_price__"

        if not c_price:
            # как минимум найдём числовую колонку
            exclude = set()
            q = _pick_by_name(cols_lower, _QTY_KEYS)
            if q:
                exclude.add(q)
            c_price = _first_numeric_col(df, exclude)

        if not c_price:
            continue

        part = pd.DataFrame({
            "Description": _clean_series(df[c_desc]),
            "Unit": _clean_series(df[c_unit]) if c_unit else pd.Series([""] * len(df)),
            "Unit Price": df[c_price].apply(_to_float),
            "RFQ Sheet": sheet_name,
        })
        part["desc_key"] = part["Description"].map(_norm)
        part["unit_key"] = part["Unit"].map(_norm_unit)
        part["rfq_sheet_key"] = part["RFQ Sheet"].map(_sheet_key)
        part = part[part["Unit Price"] > 0]
        if not part.empty:
            rows.append(part)

    if not rows:
        raise ValueError("RFQ: ценовые листы не найдены (xlsx)")

    return pd.concat(rows, ignore_index=True)


def _parse_rfq_pdf(rfq_bytes: bytes) -> pd.DataFrame:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber не установлен — PDF RFQ не поддержаны")

    rows = []
    with pdfplumber.open(io.BytesIO(rfq_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            # header tokens для «ключа листа»
            try:
                words = page.extract_words()
                h = page.height
                header_text = " ".join(w["text"] for w in words if w["top"] < 0.18 * h)
            except Exception:
                header_text = ""
            rfq_sheet_name = f"page {i}: " + (header_text[:40] if header_text else "")

            # пробуем две стратегии извлечения таблиц
            strategies = [
                dict(vertical_strategy="lines", horizontal_strategy="lines",
                     intersection_tolerance=5, snap_tolerance=3, join_tolerance=3, edge_min_length=40),
                dict(vertical_strategy="text", horizontal_strategy="text",
                     text_tolerance=2, snap_tolerance=3, join_tolerance=3),
            ]
            tables = []
            for st in strategies:
                try:
                    tables = page.extract_tables(st)
                    if tables:
                        break
                except Exception:
                    continue

            if not tables:
                # без таблиц — попробуем «строчник»: очень грубо
                txt = page.extract_text() or ""
                lines = [l.strip() for l in txt.splitlines() if l.strip()]
                for ln in lines:
                    # эвристика: "... qty price amount" — игнорируем
                    pass
                # нет надёжной таблицы — пропускаем страницу
                continue

            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                df = pd.DataFrame(tbl[1:], columns=tbl[0])
                df = df.dropna(how="all").dropna(axis=1, how="all")
                if df.empty:
                    continue

                df = _raise_header_if_first_row_looks_like_headers(df).dropna(how="all")
                if df.empty:
                    continue

                cols_lower = {str(c).strip().lower(): c for c in df.columns}
                c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
                c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
                c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

                if not c_desc:
                    # choose most "texty"
                    text_scores = []
                    for c in df.columns:
                        s = _clean_series(df[c])
                        text_scores.append((s.map(len).mean(), c))
                    text_scores.sort(reverse=True)
                    c_desc = text_scores[0][1]

                if not c_price:
                    c_amount = None
                    for k, orig in cols_lower.items():
                        if any(w in k for w in _AMOUNT_LIKE):
                            c_amount = orig
                            break
                    qcol = _pick_by_name(cols_lower, _QTY_KEYS)
                    if c_amount and qcol:
                        df["__computed_price__"] = df[c_amount].apply(_to_float) / df[qcol].apply(_to_float).replace(0, pd.NA)
                        c_price = "__computed_price__"

                if not c_price:
                    # fallback: первая числовая
                    exclude = set()
                    q = _pick_by_name(cols_lower, _QTY_KEYS)
                    if q:
                        exclude.add(q)
                    c_price = _first_numeric_col(df, exclude)

                if not c_price:
                    continue

                part = pd.DataFrame({
                    "Description": _clean_series(df[c_desc]),
                    "Unit": _clean_series(df[c_unit]) if c_unit else pd.Series([""] * len(df)),
                    "Unit Price": df[c_price].apply(_to_float),
                    "RFQ Sheet": rfq_sheet_name,
                })
                part["desc_key"] = part["Description"].map(_norm)
                part["unit_key"] = part["Unit"].map(_norm_unit)
                part["rfq_sheet_key"] = part["RFQ Sheet"].map(_sheet_key)
                part = part[part["Unit Price"] > 0]
                if not part.empty:
                    rows.append(part)

    if not rows:
        raise ValueError("RFQ: не удалось извлечь ценовые таблицы из PDF (вероятно скан).")

    return pd.concat(rows, ignore_index=True)


def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    # Авто-детект PDF
    head = rfq_bytes[:8]
    if isinstance(head, bytes) and b"%PDF" in head:
        return _parse_rfq_pdf(rfq_bytes)
    # иначе считаем Excel
    return _parse_rfq_excel(rfq_bytes)


# ============================ fuzzy matching ============================

def _best_match_key(dk: str, supplier_keys: List[str]) -> Optional[str]:
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


# ============================ alignment ============================

def align_offers(boq: pd.DataFrame, supplier_to_df: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    suppliers = sorted(supplier_to_df.keys())
    base = boq.copy()

    for s in suppliers:
        base[(s, "Unit Price")] = 0.0
        base[(s, "Total")] = 0.0
        base[(s, "Match")] = ""
        base[(s, "Notes")] = ""

    for s, df in supplier_to_df.items():
        by_sheet: Dict[str, pd.DataFrame] = {}
        for sh, sub in df.groupby("RFQ Sheet"):
            by_sheet[sh] = sub.copy()

        global_desc_keys = df["desc_key"].tolist()

        prices, totals, matches, notes = [], [], [], []
        for _, row in base.iterrows():
            dk = row["desc_key"]
            uk = row.get("unit_key", "")
            qty = float(row["Qty"])
            boq_tokens = row.get("boq_sheet_key", [])

            # ранжируем страницы/листы RFQ
            sheet_scores = []
            for sh, sub in by_sheet.items():
                rfq_tokens = sub["rfq_sheet_key"].iloc[0] if not sub.empty else []
                sim = _jaccard(boq_tokens, rfq_tokens)
                sheet_scores.append((sim, sh))
            sheet_scores.sort(reverse=True)

            price = 0.0
            match_tag = "—"
            note = "No line in RFQ"

            for sim, sh in sheet_scores:
                sub = by_sheet[sh]

                exact_du = sub[(sub["desc_key"] == dk) & (sub["unit_key"] == uk)]
                if not exact_du.empty:
                    price = float(exact_du["Unit Price"].iloc[0]); match_tag = "✅"; note = f"Exact in sheet: {sh}"; break

                exact_d = sub[sub["desc_key"] == dk]
                if not exact_d.empty:
                    price = float(exact_d["Unit Price"].iloc[0])
                    if uk and uk not in exact_d["unit_key"].tolist():
                        match_tag = "❗"; note = f"Unit mismatch in sheet: {sh}"
                    else:
                        match_tag = "✅"; note = f"Exact (any unit) in sheet: {sh}"
                    break

                cand_keys = sub["desc_key"].unique().tolist()
                dk2 = _best_match_key(dk, cand_keys)
                if dk2:
                    sub2 = sub[sub["desc_key"] == dk2]
                    same_unit = sub2[sub2["unit_key"] == uk]
                    pick = same_unit.iloc[0] if not same_unit.empty else sub2.iloc[0]
                    price = float(pick["Unit Price"])
                    if not same_unit.empty:
                        match_tag = "✅"; note = f"Fuzzy (same unit) in sheet: {sh}"
                    else:
                        match_tag = "❗" if uk and uk != pick["unit_key"] else "✅"
                        note = f"Fuzzy in sheet: {sh}"
                    break

            if price == 0.0:
                dk2 = _best_match_key(dk, global_desc_keys)
                if dk2:
                    sub2 = df[df["desc_key"] == dk2]
                    same_unit = sub2[sub2["unit_key"] == uk]
                    pick = same_unit.iloc[0] if not same_unit.empty else sub2.iloc[0]
                    price = float(pick["Unit Price"])
                    if not same_unit.empty:
                        match_tag = "✅"; note = "Fuzzy (global, same unit)"
                    else:
                        match_tag = "❗" if uk and uk != pick["unit_key"] else "✅"
                        note = "Fuzzy (global)"

            prices.append(price)
            totals.append(price * qty)
            matches.append(match_tag)
            notes.append(note)

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = matches
        base[(s, "Notes")] = notes

    # финальный «плоский» отчёт: без BOQ Sheet
    cols = ["No", "Description", "Unit", "Qty"]
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
