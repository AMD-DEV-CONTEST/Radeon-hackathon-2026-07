#!/usr/bin/env python3
"""
Moteur de workflow 2SIN - l'ossature souveraine.
Lit un workflow declaratif (JSON), execute des primitives decouplees dans l'ordre,
avec boucle pilotee (0/1/2/3 passes selon complexite) et branchements par condition.
Le moteur ne SAIT rien du metier : il orchestre des primitives via un registre.
"""
import re, time
try:
    from primitives.trace import tracer as _TRACER
except Exception:
    try:
        from trace import tracer as _TRACER
    except Exception:
        _TRACER = None

class Moteur:
    def __init__(self, registre):
        self.registre = registre  # { "nom_primitive": fonction(entree, ctx) -> sortie }

    def _resoudre(self, valeur, ctx):
        if isinstance(valeur, str) and valeur.startswith("$"):
            cur = ctx
            for part in valeur[1:].split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            return cur
        if isinstance(valeur, list):
            return [self._resoudre(v, ctx) for v in valeur]
        return valeur

    def _condition_simple(self, cond, ctx):
        m = re.match(r'\s*([\w\.]+)\s*(==|!=)\s*(\S+)\s*', cond)
        if not m:
            return True
        chemin, op, attendu = m.groups()
        cur = ctx
        for part in chemin.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        val = str(cur)
        return (val == attendu) if op == "==" else (val != attendu)

    def _condition_ok(self, cond, ctx):
        if not cond:
            return True
        # Conjonction "&&", disjonction "||" et PARENTHESES. Sans elles, une
        # condition comme "A && (B || C)" etait mal evaluee -- le moteur decoupait
        # a plat et ignorait le groupement.
        return self._evaluer(cond.strip(), ctx)

    def _evaluer(self, expr, ctx):
        expr = expr.strip()
        if not expr:
            return True
        # Un groupe qui enveloppe TOUTE l'expression peut etre retire.
        while expr.startswith("(") and expr.endswith(")") and self._equilibre(expr[1:-1]):
            expr = expr[1:-1].strip()
        # Decoupe au niveau 0 de parenthese : disjonction d'abord (moins liante).
        for sep, combineur in (("||", any), ("&&", all)):
            parties = self._decouper(expr, sep)
            if len(parties) > 1:
                return combineur(self._evaluer(p, ctx) for p in parties)
        return self._condition_simple(expr, ctx)

    @staticmethod
    def _equilibre(s):
        n = 0
        for ch in s:
            n += (ch == "(") - (ch == ")")
            if n < 0:
                return False
        return n == 0

    @staticmethod
    def _decouper(expr, sep):
        """Decoupe sur sep, en ignorant ce qui est entre parentheses."""
        parties, courant, prof, i = [], "", 0, 0
        while i < len(expr):
            ch = expr[i]
            if ch == "(":
                prof += 1
            elif ch == ")":
                prof -= 1
            if prof == 0 and expr[i:i + len(sep)] == sep:
                parties.append(courant.strip())
                courant = ""
                i += len(sep)
                continue
            courant += ch
            i += 1
        parties.append(courant.strip())
        return [p for p in parties if p]

    def executer(self, workflow, contexte_initial):
        ctx = dict(contexte_initial)
        trace = []
        complexite = ctx.get("complexite", "simple")
        passes = {"triviale":1, "simple":1, "moyenne":2, "complexe":3}.get(complexite, 1)

        for p in range(passes):
            ctx["_passe"] = p + 1
            for etape in workflow["etapes"]:
                cond = etape.get("condition")
                if not self._condition_ok(cond, ctx):
                    trace.append(("SKIP", etape["id"], cond))
                    continue
                prim = etape["primitive"]
                fn = self.registre.get(prim)
                if not fn:
                    trace.append(("ERR", etape["id"], "primitive inconnue: "+prim))
                    continue
                entree = self._resoudre(etape.get("entree"), ctx)
                t0 = time.time()
                sortie = fn(entree, ctx)
                dt = time.time() - t0
                # Trace de debogage, eteinte par defaut (TRACE_PRIMITIVES=1).
                # Le moteur trace pour TOUTES les primitives : aucune n'a besoin
                # d'etre instrumentee, et le contrat reste intact.
                if _TRACER is not None:
                    _TRACER(prim, entree=entree, sortie=sortie, duree=dt,
                            etape=etape["id"])
                if "sortie" in etape:
                    ctx[etape["sortie"]] = sortie
                trace.append(("OK", etape["id"], prim, "%.3fs" % dt))
                # ARRET DU FLUX : une primitive de garde (firewall) peut stopper net.
                # Convention : sortie dict avec _arret=True -> aucune etape suivante.
                if isinstance(sortie, dict) and sortie.get("_arret"):
                    ctx["_arrete_par"] = etape["id"]
                    ctx["_arret_message"] = sortie.get("message", "")
                    trace.append(("ARRET", etape["id"], "flux stoppe par garde"))
                    ctx["_trace"] = trace
                    return ctx
            if ctx.get("complexite", "simple") in ("triviale", "simple"):
                break
        ctx["_trace"] = trace
        return ctx
