"""
Boussole des marchés — « Météo du risque » (indicateurs inspirés de Charles Gave).

Chaque indicateur produit une valeur quotidienne et un état :
  0 = favorable (🟢), 1 = vigilance (🟠), 2 = défavorable (🔴).

Point clé pour un test honnête : les statistiques macro (PIB, inflation...) sont
publiées avec retard. On décale donc chaque série de son délai de publication :
un jour donné, l'app ne « voit » que ce qui était réellement connu ce jour-là.

Gave donne rarement des seuils chiffrés : les seuils ci-dessous sont des choix
raisonnables inspirés de ses règles, pas les siens mot pour mot.
"""

import io
import json
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

JOURS_PAR_AN = 252

# ---------------------------------------------------------------------------
# Sources de données
# ---------------------------------------------------------------------------
# Séries FRED (Réserve fédérale de Saint-Louis), téléchargées sans clé API.
SERIES_FRED = {
    "T10Y3M": "Écart taux 10 ans − 3 mois (US)",
    "DGS10": "Taux 10 ans US",
    "BAA": "Rendement obligations d'entreprises Baa (US)",
    "BAA10Y": "Écart Baa − taux 10 ans (US)",
    "CPIAUCSL": "Indice des prix à la consommation (US)",
    "GDP": "PIB nominal US",
    "GDPC1": "PIB réel US",
    "USALOLITOAASTSAM": "Indicateur avancé OCDE (US)",
}
# Séries Yahoo Finance.
SERIES_YAHOO = {
    "SP500": "^GSPC",
    "GOLD": "GC=F",
    "WTI": "CL=F",
    "VIX": "^VIX",
}
# Délai de publication approximatif (jours) appliqué à chaque série.
DELAIS = {"T10Y3M": 1, "DGS10": 1, "BAA10Y": 1, "BAA": 31, "CPIAUCSL": 45,
          "GDP": 120, "GDPC1": 120, "USALOLITOAASTSAM": 75,
          "SP500": 0, "GOLD": 0, "WTI": 0, "VIX": 0}


def _get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept": "text/csv,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def telecharger_fred_api(code: str, cle_api: str) -> pd.Series:
    """API officielle de FRED (clé gratuite) : la voie la plus fiable."""
    q = urllib.parse.urlencode({"series_id": code, "api_key": cle_api, "file_type": "json"})
    data = json.loads(_get(f"https://api.stlouisfed.org/fred/series/observations?{q}", 30))
    obs = data["observations"]
    s = pd.Series([o["value"] for o in obs], index=pd.to_datetime([o["date"] for o in obs]))
    return pd.to_numeric(s, errors="coerce").dropna()


def telecharger_fred(code: str, timeout: int = 20) -> pd.Series:
    """Téléchargement direct au format CSV (sans clé, mais parfois bloqué depuis le cloud)."""
    df = pd.read_csv(io.BytesIO(_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}",
                                     timeout)))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna()


# Replis Yahoo si FRED est inaccessible (taux uniquement).
REPLIS_YAHOO = {"DGS10": "^TNX", "T10Y3M": ("^TNX", "^IRX")}


