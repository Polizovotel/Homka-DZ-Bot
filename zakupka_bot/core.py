"""Расчёт закупки для поездки. Логика совпадает с веб-версией калькулятора.

Здесь нет ничего про Telegram: только данные и расчёты, поэтому модуль
легко проверять тестами.
"""
from __future__ import annotations

import math
import re
import secrets

UNITS = ["г", "мл", "шт"]
# Цвета-метки для продуктов, которые считаются вместе в нескольких блюдах.
MARKS = ["🟠", "🟣", "🔵", "🟢", "🟡", "🔴", "🟤", "⚪"]

NBSP = " "


def uid() -> str:
    return secrets.token_hex(3)


def jsround(x: float) -> int:
    """Округление как в JavaScript: 0.5 уходит вверх."""
    return int(math.floor(x + 0.5))


# --------------------------------------------------------------------------
# Выражения: 123+12, 34-24, 24*234, 134/234, скобки в приоритете
# --------------------------------------------------------------------------
_NUM = re.compile(r"(\d+\.?\d*|\.\d+)")


class _Parser:
    def __init__(self, text: str):
        self.t = text
        self.i = 0

    def peek(self) -> str:
        return self.t[self.i] if self.i < len(self.t) else ""

    def factor(self) -> float:
        c = self.peek()
        if c == "-":
            self.i += 1
            return -self.factor()
        if c == "+":
            self.i += 1
            return self.factor()
        if c == "(":
            self.i += 1
            v = self.expr()
            if self.peek() != ")":
                raise ValueError("скобка")
            self.i += 1
            return v
        m = _NUM.match(self.t, self.i)
        if not m:
            raise ValueError("число")
        self.i = m.end()
        return float(m.group(0))

    def term(self) -> float:
        v = self.factor()
        while self.peek() in ("*", "/") and self.peek() != "":
            op = self.t[self.i]
            self.i += 1
            r = self.factor()
            if op == "*":
                v *= r
            else:
                if r == 0:
                    raise ValueError("деление на ноль")
                v /= r
        return v

    def expr(self) -> float:
        v = self.term()
        while self.peek() in ("+", "-") and self.peek() != "":
            op = self.t[self.i]
            self.i += 1
            r = self.term()
            v = v + r if op == "+" else v - r
        return v


def eval_expr(src) -> tuple[bool, float]:
    s = "" if src is None else str(src)
    s = re.sub(r"\s", "", s).replace(",", ".").replace("×", "*").replace("÷", "/")
    s = re.sub("[−–—]", "-", s)
    if s == "":
        return True, 0.0
    if len(s) > 200:
        return False, 0.0
    try:
        p = _Parser(s)
        v = p.expr()
        if p.i != len(s) or not math.isfinite(v):
            return False, 0.0
        return True, v
    except (ValueError, RecursionError):
        return False, 0.0


def num(src) -> float:
    ok, v = eval_expr(src)
    return v if ok else 0.0


_UNIT_RE = re.compile(r"^(.*?)\s*(кг|kg|гр|г|g|мл|ml|л|l|шт)\.?\s*$", re.I)
_UNIT_MAP = {
    "кг": ("г", 1000), "kg": ("г", 1000), "гр": ("г", 1), "г": ("г", 1), "g": ("г", 1),
    "мл": ("мл", 1), "ml": ("мл", 1), "л": ("мл", 1000), "l": ("мл", 1000), "шт": ("шт", 1),
}


def numstr(v: float) -> str:
    out = ("%.6f" % v).rstrip("0").rstrip(".")
    return out if out not in ("", "-0") else "0"


def parse_field(text: str, allow_unit: bool = True) -> dict:
    """Разбирает ввод вроде «120», «0,5 кг», «2+1 шт», «(10+5)*2».

    Возвращает {"ok", "value", "unit", "err"}. Килограммы и литры переводятся
    в граммы и миллилитры.
    """
    t = (text or "").strip()
    unit = None
    mult = 1
    if allow_unit:
        m = _UNIT_RE.match(t)
        if m:
            unit, mult = _UNIT_MAP[m.group(2).lower()]
            t = m.group(1).strip()
            if t == "":
                return {"ok": False, "err": "Перед единицей нужно число, например «500 г»."}
    ok, v = eval_expr(t)
    if not ok or t == "":
        return {"ok": False, "err": "Не получилось посчитать. Пример: 120, 0,5 кг или (10+5)*2."}
    v *= mult
    if v < 0:
        return {"ok": False, "err": "Число не может быть отрицательным."}
    return {"ok": True, "value": numstr(v), "unit": unit}


