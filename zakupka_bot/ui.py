"""Экраны и действия бота.

Модуль ничего не знает про Telegram: клавиатуры это списки строк из пар
(текст кнопки, callback_data), а результат любого действия это объект Out.
Благодаря этому всё поведение проверяется обычными тестами.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass

from core import (
    UNITS, blank_state, calc, candidates, copy_pack, dependents, example_state, find_dish, find_extra,
    find_ing, find_person, jsround, master, money, new_dish, new_ing, num, parse_field, pl, qty,
    release_ing, set_link, set_unit, uid,
)

Kb = list[list[tuple[str, str]]]
Screen = tuple[str, Kb]

PAGE = 12  # позиций на странице списка покупок


def h(x) -> str:
    return html.escape("" if x is None else str(x), quote=False)


def short(s: str, n: int = 20) -> str:
    s = (s or "").strip() or "Без названия"
    return s if len(s) <= n else s[: n - 1] + "…"


def grid(btns: list, per: int = 2) -> Kb:
    return [btns[i:i + per] for i in range(0, len(btns), per)]


def B(text: str, data: str) -> tuple[str, str]:
    return (text, data)


@dataclass
class Ask:
    """Нужно спросить текст у пользователя (бот пришлёт ForceReply)."""
    text: str
    meta: dict
    placeholder: str = ""


@dataclass
class Out:
    screen: Screen | None = None
    ask: Ask | None = None
    toast: str | None = None
    send: str | None = None      # отдельное сообщение, например расчёт для пересылки
    export: bool = False
    err: str | None = None


NAME_ERR = "Название не должно быть пустым."


def clean_name(text: str, limit: int = 40) -> str:
    return " ".join((text or "").split())[:limit]


# ==========================================================================
# Экраны
# ==========================================================================
def scr_menu(S: dict) -> Screen:
    C = calc(S)
    n = C["n"]
    used = sum(1 for gid in C["order"] if C["res"][gid]["used"])
    t = f"🏕 <b>{h(S['title'] or 'Закупка на выезд')}</b>\n"
    t += (f"👥 {n} {pl(n, ('человек', 'человека', 'человек'))} · "
          f"🍲 {len(S['dishes'])} {pl(len(S['dishes']), ('блюдо', 'блюда', 'блюд'))} · "
          f"🛒 {used} {pl(used, ('продукт', 'продукта', 'продуктов'))}\n")
    t += f"💰 Всего <b>{money(C['grand'])}</b> · <b>{money(C['grand'] / n if n else 0)}</b> с человека"
    if n == 0:
        t += ("\n\n👉 Начните с участников: нажмите «Участники» и добавьте всех, кто едет. "
              "Или загрузите пример в разделе «Ещё».")
    elif not S["dishes"]:
        t += "\n\n👉 Теперь добавьте блюда в разделе «Блюда»."
    if C["un"]["count"]:
        k = C["un"]["count"]
        t += f"\n⚠️ У {k} {pl(k, ('позиции', 'позиций', 'позиций'))} не выбран покупатель ({money(C['un']['sum'])})"
    kb = [
        [B("👥 Участники", "pl"), B("🍲 Блюда", "dl")],
        [B("🧾 Покупки", "sh:0"), B("💰 Расчёт", "se")],
        [B("🧂 Общие траты", "xl"), B("⚙️ Ещё", "mo")],
    ]
    return t, kb


def scr_confirm(text: str, yes: str, no: str) -> Screen:
    return text, [[B("✅ Да", yes), B("Отмена", no)]]


# ---- участники -----------------------------------------------------------
def scr_people(S: dict) -> Screen:
    C = calc(S)
    if not S["people"]:
        t = ("👥 <b>Участники</b>\n\nПока никого нет. Нажмите «Добавить» и напишите имена всех, "
             "кто едет, через запятую.")
    else:
        lines = [f"• {h(r['p']['name'])}: потратил(а) {money(r['paid'])}" for r in C["rows"]]
        t = f"👥 <b>Участники</b> · {C['n']}\n\n" + "\n".join(lines)
    btns = [B("👤 " + short(p["name"], 16), f"pe:{p['id']}") for p in S["people"]]
    kb = grid(btns, 2) + [[B("➕ Добавить", "pa"), B("🙋 Я еду", "pm")], [B("‹ Меню", "m")]]
    return t, kb


def scr_person(S: dict, pid: str) -> Screen:
    p = find_person(S, pid)
    if not p:
        return scr_people(S)
    C = calc(S)
    r = next(x for x in C["rows"] if x["p"]["id"] == pid)
    if r["bal"] > 0:
        bal = f"🟢 получит {money(r['bal'] / 100)}"
    elif r["bal"] < 0:
        bal = f"🔴 отдаст {money(-r['bal'] / 100)}"
    else:
        bal = "✅ в расчёте"
    t = (f"👤 <b>{h(p['name'])}</b>\nПотратил(а): {money(r['paid'])}\n"
         f"Доля: {money(C['share'])}\nИтог: {bal}")
    kb = [[B("✏️ Переименовать", f"pr:{pid}"), B("🗑 Удалить", f"pd:{pid}")], [B("‹ Участники", "pl")]]
    return t, kb


# ---- блюда ---------------------------------------------------------------
def scr_dishes(S: dict) -> Screen:
    C = calc(S)
    if not S["dishes"]:
        t = "🍲 <b>Блюда</b>\n\nПока пусто. Нажмите «Блюдо» и напишите название, например «Лазанья»."
    else:
        t = "🍲 <b>Блюда</b>\n\n" + "\n".join(
            f"• {h(D['d']['name'] or 'Без названия')}: {money(D['cost'])} · {D['need']} порц." for D in C["dishes"])
    kb = [[B(f"🍲 {short(D['d']['name'], 22)} · {money(D['cost'])}", f"d:{D['d']['id']}")] for D in C["dishes"]]
    kb += [[B("➕ Блюдо", "da"), B("‹ Меню", "m")]]
    return t, kb


def _ing_line(i: int, E: dict) -> str:
    G = E["G"]
    m = G["m"]
    mark = (G["mark"] + " ") if E["shared"] else ""
    per = num(E["g"].get("per"))
    per_s = f"{qty(per, G['unit'])}/порц" if per > 0 else "без количества"
    if E["linked"]:
        tail = f"часть общей пачки ~{money(E['share'])}"
    elif G["packs"] > 0:
        tail = f"{G['packs']} {pl(G['packs'], ('пачка', 'пачки', 'пачек'))} · {money(G['total'])}"
    else:
        tail = "заполните расчёт"
    return f"{i}. {mark}<b>{h(m['name'] or 'Без названия')}</b>: {per_s} → {tail}"


def scr_dish(S: dict, did: str) -> Screen:
    d = find_dish(S, did)
    if not d:
        return scr_dishes(S)
    C = calc(S)
    D = next(x for x in C["dishes"] if x["d"]["id"] == did)
    manual = math.floor(num(d.get("portions"))) > 0
    t = (f"🍲 <b>{h(d['name'] or 'Без названия')}</b>\n"
         f"🍽 {D['need']} {pl(D['need'], ('порция', 'порции', 'порций'))} "
         f"({'задано вручную' if manual else 'по числу людей'}) · <b>{money(D['cost'])}</b> · "
         f"{money(D['per_person'])} с человека\n")
    if D["ings"]:
        t += "\n" + "\n".join(_ing_line(i + 1, E) for i, E in enumerate(D["ings"]))
        if any(E["shared"] for E in D["ings"]):
            t += "\n\n<i>Цветная метка: продукт считается вместе с другими блюдами.</i>"
    else:
        t += "\nПродуктов пока нет. Нажмите «Продукт»."
    btns = []
    for i, E in enumerate(D["ings"]):
        mark = (E["G"]["mark"] + " ") if E["shared"] else ""
        btns.append(B(f"{i + 1}. {mark}{short(E['G']['m']['name'], 14)}", f"i:{E['g']['id']}"))
    kb = grid(btns, 2)
    kb += [[B("➕ Продукт", f"ia:{did}"), B("🍽 Порций", f"dp:{did}")],
           [B("✏️ Название", f"dn:{did}"), B("🗑 Удалить", f"dd:{did}")],
           [B("‹ Блюда", "dl")]]
    return t, kb


def _payer_name(S: dict, pid: str) -> str:
    p = find_person(S, pid or "")
    return p["name"] if p else ""


def _find_E(C: dict, iid: str):
    for D in C["dishes"]:
        for E in D["ings"]:
            if E["g"]["id"] == iid:
                return D, E
    return None, None


def scr_ing(S: dict, iid: str) -> Screen:
    f = find_ing(S, iid)
    if not f:
        return scr_menu(S)
    d, g = f
    C = calc(S)
    D, E = _find_E(C, iid)
    G = E["G"]
    m = G["m"]
    u = G["unit"]
    mark = (G["mark"] + " ") if E["shared"] else ""
    per = num(g.get("per"))
    size_s = qty(G["size"], u) if G["size"] > 0 else "—"
    price_s = money(num(m.get("price"))) if num(m.get("price")) > 0 else "—"
    who = _payer_name(S, m.get("payer")) or "не выбран"
    lines = [
        f"🥫 {mark}<b>{h(m['name'] or 'Без названия')}</b>",
        f"🍲 Блюдо: {h(d['name'] or 'Без названия')} · {D['need']} порц.",
        f"⚖️ На 1 порцию: <b>{qty(per, u) if per > 0 else '—'}</b>",
        f"📦 Пачка{' (общая)' if E['linked'] else ''}: <b>{size_s}</b> · 💵 <b>{price_s}</b>",
        f"👤 Покупает: <b>{h(who)}</b>",
    ]
    if E["linked"] or E["deps"] > 0:
        others = ", ".join(h(x["name"] or "Без названия") for x in E["others"]) or "—"
        lines.append(f"🔗 Расчёт вместе с: {mark}{others}")
    else:
        lines.append("🔗 Расчёт вместе с: отдельно")
    lines.append("")
    if E["linked"]:
        lines.append(f"➡️ Нужно {qty(E['need'], u)}, это около {money(E['share'])} из общей пачки.")
    elif G["packs"] > 0:
        tail = (f"запас {qty(G['left'], u)}" if G["left"] > 0.0001 else "впритык") if G["has_size"] else "укажите размер пачки"
        lines.append(f"➡️ <b>{G['packs']} {pl(G['packs'], ('пачка', 'пачки', 'пачек'))} · {money(G['total'])}</b>\n"
                     f"   нужно {qty(G['need_total'], u)}, {tail}")
    else:
        lines.append("➡️ Укажите, сколько нужно на порцию.")
    t = "\n".join(lines)

    kb: Kb = []
    if E["linked"]:
        kb.append([B("⚖️ На порцию", f"iq:{iid}"), B("↗️ Общая пачка", f"i:{m['id']}")])
        kb.append([B("🔗 Расчёт вместе с…", f"il:{iid}")])
    else:
        kb.append([B("✏️ Название", f"in:{iid}"), B("⚖️ На порцию", f"iq:{iid}")])
        kb.append([B("📦 Размер пачки", f"is:{iid}"), B("💵 Цена пачки", f"ip:{iid}")])
        kb.append([B(f"📏 Единица: {u}", f"iu:{iid}"), B("👤 Кто купит", f"py:g:{iid}:i")])
        if E["deps"] == 0 and candidates(S, d):
            kb.append([B("🔗 Расчёт вместе с…", f"il:{iid}")])
    kb.append([B("🗑 Удалить", f"id:{iid}"), B("‹ К блюду", f"d:{d['id']}")])
    return t, kb


def scr_payer(S: dict, kind: str, tid: str, ret: str) -> Screen:
    if kind == "g":
        f = find_ing(S, tid)
        if not f:
            return scr_menu(S)
        cur, title, what = f[1].get("payer"), f[1].get("name"), "купит"
    else:
        x = find_extra(S, tid)
        if not x:
            return scr_menu(S)
        cur, title, what = x.get("payer"), x.get("name"), "оплатил"
    t = f"👤 Кто {what} «{h((title or '').strip() or 'Без названия')}»?"
    btns = [B(("✓ " if p["id"] == cur else "") + short(p["name"], 16), f"sp:{kind}:{tid}:{p['id']}:{ret}")
            for p in S["people"]]
    back = {"i": f"i:{tid}", "x": f"x:{tid}", "u": "su"}[ret]
    return t, grid(btns, 2) + [[B("— Не выбран", f"sp:{kind}:{tid}:-:{ret}")], [B("‹ Назад", back)]]


def scr_link(S: dict, iid: str) -> Screen:
    f = find_ing(S, iid)
    if not f:
        return scr_menu(S)
    d, g = f
    cur = g.get("link") or ""
    t = ("🔗 <b>Расчёт вместе с…</b>\n\nВыберите такой же продукт из другого блюда. Пачки посчитаются вместе, "
         "лишнего не купите. Размер, цена и покупатель берутся из выбранной пачки.")
    kb: Kb = [[B(("✓ " if not cur else "") + "Отдельно", f"sl:{iid}:-:0")]]
    for hh, dd in candidates(S, d):
        kb.append([B(("✓ " if hh["id"] == cur else "") + f"{short(hh['name'], 20)} · {short(dd['name'], 18)}",
                     f"sl:{iid}:{hh['id']}:0")])
    kb.append([B("‹ Назад", f"i:{iid}")])
    return t, kb


def scr_link_offer(S: dict, iid: str, matches: list) -> Screen:
    f = find_ing(S, iid)
    g = f[1]
    t = (f"🔗 «{h(g['name'])}» уже есть в другом блюде. Считать пачку вместе? "
         "Тогда лишнего не купите.")
    kb: Kb = []
    for hh, dd in matches:
        kb.append([B(f"Да, вместе: {short(dd['name'], 24)}", f"sl:{iid}:{hh['id']}:1")])
    kb.append([B("Нет, отдельная пачка", f"sl:{iid}:-:1")])
    return t, kb


# ---- общие траты ---------------------------------------------------------
def scr_extras(S: dict) -> Screen:
    if not S["extras"]:
        t = ("🧂 <b>Общие траты</b>\n\nСюда добавляйте всё, что не входит в блюда и делится на всех поровну: "
             "уголь, напитки, аренда, бензин.")
    else:
        lines = []
        for i, x in enumerate(S["extras"]):
            who = _payer_name(S, x.get("payer"))
            lines.append(f"{i + 1}. {h(x['name'] or 'Без названия')}: {money(num(x.get('sum')))}" + (f" · {h(who)}" if who else " · ⚠️ без плательщика"))
        t = "🧂 <b>Общие траты</b>\n\n" + "\n".join(lines)
    btns = [B(f"{i + 1}. {short(x['name'], 16)}", f"x:{x['id']}") for i, x in enumerate(S["extras"])]
    return t, grid(btns, 2) + [[B("➕ Трата", "xa"), B("‹ Меню", "m")]]


def scr_extra(S: dict, xid: str) -> Screen:
    x = find_extra(S, xid)
    if not x:
        return scr_extras(S)
    who = _payer_name(S, x.get("payer")) or "не выбран"
    t = (f"🧂 <b>{h(x['name'] or 'Без названия')}</b>\n💵 Сумма: <b>{money(num(x.get('sum')))}</b>\n"
         f"👤 Оплатил: <b>{h(who)}</b>")
    kb = [[B("✏️ Название", f"xn:{xid}"), B("💵 Сумма", f"xs:{xid}")],
          [B("👤 Кто оплатил", f"py:x:{xid}:x")],
          [B("🗑 Удалить", f"xd:{xid}"), B("‹ Траты", "xl")]]
    return t, kb


# ---- покупки -------------------------------------------------------------
def shop_items(S: dict, C: dict) -> list[dict]:
    items = []
    for gid in C["order"]:
        G = C["res"][gid]
        if G["used"] and G["packs"] > 0:
            names: list[str] = []
            for r in G["rows"]:
                nm = r["d"]["name"] or "Без названия"
                if r["need"] > 0 and nm not in names:
                    names.append(nm)
            items.append({
                "key": gid, "kind": "g", "payer": G["m"].get("payer") or "",
                "name": (G["m"].get("name") or "").strip() or "Без названия",
                "small": qty(G["size"], G["unit"]) if G["size"] > 0 else "",
                "meta": f"{G['packs']} {pl(G['packs'], ('пачка', 'пачки', 'пачек'))} · " + ", ".join(names),
                "total": G["total"], "mark": G["mark"] if G["shared"] else "",
            })
    for x in S["extras"]:
        v = num(x.get("sum"))
        if not (x.get("name") or "").strip() and v <= 0:
            continue
        items.append({
            "key": x["id"], "kind": "x", "payer": x.get("payer") or "",
            "name": (x.get("name") or "").strip() or "Без названия", "small": "", "meta": "общая трата",
            "total": v, "mark": "",
        })
    return items


def _shop_groups(S: dict, items: list[dict]) -> list[tuple[str, list[dict]]]:
    known = {p["id"] for p in S["people"]}
    groups = []
    loose = [i for i in items if i["payer"] not in known]
    if loose:
        groups.append(("⚠️ Без покупателя", loose))
    for p in S["people"]:
        its = [i for i in items if i["payer"] == p["id"]]
        if its:
            groups.append(("👤 " + p["name"], its))
    return groups


def scr_shop(S: dict, page: int = 0) -> Screen:
    C = calc(S)
    items = shop_items(S, C)
    if not items:
        return ("🧾 <b>Список покупок</b>\n\nПока пусто. Добавьте блюда с продуктами и ценами или общие траты.",
                [[B("🍲 Блюда", "dl"), B("‹ Меню", "m")]])
    groups = _shop_groups(S, items)
    flat = [(gi, it) for gi, (_, its) in enumerate(groups) for it in its]
    pages = max(1, math.ceil(len(flat) / PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = flat[page * PAGE:(page + 1) * PAGE]
    done = sum(1 for it in items if S["bought"].get(it["key"]))
    filled = round(10 * done / len(items))
    t = ["🧾 <b>Список покупок</b>", f"{'▰' * filled}{'▱' * (10 - filled)} куплено {done} из {len(items)}"]
    last = -1
    btns = []
    for idx, (gi, it) in enumerate(chunk):
        if gi != last:
            title, its = groups[gi]
            t.append("")
            t.append(f"<b>{h(title)}</b> · {len(its)} {pl(len(its), ('позиция', 'позиции', 'позиций'))} · "
                     f"{money(sum(x['total'] for x in its))}")
            last = gi
        n = page * PAGE + idx + 1
        ok = bool(S["bought"].get(it["key"]))
        name = f"{it['mark'] + ' ' if it['mark'] else ''}{h(it['name'])}"
        if ok:
            name = f"<s>{name}</s>"
        small = f" <i>{h(it['small'])}</i>" if it["small"] else ""
        t.append(f"{n}. {'✅' if ok else '⬜'} {name}{small} · {h(it['meta'])} · {money(it['total'])}")
        btns.append(B(f"{'✅' if ok else '⬜'} {n}", f"st:{it['key']}:{page}"))
    kb = grid(btns, 4)
    if pages > 1:
        kb.append([
            B("◀", f"sh:{page - 1}") if page > 0 else B("·", "noop"),
            B(f"{page + 1}/{pages}", "noop"),
            B("▶", f"sh:{page + 1}") if page < pages - 1 else B("·", "noop"),
        ])
    if groups and groups[0][0].startswith("⚠️"):
        kb.append([B("👤 Назначить покупателей", "su")])
    kb.append([B("‹ Меню", "m")])
    return "\n".join(t), kb


def scr_unassigned(S: dict) -> Screen:
    C = calc(S)
    loose = [i for i in shop_items(S, C) if i["payer"] not in {p["id"] for p in S["people"]}]
    if not loose:
        return scr_shop(S, 0)
    t = "⚠️ <b>Без покупателя</b>\n\nНажмите на позицию и выберите, кто её купит или оплатил."
    kb = [[B(f"{short(i['name'], 22)} · {money(i['total'])}", f"py:{i['kind']}:{i['key']}:u")] for i in loose]
    kb.append([B("‹ К покупкам", "sh:0")])
    return t, kb


# ---- расчёт --------------------------------------------------------------
def settle_text(S: dict) -> str:
    C = calc(S)
    n = C["n"]
    if not S["dishes"] and not S["extras"]:
        return "💰 <b>Расчёт</b>\n\nПока считать нечего: добавьте блюда и траты."
    t = [f"💰 <b>{h(S['title'] or 'Расчёт закупки')}</b>",
         f"Продукты {money(C['groc'])}" + (f" · траты {money(C['extras_sum'])}" if C["extras_sum"] > 0 else ""),
         f"<b>Итого {money(C['grand'])}</b> · <b>{money(C['grand'] / n if n else 0)}</b> с человека", ""]
    if n == 0:
        t.append("Добавьте участников, чтобы разделить сумму.")
        return "\n".join(t)
    if C["un"]["count"]:
        k = C["un"]["count"]
        t += [f"⚠️ У {k} {pl(k, ('позиции', 'позиций', 'позиций'))} не выбран покупатель "
              f"({money(C['un']['sum'])}), в переводах они не учтены.", ""]
    t.append(f"<b>Кто сколько потратил</b> (доля {money(C['share'])})")
    for r in C["rows"]:
        if r["bal"] > 0:
            tail = f"🟢 получит {money(r['bal'] / 100)}"
        elif r["bal"] < 0:
            tail = f"🔴 отдаст {money(-r['bal'] / 100)}"
        else:
            tail = "✅ в расчёте"
        t.append(f"• {h(r['p']['name'])}: {money(r['paid'])} → {tail}")
    t += ["", "<b>Кто кому переводит</b>"]
    if C["transfers"]:
        t += [f"💸 {h(x['from']['name'])} → {h(x['to']['name'])}: <b>{money(x['amt'] / 100)}</b>" for x in C["transfers"]]
    else:
        t.append("Переводы не нужны, все в расчёте.")
    t += ["", "<b>По блюдам</b>"]
    for D in C["dishes"]:
        t.append(f"🍲 {h(D['d']['name'] or 'Без названия')}: {money(D['cost'])} · {D['need']} порц. · "
                 f"{money(D['per_person'])} с человека · {money(D['per_portion'])} за порцию")
    return "\n".join(t)


def scr_settle(S: dict) -> Screen:
    return settle_text(S), [[B("📤 Отправить в чат", "sx"), B("🔄 Обновить", "se")], [B("‹ Меню", "m")]]


# ---- прочее --------------------------------------------------------------
def scr_more(S: dict) -> Screen:
    t = ("⚙️ <b>Ещё</b>\n\nЭкспорт сохраняет все данные в файл. Его можно загрузить обратно здесь "
         "или на веб-странице калькулятора.")
    kb = [[B("✏️ Название поездки", "mt")],
          [B("📤 Экспорт", "me"), B("📥 Импорт", "mi")],
          [B("🧪 Загрузить пример", "mx"), B("♻️ Начать заново", "mr")],
          [B("❓ Справка", "hp"), B("‹ Меню", "m")]]
    return t, kb


HELP = (
    "🏕 <b>Закупка в поездку</b>\n\n"
    "Бот считает, сколько брать продуктов, сколько это стоит и кто кому должен перевести.\n\n"
    "<b>Как пользоваться</b>\n"
    "1. «Участники»: добавьте всех, кто едет.\n"
    "2. «Блюда»: добавьте блюдо, потом продукты. Для продукта бот спросит, сколько нужно на одну порцию, "
    "какой размер пачки и цену, и сам посчитает пачки с округлением вверх.\n"
    "3. Если продукт нужен в нескольких блюдах, выберите «Расчёт вместе с…»: пачки посчитаются вместе.\n"
    "4. «Общие траты»: уголь, напитки, аренда. Делятся на всех.\n"
    "5. «Покупки»: список с галочками, кто что покупает.\n"
    "6. «Расчёт»: итог и кто кому переводит.\n\n"
    "<b>Ввод чисел</b>\n"
    "Можно писать выражения со скобками: <code>123+12</code>, <code>(2+3)*4</code>, <code>134/234</code>. "
    "С единицами: <code>0,5 кг</code>, <code>1,5 л</code>, <code>2+1 шт</code>. "
    "Знак «-» очищает поле.\n\n"
    "<b>В группе</b>\n"
    "Добавьте бота в чат друзей и отправьте /start. Данные общие для всего чата, нажимать кнопки может любой. "
    "Когда бот просит ввести текст, отвечайте именно на его сообщение (кнопка «Ответить»).\n\n"
    "<b>Команды</b>\n/menu: главное меню · /shop: покупки · /settle: расчёт · /export: файл с данными"
)


# ==========================================================================
# Действия по кнопкам
# ==========================================================================
def _ret_screen(S: dict, ret: str, tid: str) -> Screen:
    if ret == "i":
        return scr_ing(S, tid)
    if ret == "x":
        return scr_extra(S, tid)
    s = scr_unassigned(S)
    return s


def _per_prompt(S: dict, g: dict, wiz: bool) -> Ask:
    m = master(S, g)
    name = (m.get("name") or g.get("name") or "").strip() or "продукта"
    return Ask(
        f"⚖️ Сколько «{h(name)}» нужно на 1 порцию?\nЕдиница сейчас: {m.get('unit') or 'г'}. "
        "Примеры: <code>120</code> · <code>0,5 кг</code> · <code>2+1 шт</code>",
        {"kind": "f_per", "iid": g["id"], "wiz": wiz}, "120 или 0,5 кг")


def _size_prompt(S: dict, g: dict, wiz: bool) -> Ask:
    return Ask(
        f"📦 Какой размер пачки «{h(g['name'])}»?\nПримеры: <code>500</code> · <code>1 кг</code> · "
        "<code>900 мл</code> · <code>10 шт</code>",
        {"kind": "f_size", "iid": g["id"], "wiz": wiz}, "500 или 1 кг")


def _price_prompt(g: dict, wiz: bool) -> Ask:
    return Ask(f"💵 Сколько стоит пачка «{h(g['name'])}», ₽?\nМожно выражение, например <code>99+20</code>.",
               {"kind": "f_price", "iid": g["id"], "wiz": wiz}, "149")


def _sum_prompt(x: dict, wiz: bool) -> Ask:
    return Ask(f"💵 Сколько стоит «{h(x['name'])}», ₽?\nМожно выражение, например <code>450+300</code>.",
               {"kind": "x_sum", "xid": x["id"], "wiz": wiz}, "750")


def act(S: dict, p: list[str], user: dict) -> Out:
    """Обрабатывает нажатие кнопки. p это callback_data, разделённый по ':'."""
    c = p[0]
    a = p[1] if len(p) > 1 else ""

    if c == "noop":
        return Out()
    if c == "m":
        return Out(scr_menu(S))
    if c == "hp":
        return Out((HELP, [[B("‹ Меню", "m")]]))

    # ---- участники
    if c == "pl":
        return Out(scr_people(S))
    if c == "pe":
        return Out(scr_person(S, a))
    if c == "pa":
        return Out(ask=Ask("👥 Кто едет? Напишите имена через запятую или с новой строки.",
                           {"kind": "person_add"}, "Аня, Борис, Вика"))
    if c == "pm":
        if any(x.get("tg") == user["id"] for x in S["people"]):
            return Out(toast="Вы уже в списке")
        S["people"].append({"id": uid(), "name": clean_name(user["name"]) or "Участник", "tg": user["id"]})
        return Out(scr_people(S), toast="Добавил вас")
    if c == "pr":
        pp = find_person(S, a)
        if not pp:
            return Out(scr_people(S))
        return Out(ask=Ask(f"✏️ Новое имя для «{h(pp['name'])}»:", {"kind": "person_ren", "pid": a}, pp["name"]))
    if c == "pd":
        pp = find_person(S, a)
        if not pp:
            return Out(scr_people(S))
        return Out(scr_confirm(f"Удалить участника «{h(pp['name'])}»? Его покупки останутся без покупателя.", f"pdy:{a}", f"pe:{a}"))
    if c == "pdy":
        S["people"] = [x for x in S["people"] if x["id"] != a]
        for d in S["dishes"]:
            for g in d["ings"]:
                if g.get("payer") == a:
                    g["payer"] = ""
        for x in S["extras"]:
            if x.get("payer") == a:
                x["payer"] = ""
        return Out(scr_people(S), toast="Удалён")

    # ---- блюда
    if c == "dl":
        return Out(scr_dishes(S))
    if c == "d":
        return Out(scr_dish(S, a))
    if c == "da":
        return Out(ask=Ask("🍲 Как называется блюдо?", {"kind": "dish_add"}, "Лазанья"))
    if c == "dn":
        d = find_dish(S, a)
        if not d:
            return Out(scr_dishes(S))
        return Out(ask=Ask("✏️ Новое название блюда:", {"kind": "dish_ren", "did": a}, d["name"]))
    if c == "dp":
        d = find_dish(S, a)
        if not d:
            return Out(scr_dishes(S))
        return Out(ask=Ask(f"🍽 Сколько порций нужно? По умолчанию столько же, сколько людей ({len(S['people'])}). "
                           "Можно выражение. Знак «-» вернёт значение по умолчанию.",
                           {"kind": "dish_por", "did": a}, "например 10"))
    if c == "dd":
        d = find_dish(S, a)
        if not d:
            return Out(scr_dishes(S))
        return Out(scr_confirm(f"Удалить блюдо «{h(d['name'])}» со всеми продуктами?", f"ddy:{a}", f"d:{a}"))
    if c == "ddy":
        d = find_dish(S, a)
        if d:
            for g in list(d["ings"]):
                release_ing(S, g)
            S["dishes"].remove(d)
        return Out(scr_dishes(S), toast="Удалено")

    # ---- продукты
    if c == "ia":
        if not find_dish(S, a):
            return Out(scr_dishes(S))
        return Out(ask=Ask("🥫 Как называется продукт?", {"kind": "ing_add", "did": a}, "Фарш говяжий"))
    if c == "i":
        return Out(scr_ing(S, a))
    if c in ("in", "iq", "is", "ip"):
        f = find_ing(S, a)
        if not f:
            return Out(scr_menu(S))
        g = f[1]
        if c == "in":
            return Out(ask=Ask("✏️ Новое название продукта:", {"kind": "f_name", "iid": a}, g["name"]))
        if c == "iq":
            return Out(ask=_per_prompt(S, g, False))
        if g.get("link"):
            return Out(toast="Размер и цена берутся из общей пачки")
        return Out(ask=_size_prompt(S, g, False) if c == "is" else _price_prompt(g, False))
    if c == "iu":
        f = find_ing(S, a)
        if not f:
            return Out(scr_menu(S))
        g = f[1]
        if g.get("link"):
            return Out(toast="Единица берётся из общей пачки")
        set_unit(S, g, UNITS[(UNITS.index(g.get("unit") or "г") + 1) % len(UNITS)])
        return Out(scr_ing(S, a))
    if c == "id":
        f = find_ing(S, a)
        if not f:
            return Out(scr_menu(S))
        extra = " Другие блюда продолжат считать эту пачку вместе." if dependents(S, a) else ""
        return Out(scr_confirm(f"Удалить продукт «{h(f[1]['name'] or 'Без названия')}»?{extra}", f"idy:{a}", f"i:{a}"))
    if c == "idy":
        f = find_ing(S, a)
        if f:
            release_ing(S, f[1])
            f[0]["ings"].remove(f[1])
            return Out(scr_dish(S, f[0]["id"]), toast="Удалено")
        return Out(scr_menu(S))

    # ---- выбор покупателя / плательщика
    if c == "py":
        kind, tid, ret = p[1], p[2], p[3]
        if not S["people"]:
            return Out(toast="Сначала добавьте участников")
        return Out(scr_payer(S, kind, tid, ret))
    if c == "sp":
        kind, tid, pid, ret = p[1], p[2], p[3], p[4]
        pid = "" if pid == "-" else pid
        if kind == "g":
            f = find_ing(S, tid)
            if f:
                f[1]["payer"] = pid
        else:
            x = find_extra(S, tid)
            if x:
                x["payer"] = pid
        return Out(_ret_screen(S, ret, tid))

    # ---- расчёт вместе с
    if c == "il":
        f = find_ing(S, a)
        if not f:
            return Out(scr_menu(S))
        if dependents(S, a):
            return Out(toast="Эту пачку уже используют другие блюда")
        if not candidates(S, f[0]):
            return Out(toast="Нет продуктов в других блюдах")
        return Out(scr_link(S, a))
    if c == "sl":
        iid, mid, wiz = p[1], p[2], p[3] == "1"
        f = find_ing(S, iid)
        if not f:
            return Out(scr_menu(S))
        g = f[1]
        if mid != "-" and (not find_ing(S, mid) or dependents(S, iid)):
            return Out(scr_ing(S, iid), toast="Не получилось связать")
        set_link(S, g, "" if mid == "-" else mid)
        out = Out(scr_ing(S, iid))
        if wiz:
            out.ask = _per_prompt(S, g, True)
        return out

    # ---- общие траты
    if c == "xl":
        return Out(scr_extras(S))
    if c == "x":
        return Out(scr_extra(S, a))
    if c == "xa":
        return Out(ask=Ask("🧂 На что трата? Например: уголь, напитки, аренда.", {"kind": "x_add"}, "Уголь и дрова"))
    if c in ("xn", "xs"):
        x = find_extra(S, a)
        if not x:
            return Out(scr_extras(S))
        if c == "xn":
            return Out(ask=Ask("✏️ Новое название траты:", {"kind": "x_name", "xid": a}, x["name"]))
        return Out(ask=_sum_prompt(x, False))
    if c == "xd":
        x = find_extra(S, a)
        if not x:
            return Out(scr_extras(S))
        return Out(scr_confirm(f"Удалить трату «{h(x['name'] or 'Без названия')}»?", f"xdy:{a}", f"x:{a}"))
    if c == "xdy":
        S["extras"] = [x for x in S["extras"] if x["id"] != a]
        S["bought"].pop(a, None)
        return Out(scr_extras(S), toast="Удалено")

    # ---- покупки
    if c == "sh":
        return Out(scr_shop(S, int(a or 0)))
    if c == "st":
        if S["bought"].get(a):
            S["bought"].pop(a)
        else:
            S["bought"][a] = True
        return Out(scr_shop(S, int(p[2]) if len(p) > 2 else 0))
    if c == "su":
        return Out(scr_unassigned(S))

    # ---- расчёт
    if c == "se":
        return Out(scr_settle(S))
    if c == "sx":
        return Out(send=settle_text(S))

    # ---- прочее
    if c == "mo":
        return Out(scr_more(S))
    if c == "mt":
        return Out(ask=Ask("✏️ Как назвать поездку?", {"kind": "title"}, S["title"] or "Выходные на природе"))
    if c == "me":
        return Out(export=True)
    if c == "mi":
        return Out(ask=Ask("📥 Пришлите файл экспорта (.json) в ответ на это сообщение.", {"kind": "import"}, "файл .json"))
    if c == "mx":
        if S["people"] or S["dishes"] or S["extras"]:
            return Out(scr_confirm("Заменить текущие данные примером?", "mxy", "mo"))
        replace_state(S, example_state())
        return Out(scr_menu(S), toast="Пример загружен")
    if c == "mxy":
        replace_state(S, example_state())
        return Out(scr_menu(S), toast="Пример загружен")
    if c == "mr":
        return Out(scr_confirm("Удалить все данные и начать заново?", "mry", "mo"))
    if c == "mry":
        replace_state(S, blank_state())
        return Out(scr_menu(S), toast="Готово")

    return Out(toast="Эта кнопка устарела, откройте /menu")


def replace_state(S: dict, new: dict) -> None:
    S.clear()
    S.update(new)
    S.setdefault("prompts", {})


# ==========================================================================
# Ответы пользователя на вопросы бота
# ==========================================================================
def reply(S: dict, pr: dict, text: str) -> Out:
    """Применяет текст, присланный в ответ на вопрос бота. Out.err значит, что ввод не принят."""
    k = pr["kind"]
    text = (text or "").strip()

    if k == "person_add":
        names = [clean_name(x) for x in text.replace(";", ",").replace("\n", ",").split(",")]
        names = [x for x in names if x]
        if not names:
            return Out(err="Напишите хотя бы одно имя.")
        for x in names:
            S["people"].append({"id": uid(), "name": x})
        return Out(scr_people(S))
    if k == "person_ren":
        name = clean_name(text)
        pp = find_person(S, pr["pid"])
        if not name:
            return Out(err=NAME_ERR)
        if pp:
            pp["name"] = name
        return Out(scr_person(S, pr["pid"]))

    if k == "title":
        S["title"] = "" if text == "-" else clean_name(text, 60)
        return Out(scr_menu(S))

    if k == "dish_add":
        name = clean_name(text, 60)
        if not name:
            return Out(err=NAME_ERR)
        d = new_dish(name)
        S["dishes"].append(d)
        return Out(scr_dish(S, d["id"]))
    if k == "dish_ren":
        name = clean_name(text, 60)
        d = find_dish(S, pr["did"])
        if not name:
            return Out(err=NAME_ERR)
        if d:
            d["name"] = name
        return Out(scr_dish(S, pr["did"]))
    if k == "dish_por":
        d = find_dish(S, pr["did"])
        if not d:
            return Out(scr_dishes(S))
        if text == "-":
            d["portions"] = ""
        else:
            r = parse_field(text, allow_unit=False)
            if not r["ok"]:
                return Out(err=r["err"])
            d["portions"] = r["value"]
        return Out(scr_dish(S, pr["did"]))

    if k == "ing_add":
        name = clean_name(text, 60)
        d = find_dish(S, pr["did"])
        if not name:
            return Out(err=NAME_ERR)
        if not d:
            return Out(scr_dishes(S))
        g = new_ing(name)
        d["ings"].append(g)
        matches = [(hh, dd) for hh, dd in candidates(S, d) if hh["name"].strip().lower() == name.lower()]
        if matches:
            return Out(scr_link_offer(S, g["id"], matches))
        return Out(scr_ing(S, g["id"]), ask=_per_prompt(S, g, True))
    if k == "f_name":
        name = clean_name(text, 60)
        f = find_ing(S, pr["iid"])
        if not name:
            return Out(err=NAME_ERR)
        if f:
            f[1]["name"] = name
        return Out(scr_ing(S, pr["iid"]))

    if k in ("f_per", "f_size", "f_price"):
        f = find_ing(S, pr["iid"])
        if not f:
            return Out(err="Этот продукт уже удалён.")
        d, g = f
        m = master(S, g)
        linked = m is not g
        if k != "f_per" and linked:
            return Out(err="Размер и цена берутся из общей пачки.")
        if text == "-":
            val, unit = "", None
        else:
            r = parse_field(text, allow_unit=(k != "f_price"))
            if not r["ok"]:
                return Out(err=r["err"])
            val, unit = r["value"], r["unit"]
        if unit and unit != (m.get("unit") or "г"):
            if linked:
                return Out(err=f"В общей пачке единица «{m.get('unit') or 'г'}». Напишите количество в ней.")
            set_unit(S, g, unit)
        if k == "f_per":
            g["per"] = val
        elif k == "f_size":
            g["packSize"] = val
        else:
            g["price"] = val
        if not pr.get("wiz"):
            return Out(scr_ing(S, g["id"]))
        if k == "f_per":
            if linked:
                return Out(scr_ing(S, g["id"]))
            return Out(scr_ing(S, g["id"]), ask=_size_prompt(S, g, True))
        if k == "f_size":
            return Out(scr_ing(S, g["id"]), ask=_price_prompt(g, True))
        if S["people"]:
            return Out(scr_payer(S, "g", g["id"], "i"))
        return Out(scr_ing(S, g["id"]))

    if k == "x_add":
        name = clean_name(text, 60)
        if not name:
            return Out(err=NAME_ERR)
        x = {"id": uid(), "name": name, "sum": "", "payer": ""}
        S["extras"].append(x)
        return Out(scr_extra(S, x["id"]), ask=_sum_prompt(x, True))
    if k == "x_name":
        name = clean_name(text, 60)
        x = find_extra(S, pr["xid"])
        if not name:
            return Out(err=NAME_ERR)
        if x:
            x["name"] = name
        return Out(scr_extra(S, pr["xid"]))
    if k == "x_sum":
        x = find_extra(S, pr["xid"])
        if not x:
            return Out(scr_extras(S))
        if text == "-":
            x["sum"] = ""
        else:
            r = parse_field(text, allow_unit=False)
            if not r["ok"]:
                return Out(err=r["err"])
            x["sum"] = r["value"]
        if pr.get("wiz") and S["people"]:
            return Out(scr_payer(S, "x", x["id"], "x"))
        return Out(scr_extra(S, x["id"]))

    return Out(err="Этот вопрос уже не актуален. Откройте /menu.")