# ---------------------------------------------------------------------------
# Définition des indicateurs
# ---------------------------------------------------------------------------
# sens = "bas"  -> c'est dangereux quand la valeur est BASSE
# sens = "haut" -> c'est dangereux quand la valeur est HAUTE
INDICATEURS = {
    "courbe": {
        "nom": "Courbe des taux US (10 ans − 3 mois)",
        "unite": "pts", "sens": "bas", "rouge": 0.0, "orange": 0.5,
        "gave": "Quand les taux courts passent au-dessus des taux longs (courbe inversée), "
                "une récession a suivi à chaque fois depuis 1968 (1974, 1980-82, 1989, 2000, 2007).",
        "lecture": "🔴 si inversée (< 0), 🟠 si presque plate (< 0,5 pt).",
    },
    "wicksell": {
        "nom": "Spread de Wicksell (croissance − coût réel du capital)",
        "unite": "pts", "sens": "bas", "rouge": 0.0, "orange": 1.0,
        "gave": "Si le capital rapporte moins qu'il ne coûte (croissance réelle sous le taux réel "
                "des obligations d'entreprises Baa), l'économie va vers la récession.",
        "lecture": "Croissance réelle du PIB − (taux Baa − inflation moyenne 10 ans). 🔴 si < 0.",
    },
    "allais": {
        "nom": "Règle d'Allais (croissance nominale − taux 10 ans)",
        "unite": "pts", "sens": "bas", "rouge": 0.0, "orange": 1.0,
        "gave": "Les taux longs doivent rester sous la croissance nominale de l'économie ; "
                "au-dessus, la dette devient insoutenable et les actifs souffrent.",
        "lecture": "Croissance du PIB nominal (moy. 1 an) − taux 10 ans. 🔴 si < 0.",
    },
    "actions_or": {
        "nom": "Actions / or vs moyenne 5 ans",
        "unite": "%", "sens": "bas", "rouge": 0.0, "orange": 0.05,
        "gave": "Le S&P 500 mesuré en or traduit la rentabilité du capital. Quand le ratio "
                "passe sous sa moyenne mobile 5 ans, l'or bat les actions : « il faut sortir des actions ».",
        "lecture": "Écart du ratio S&P 500 / or à sa moyenne 5 ans. 🔴 si sous la moyenne.",
    },
    "petrole_or": {
        "nom": "Pétrole / or (variation sur 1 an)",
        "unite": "%", "sens": "haut", "rouge": 0.20, "orange": 0.0,
        "gave": "Le pétrole exprimé en or donne le sens des actions : quand ce rapport monte, "
                "l'énergie coûte plus cher à l'économie, c'est baissier ; quand il baisse, haussier.",
        "lecture": "🔴 si le ratio WTI / or a pris plus de 20 % en un an, 🟠 s'il monte.",
    },
    "credit": {
        "nom": "Écarts de crédit (Baa − État) vs moyenne 1 an",
        "unite": "pts", "sens": "haut", "rouge": 0.5, "orange": 0.2,
        "gave": "Quand les entreprises doivent payer de plus en plus cher pour emprunter "
                "par rapport à l'État, la tension financière monte (signal à surveiller avec le VIX).",
        "lecture": "Hausse de l'écart Baa − 10 ans par rapport à sa moyenne d'un an. 🔴 si > 0,5 pt.",
    },
    "vix": {
        "nom": "VIX (indice de la peur)",
        "unite": "", "sens": "haut", "rouge": 25.0, "orange": 18.0,
        "gave": "Volatilité implicite du S&P 500 : le prix que paient les investisseurs pour se protéger.",
        "lecture": "🔴 au-dessus de 25, 🟠 au-dessus de 18.",
    },
    "oecd": {
        "nom": "Indicateur avancé OCDE (US), variation 12 mois",
        "unite": "pts", "sens": "bas", "rouge": 0.0, "orange": 0.3,
        "gave": "Quand la variation sur 12 mois des indicateurs avancés de l'OCDE devient négative, "
                "une récession a souvent suivi 3 à 6 mois plus tard.",
        "lecture": "🔴 si la variation sur 12 mois est négative.",
    },
}


# Âge maximal (jours) de la dernière donnée avant de considérer la série comme figée.
AGE_MAX = {"courbe": 15, "credit": 15, "vix": 15, "actions_or": 15, "petrole_or": 15,
           "wicksell": 220, "allais": 220, "oecd": 130}


def _aligner(s: pd.Series | None, delai: int, cal: pd.DatetimeIndex) -> pd.Series:
    """Décale une série de son délai de publication puis la recopie jour par jour."""
    if s is None or len(s.dropna()) == 0:
        return pd.Series(np.nan, index=cal)
    s = s.dropna().copy()
    s.index = pd.to_datetime(s.index) + pd.Timedelta(days=delai)
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(cal)).ffill().reindex(cal)