# --------------------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------------------
def money(x: float) -> str:
    return f"{jsround(x):,}".replace(",", NBSP) + NBSP + "₽"


def trim_num(x: float) -> str:
    return str(round(x * 100) / 100).replace(".", ",").removesuffix(",0")


def qty(v: float, unit: str) -> str:
    if unit == "шт":
        return trim_num(v) + " шт"
    big = v >= 1000
    x = v / 1000 if big else v
    label = ("кг" if unit == "г" else "л") if big else unit
    return trim_num(x) + " " + label


def pl(n: float, forms: tuple[str, str, str]) -> str:
    n = abs(jsround(n))
    m, d = n % 100, n % 10
    if 10 < m < 20:
        return forms[2]
    if d == 1:
        return forms[0]
    if 2 <= d <= 4:
        return forms[1]
    return forms[2]


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------
def new_ing(name: str = "") -> dict:
    return {"id": uid(), "name": name, "per": "", "unit": "г", "packSize": "", "price": "", "payer": "", "link": ""}


def new_dish(name: str = "") -> dict:
    return {"id": uid(), "name": name, "portions": "", "ings": []}


def blank_state() -> dict:
    return {"v": 2, "title": "", "people": [], "dishes": [], "extras": [], "bought": {}, "prompts": {}}


def example_state() -> dict:
    names = ["Аня", "Борис", "Вика", "Глеб", "Даша"]
    people = [{"id": uid(), "name": n} for n in names]
    P = lambda i: people[i]["id"]

    def g(name, per, unit, size, price, payer):
        x = new_ing(name)
        x.update(per=str(per), unit=unit, packSize=str(size), price=str(price), payer=payer)
        return x

    onion = g("Лук репчатый", 100, "г", 1000, 69, P(2))
    lasagna = [
        g("Листы для лазаньи", 60, "г", 250, 129, P(0)),
        g("Фарш говяжий", 120, "г", 500, 349, P(0)),
        g("Томаты в собственном соку", 80, "г", 400, 119, P(1)),
        g("Сыр моцарелла", 50, "г", 250, 219, P(1)),
        g("Сливки 20%", 60, "мл", 330, 99, P(0)),
    ]
    linked = new_ing("")
    linked.update(per="20", unit="г", link=onion["id"])
    lasagna.append(linked)
    S = blank_state()
    S["title"] = "Выходные на природе"
    S["people"] = people
    S["dishes"] = [
        {"id": uid(), "name": "Лазанья", "portions": "", "ings": lasagna},
        {"id": uid(), "name": "Шашлык из курицы", "portions": "", "ings": [
            g("Куриные бёдра", 250, "г", 1000, 399, P(2)), onion, g("Кефир для маринада", 100, "мл", 900, 109, P(2))]},
        {"id": uid(), "name": "Блины на завтрак", "portions": "10", "ings": [
            g("Молоко", 100, "мл", 1000, 95, P(3)), g("Яйца", 1, "шт", 10, 129, P(3)), g("Мука", 50, "г", 1000, 79, P(4))]},
    ]
    S["extras"] = [
        {"id": uid(), "name": "Уголь и дрова", "sum": "450", "payer": P(1)},
        {"id": uid(), "name": "Напитки", "sum": "900", "payer": P(4)},
    ]
    return S


# ---- поиск и связи ------------------------------------------------------
def find_ing(S: dict, iid: str):
    for d in S["dishes"]:
        for g in d["ings"]:
            if g["id"] == iid:
                return d, g
    return None


def find_dish(S: dict, did: str):
    return next((d for d in S["dishes"] if d["id"] == did), None)


def find_person(S: dict, pid: str):
    return next((p for p in S["people"] if p["id"] == pid), None)


def find_extra(S: dict, xid: str):
    return next((x for x in S["extras"] if x["id"] == xid), None)


def master(S: dict, g: dict) -> dict:
    if g.get("link"):
        f = find_ing(S, g["link"])
        if f and not f[1].get("link") and f[1] is not g:
            return f[1]
    return g


def dependents(S: dict, iid: str) -> list[dict]:
    return [x for d in S["dishes"] for x in d["ings"] if x.get("link") == iid]