def construire(brut: dict, debut: str = "1995-01-01") -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """À partir des séries brutes, calcule valeurs et états quotidiens.

    Renvoie (valeurs, etats, derniere_donnee) où derniere_donnee donne, pour
    chaque indicateur, la date de la dernière donnée réellement publiée.
    """
    cal = pd.bdate_range(debut, pd.Timestamp.today().normalize())
    g = lambda k: brut.get(k)  # noqa: E731
    A = lambda k, s=None: _aligner(s if s is not None else g(k), DELAIS[k], cal)  # noqa: E731

    v = {}
    # 1. Courbe des taux
    v["courbe"] = A("T10Y3M")

    # 2. Wicksell : croissance réelle − (Baa − inflation moyenne 10 ans)
    if g("BAA") is not None and g("CPIAUCSL") is not None and g("GDPC1") is not None:
        cpi = g("CPIAUCSL").resample("MS").last()
        infl10 = (cpi.pct_change(12) * 100).rolling(120, min_periods=60).mean()
        baa_reel = (g("BAA").resample("MS").last() - infl10).dropna()
        croiss_reelle = (g("GDPC1").pct_change(4) * 100).rolling(4).mean()
        v["wicksell"] = (_aligner(croiss_reelle, DELAIS["GDPC1"], cal)
                         - _aligner(baa_reel, DELAIS["CPIAUCSL"], cal))
    else:
        v["wicksell"] = pd.Series(np.nan, index=cal)

    # 3. Allais : croissance nominale − taux 10 ans
    if g("GDP") is not None:
        croiss_nom = (g("GDP").pct_change(4) * 100).rolling(4).mean()
        v["allais"] = _aligner(croiss_nom, DELAIS["GDP"], cal) - A("DGS10")
    else:
        v["allais"] = pd.Series(np.nan, index=cal)

    # 4 et 5. Ratios avec l'or (marchés, quotidien)
    sp, gold = A("SP500"), A("GOLD")
    wti = g("WTI")
    if wti is not None:
        wti = wti.where(wti > 0)  # le WTI a été négatif le 20/04/2020
    wti = A("WTI", wti)
    ratio_ao = sp / gold
    v["actions_or"] = ratio_ao / ratio_ao.rolling(5 * JOURS_PAR_AN, min_periods=3 * JOURS_PAR_AN).mean() - 1
    ratio_po = wti / gold
    v["petrole_or"] = ratio_po / ratio_po.shift(JOURS_PAR_AN) - 1

    # 6. Crédit
    credit = A("BAA10Y")
    v["credit"] = credit - credit.rolling(JOURS_PAR_AN, min_periods=120).mean()

    # 7. VIX
    v["vix"] = A("VIX")

    # 8. OCDE
    cli = g("USALOLITOAASTSAM")
    v["oecd"] = A("USALOLITOAASTSAM", cli.diff(12) if cli is not None else None)

    # Pour les 4 cadrans : accélération de l'inflation (glissement annuel − celui d'il y a 6 mois)
    if g("CPIAUCSL") is not None:
        cpi = g("CPIAUCSL").resample("MS").last()
        yoy = cpi.pct_change(12) * 100
        v["_inflation"] = _aligner(yoy - yoy.shift(6), DELAIS["CPIAUCSL"], cal)
        v["_inflation_niveau"] = _aligner(yoy, DELAIS["CPIAUCSL"], cal)
    else:
        v["_inflation"] = v["_inflation_niveau"] = pd.Series(np.nan, index=cal)

    valeurs = pd.DataFrame(v)
    etats = pd.DataFrame({k: etat_serie(valeurs[k], k) for k in INDICATEURS})

    # Date de la dernière donnée publiée (pour signaler une série figée)
    sources = {"courbe": ["T10Y3M"], "wicksell": ["BAA", "CPIAUCSL", "GDPC1"],
               "allais": ["GDP", "DGS10"], "actions_or": ["SP500", "GOLD"],
               "petrole_or": ["WTI", "GOLD"], "credit": ["BAA10Y"], "vix": ["VIX"],
               "oecd": ["USALOLITOAASTSAM"]}
    derniere = {}
    for k, codes in sources.items():
        dates = [g(c).dropna().index.max() for c in codes if g(c) is not None and len(g(c).dropna())]
        derniere[k] = min(dates) if len(dates) == len(codes) else None
        # Série arrêtée ou trop ancienne : on n'affiche plus de voyant (⚪)
        if derniere[k] is not None:
            limite = derniere[k] + pd.Timedelta(days=AGE_MAX[k])
            valeurs.loc[valeurs.index > limite, k] = np.nan
            etats.loc[etats.index > limite, k] = np.nan
    return valeurs, etats, derniere