def candidates(S: dict, dish: dict) -> list[tuple[dict, dict]]:
    """Продукты из ДРУГИХ блюд, с которыми можно считать пачку вместе."""
    out = []
    for d in S["dishes"]:
        if d["id"] == dish["id"]:
            continue
        for h in d["ings"]:
            if not h.get("link") and (h.get("name") or "").strip():
                out.append((h, d))
    return out


def copy_pack(to: dict, src: dict) -> None:
    for k in ("name", "unit", "packSize", "price", "payer"):
        to[k] = src.get(k, "")


def set_link(S: dict, g: dict, mid: str) -> None:
    if mid:
        f = find_ing(S, mid)
        if f:
            g["link"] = mid
            g["unit"] = f[1]["unit"]
    else:
        cur = find_ing(S, g.get("link") or "")
        if cur:
            copy_pack(g, cur[1])
        g["link"] = ""


def release_ing(S: dict, g: dict) -> None:
    """Перед удалением продукта передаёт общую пачку следующему блюду."""
    deps = dependents(S, g["id"])
    if deps:
        first = deps[0]
        copy_pack(first, g)
        first["link"] = ""
        for x in deps[1:]:
            x["link"] = first["id"]
        if S["bought"].get(g["id"]):
            S["bought"][first["id"]] = True
    S["bought"].pop(g["id"], None)


def set_unit(S: dict, g: dict, unit: str) -> None:
    g["unit"] = unit
    for x in dependents(S, g["id"]):
        x["unit"] = unit


# --------------------------------------------------------------------------
# Расчёт
# --------------------------------------------------------------------------
def calc(S: dict) -> dict:
    people = S["people"]
    n = len(people)
    paid = {p["id"]: 0 for p in people}
    un = {"count": 0, "sum": 0}

    def add_cost(rub: float, payer: str, counted: bool) -> None:
        kop = jsround(rub * 100)
        if payer in paid:
            paid[payer] += kop
        elif counted:
            un["count"] += 1
            un["sum"] += kop

    dish_need = {}
    for d in S["dishes"]:
        p = math.floor(num(d.get("portions")))
        dish_need[d["id"]] = p if p > 0 else n

    groups: dict[str, dict] = {}
    order: list[str] = []
    for d in S["dishes"]:
        for g in d["ings"]:
            m = master(S, g)
            if m["id"] not in groups:
                groups[m["id"]] = {"m": m, "rows": []}
                order.append(m["id"])
            groups[m["id"]]["rows"].append({"g": g, "d": d, "need": dish_need[d["id"]] * num(g.get("per"))})

    res: dict[str, dict] = {}
    groc = 0.0
    for gid in order:
        G = groups[gid]
        m = G["m"]
        need_total = sum(r["need"] for r in G["rows"])
        size = num(m.get("packSize"))
        if need_total <= 0:
            packs = 0
        elif size > 0:
            packs = math.ceil(need_total / size - 1e-9)
        else:
            packs = 1
        covers = packs * size if size > 0 else need_total
        price = num(m.get("price"))
        total = packs * price
        used = bool((m.get("name") or "").strip()) or price > 0 or need_total > 0
        res[gid] = {
            "m": m, "rows": G["rows"], "need_total": need_total, "size": size, "packs": packs,
            "left": covers - need_total if size > 0 else 0, "total": total, "used": used,
            "has_size": size > 0, "unit": m.get("unit") or "г", "shared": False, "mark": "",
        }
        if used:
            groc += total
            add_cost(total, m.get("payer") or "", total > 0)

    k = 0
    for gid in order:
        G = res[gid]
        G["shared"] = len(G["rows"]) > 1 and G["used"]
        if G["shared"]:
            G["mark"] = MARKS[k % len(MARKS)]
            k += 1

    dishes = []
    for d in S["dishes"]:
        cost = 0.0
        ings = []
        for g in d["ings"]:
            m = master(S, g)
            G = res[m["id"]]
            need = dish_need[d["id"]] * num(g.get("per"))
            share = G["total"] * need / G["need_total"] if (G["used"] and G["need_total"] > 0) else 0.0
            cost += share
            others, seen = [], set()
            for r in G["rows"]:
                if r["g"] is not g and r["d"]["id"] != d["id"] and r["d"]["id"] not in seen:
                    seen.add(r["d"]["id"])
                    others.append(r["d"])
            ings.append({
                "g": g, "G": G, "linked": m is not g, "need": need, "share": share,
                "deps": len(G["rows"]) - 1 if m is g else 0, "shared": G["shared"], "others": others,
            })
        nd = dish_need[d["id"]]
        dishes.append({
            "d": d, "need": nd, "cost": cost, "ings": ings,
            "per_person": cost / n if n else 0, "per_portion": cost / nd if nd else 0,
        })

    extras_sum = 0.0
    for x in S["extras"]:
        v = num(x.get("sum"))
        if v > 0:
            extras_sum += v
            add_cost(v, x.get("payer") or "", True)

    assigned = sum(paid.values())
    share = assigned / n if n else 0
    rows = [{"p": p, "paid": paid[p["id"]] / 100, "bal": jsround(paid[p["id"]] - share)} for p in people]
    cr = sorted(({"p": r["p"], "b": r["bal"]} for r in rows if r["bal"] > 0), key=lambda x: -x["b"])
    db = sorted(({"p": r["p"], "b": -r["bal"]} for r in rows if r["bal"] < 0), key=lambda x: -x["b"])
    i = j = 0
    transfers = []
    while i < len(db) and j < len(cr):
        a = min(db[i]["b"], cr[j]["b"])
        if a > 0:
            transfers.append({"from": db[i]["p"], "to": cr[j]["p"], "amt": a})
        db[i]["b"] -= a
        cr[j]["b"] -= a
        if db[i]["b"] <= 0:
            i += 1
        if cr[j]["b"] <= 0:
            j += 1

    return {
        "n": n, "dishes": dishes, "res": res, "order": order, "groc": groc, "extras_sum": extras_sum,
        "un": {"count": un["count"], "sum": un["sum"] / 100}, "grand": groc + extras_sum,
        "share": share / 100, "rows": rows, "transfers": transfers,
    }


# --------------------------------------------------------------------------
# Импорт и экспорт (формат совпадает с кнопкой «Сохранить или передать данные»
# на веб-странице)
# --------------------------------------------------------------------------
_ID = re.compile(r"^[A-Za-z0-9_-]{1,12}$")


def _s(x, n=60) -> str:
    return ("" if x is None else str(x)).strip()[:n]


def sanitize(o) -> dict:
    """Собирает чистое состояние из чужого JSON или бросает ValueError."""
    if not isinstance(o, dict) or o.get("v") != 2:
        raise ValueError("не тот формат")
    S = blank_state()
    S["title"] = _s(o.get("title"), 60)
    seen: set[str] = set()

    def sid(x) -> str:
        x = _s(x, 12)
        if not _ID.match(x) or x in seen:
            raise ValueError("плохой id")
        seen.add(x)
        return x

    for p in o.get("people") or []:
        item = {"id": sid(p.get("id")), "name": _s(p.get("name"), 40)}
        if isinstance(p.get("tg"), int):
            item["tg"] = p["tg"]
        S["people"].append(item)
    if not S["people"]:
        raise ValueError("нет участников")
    pids = {p["id"] for p in S["people"]}
    for d in o.get("dishes") or []:
        dd = {"id": sid(d.get("id")), "name": _s(d.get("name"), 60), "portions": _s(d.get("portions"), 40), "ings": []}
        for g in d.get("ings") or []:
            unit = g.get("unit") if g.get("unit") in UNITS else "г"
            dd["ings"].append({
                "id": sid(g.get("id")), "name": _s(g.get("name"), 60), "per": _s(g.get("per"), 40), "unit": unit,
                "packSize": _s(g.get("packSize"), 40), "price": _s(g.get("price"), 40),
                "payer": g.get("payer") if g.get("payer") in pids else "", "link": _s(g.get("link"), 12),
            })
        S["dishes"].append(dd)
    all_ids = {g["id"] for d in S["dishes"] for g in d["ings"]}
    for d in S["dishes"]:
        for g in d["ings"]:
            if g["link"] not in all_ids or g["link"] == g["id"]:
                g["link"] = ""
    for x in o.get("extras") or []:
        S["extras"].append({
            "id": sid(x.get("id")), "name": _s(x.get("name"), 60), "sum": _s(x.get("sum"), 40),
            "payer": x.get("payer") if x.get("payer") in pids else "",
        })
    b = o.get("bought")
    if isinstance(b, dict):
        S["bought"] = {k: True for k, v in b.items() if v and _ID.match(str(k))}
    return S


def export_state(S: dict) -> dict:
    out = {k: v for k, v in S.items() if k != "prompts"}
    out["example"] = False
    return out