def etat_serie(val: pd.Series, cle: str) -> pd.Series:
    """0 = 🟢, 1 = 🟠, 2 = 🔴, NaN = pas de donnée."""
    d = INDICATEURS[cle]
    if d["sens"] == "bas":
        e = np.where(val < d["rouge"], 2, np.where(val < d["orange"], 1, 0))
    else:
        e = np.where(val > d["rouge"], 2, np.where(val > d["orange"], 1, 0))
    return pd.Series(e, index=val.index, dtype=float).where(val.notna())


def danger(valeurs: pd.DataFrame) -> pd.DataFrame:
    """Version orientée des valeurs : plus c'est haut, plus c'est dangereux."""
    return pd.DataFrame({k: valeurs[k] if INDICATEURS[k]["sens"] == "haut" else -valeurs[k]
                         for k in INDICATEURS})


def nb_rouges(etats: pd.DataFrame) -> pd.Series:
    return (etats == 2).sum(axis=1)


def meteo_globale(n: int) -> tuple[str, str]:
    if n == 0:
        return "☀️", "Beau temps"
    if n == 1:
        return "🌤️", "Quelques nuages"
    if n == 2:
        return "⛅", "Ciel chargé"
    if n == 3:
        return "🌧️", "Pluie"
    return "⛈️", "Orage"


EMOJI_ETAT = {0: "🟢", 1: "🟠", 2: "🔴"}


# ---------------------------------------------------------------------------
# Corrélations avec les ETF
# ---------------------------------------------------------------------------
def _episodes(rouge: pd.Series) -> int:
    """Nombre de fois où l'indicateur est PASSÉ au rouge (épisodes distincts)."""
    r = rouge.fillna(False).astype(bool)
    return int((r & ~r.shift(1, fill_value=False)).sum())


def correlations(prix: pd.Series, valeurs: pd.DataFrame, etats: pd.DataFrame,
                 horizon: int = 63) -> pd.DataFrame:
    """Pour chaque indicateur : que fait l'ETF dans les `horizon` jours qui suivent,
    selon que l'indicateur est rouge ou non ?

    On échantillonne en fin de mois pour ne pas compter 20 fois la même situation.
    """
    prix = prix.dropna()
    fwd = (prix.shift(-horizon) / prix - 1)
    fin_mois = prix.groupby(prix.index.to_period("M")).tail(1).index
    dg = danger(valeurs)
    lignes = []
    etats_ext = etats.copy()
    etats_ext["_global"] = np.where(nb_rouges(etats) >= 2, 2, 0)
    for k in list(INDICATEURS) + ["_global"]:
        e = etats_ext[k].reindex(prix.index, method="ffill")
        e_m, f_m = e.reindex(fin_mois), fwd.reindex(fin_mois)
        ok = e_m.notna() & f_m.notna()
        rouge = ok & (e_m == 2)
        autre = ok & (e_m < 2)
        ligne = {
            "Indicateur": INDICATEURS[k]["nom"] if k in INDICATEURS else "Météo : au moins 2 voyants rouges",
            "Mois testés": int(ok.sum()),
            "Mois en rouge": int(rouge.sum()),
            "Épisodes rouges": _episodes(e.where(e.index >= prix.index[0]) == 2),
            "Rdt moyen si rouge": f_m[rouge].mean() if rouge.any() else np.nan,
            "Rdt moyen sinon": f_m[autre].mean() if autre.any() else np.nan,
            "% de baisse si rouge": (f_m[rouge] < 0).mean() if rouge.any() else np.nan,
        }
        ligne["Écart (rouge − sinon)"] = ligne["Rdt moyen si rouge"] - ligne["Rdt moyen sinon"]
        if k in INDICATEURS:
            d_m = dg[k].reindex(prix.index, method="ffill").reindex(fin_mois)
            ok2 = d_m.notna() & f_m.notna()
            ligne["Corrélation danger ↔ rdt"] = (d_m[ok2].rank().corr(f_m[ok2].rank())
                                                 if ok2.sum() > 12 else np.nan)
        else:
            ligne["Corrélation danger ↔ rdt"] = np.nan
        lignes.append(ligne)
    return pd.DataFrame(lignes).set_index("Indicateur")


# ---------------------------------------------------------------------------
# Les 4 cadrans de Gavekal
# ---------------------------------------------------------------------------
# Axe horizontal : croissance (spread de Wicksell : le capital rapporte-t-il plus qu'il ne coûte ?)
# Axe vertical   : inflation (accélère ou ralentit ?)
QUADRANTS = {
    "boom_desinfl": {"nom": "Boom désinflationniste", "emoji": "🚀",
                     "couleur": "rgba(44,160,44,0.13)",
                     "actifs": "Actions (surtout croissance/tech) et obligations : le meilleur des mondes."},
    "boom_infl": {"nom": "Boom inflationniste", "emoji": "🔥",
                  "couleur": "rgba(255,159,28,0.13)",
                  "actifs": "Actions cycliques et « valeur », matières premières, énergie, immobilier."},
    "recession_infl": {"nom": "Récession inflationniste (stagflation)", "emoji": "🥵",
                       "couleur": "rgba(214,39,40,0.13)",
                       "actifs": "Or, liquidités, matières premières. Actions et obligations souffrent."},
    "recession_defl": {"nom": "Récession déflationniste", "emoji": "🧊",
                       "couleur": "rgba(31,119,180,0.13)",
                       "actifs": "Obligations d'État longues et liquidités. Actions en danger."},
}


def quadrant_de(x: float, y: float) -> str | None:
    if pd.isna(x) or pd.isna(y):
        return None
    if x > 0:
        return "boom_infl" if y > 0 else "boom_desinfl"
    return "recession_infl" if y > 0 else "recession_defl"


def serie_quadrants(valeurs: pd.DataFrame, axe_croissance: str = "wicksell") -> pd.DataFrame:
    """Position mensuelle (fin de mois) dans les 4 cadrans, avec les données connues à la date."""
    m = valeurs[[axe_croissance, "_inflation"]].resample("ME").last().dropna()
    m.columns = ["croissance", "inflation"]
    m["quadrant"] = [quadrant_de(x, y) for x, y in zip(m["croissance"], m["inflation"])]
    return m


def rendements_par_quadrant(prix: pd.Series, quad: pd.DataFrame, horizon: int = 63) -> pd.DataFrame:
    """Rendement moyen de l'ETF dans les `horizon` jours suivant chaque fin de mois, par cadran."""
    prix = prix.dropna()
    fwd = prix.shift(-horizon) / prix - 1
    fin_mois = prix.groupby(prix.index.to_period("M")).tail(1).index
    q = quad["quadrant"].copy()
    q.index = q.index.to_period("M")
    df = pd.DataFrame({"rdt": fwd.reindex(fin_mois).values,
                       "quadrant": q.reindex(fin_mois.to_period("M")).values}, index=fin_mois)
    df = df.dropna()
    lignes = []
    for cle, d in QUADRANTS.items():
        r = df.loc[df["quadrant"] == cle, "rdt"]
        lignes.append({"Cadran": f"{d['emoji']} {d['nom']}", "Mois": len(r),
                       "Rdt moyen": r.mean() if len(r) else np.nan,
                       "% de baisse": (r < 0).mean() if len(r) else np.nan})
    return pd.DataFrame(lignes).set_index("Cadran")
