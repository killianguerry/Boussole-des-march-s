"""
Boussole des marchés — logique de calcul (sans interface).

Principe : pour chaque jour, on trace une droite de régression linéaire
sur les N derniers jours UNIQUEMENT (jamais sur le futur). On mesure
ensuite l'écart du prix à cette droite en nombre d'écarts-types (z-score).
  z = +2  -> le prix touche la borne haute d'un canal à 2 écarts-types
  z =  0  -> le prix est sur la droite centrale
  z = -2  -> le prix touche la borne basse
Contrairement au canal TradingView, ce calcul ne "repeint" pas :
la valeur d'un jour passé ne change jamais quand de nouvelles données arrivent.
"""

import numpy as np
import pandas as pd

JOURS_PAR_AN = 252  # nombre moyen de séances de bourse par an

# Les 4 ETF suivis. Si un ticker ne renvoie rien, c'est ici qu'il faut le corriger.
ETFS = {
    "Nasdaq-100": {"ticker": "PUST.PA", "isin": "FR0011871110",
                   "nom": "Amundi PEA Nasdaq-100", "compte": "PEA"},
    "Japon (TOPIX)": {"ticker": "PTPXE.PA", "isin": "FR0013411980",
                      "nom": "Amundi PEA Japon (TOPIX)", "compte": "PEA"},
    "Banques zone euro": {"ticker": "BNKE.PA", "isin": "LU1829219390",
                          "nom": "Amundi Euro Stoxx Banks", "compte": "PEA"},
    "Asie émergente": {"ticker": "AASI.PA", "isin": "LU1681044480",
                       "nom": "Amundi MSCI Em Asia", "compte": "CTO"},
}


# ---------------------------------------------------------------------------
# 1. Le canal de régression glissant
# ---------------------------------------------------------------------------
def canal_glissant(prix: pd.Series, fenetre: int, log: bool = True) -> pd.DataFrame:
    """Calcule, pour chaque jour, la régression sur les `fenetre` jours précédents.

    Renvoie un tableau avec : prix, centre, borne_haute/borne_basse (à 1 écart-type,
    on multiplie ensuite par k), z (écart en écarts-types) et pente_annuelle.
    Le calcul utilise des sommes glissantes : c'est exactement une régression
    des moindres carrés, mais calculée d'un coup pour tous les jours.
    """
    y = np.log(prix) if log else prix.astype(float)
    W = fenetre
    i = pd.Series(np.arange(len(y), dtype=float), index=y.index)

    # Sommes glissantes sur la fenêtre
    Sy = y.rolling(W).sum()
    Siy = (y * i).rolling(W).sum()
    Syy = (y * y).rolling(W).sum()

    # Dans chaque fenêtre, x va de 0 à W-1
    Sx = W * (W - 1) / 2
    Sxx = (W - 1) * W * (2 * W - 1) / 6
    debut = i - W + 1
    Sxy = Siy - debut * Sy

    pente = (Sxy - Sx * Sy / W) / (Sxx - Sx ** 2 / W)
    ordonnee = (Sy - pente * Sx) / W
    centre = ordonnee + pente * (W - 1)          # valeur de la droite au dernier jour

    residus2 = (Syy - ordonnee * Sy - pente * Sxy).clip(lower=0)
    ecart_type = np.sqrt(residus2 / (W - 2))
    z = (y - centre) / ecart_type

    if log:
        pente_annuelle = np.exp(pente * JOURS_PAR_AN) - 1
    else:
        pente_annuelle = pente * JOURS_PAR_AN / centre

    return pd.DataFrame({
        "prix": prix,
        "centre": centre,
        "ecart_type": ecart_type,
        "z": z,
        "pente_annuelle": pente_annuelle,
        "log": log,
    })


def bornes(canal: pd.DataFrame, k: float) -> pd.DataFrame:
    """Convertit le centre ± k écarts-types en prix (pour le graphique)."""
    c, s = canal["centre"], canal["ecart_type"]
    if bool(canal["log"].iloc[0]):
        return pd.DataFrame({"centre": np.exp(c),
                             "haute": np.exp(c + k * s),
                             "basse": np.exp(c - k * s)})
    return pd.DataFrame({"centre": c, "haute": c + k * s, "basse": c - k * s})


# ---------------------------------------------------------------------------
# 2. Le voyant
# ---------------------------------------------------------------------------
def voyant(z: float, k: float) -> tuple[str, str, str]:
    """Renvoie (emoji, libellé, explication) selon la position dans le canal."""
    if np.isnan(z):
        return "⚪", "Pas assez d'historique", "La fenêtre n'est pas encore remplie."
    if z >= k:
        return "🔴", "Au-dessus du canal", f"Le prix dépasse la borne haute ({z:+.2f} écarts-types)."
    if z >= 1:
        return "🟠", "Haut du canal", f"Le prix approche la borne haute ({z:+.2f} écarts-types)."
    if z > -k:
        return "🟢", "Dans le canal", f"Zone normale ({z:+.2f} écarts-types)."
    return "🔵", "Bas du canal", f"Le prix est sous la borne basse ({z:+.2f} écarts-types)."


# ---------------------------------------------------------------------------
# 3. Backtest du signal : que se passe-t-il après un voyant rouge ?
# ---------------------------------------------------------------------------
HORIZONS = {"1 mois": 21, "3 mois": 63, "6 mois": 126}


def evenements_rouges(canal: pd.DataFrame, k: float) -> pd.Series:
    """Jours où le prix FRANCHIT la borne haute (on ne compte qu'une fois
    un même épisode, pas chaque jour passé au-dessus)."""
    au_dessus = canal["z"] >= k
    return au_dessus & ~au_dessus.shift(1, fill_value=False)


def stats_apres_signal(canal: pd.DataFrame, k: float) -> pd.DataFrame:
    """Compare ce qui se passe après un voyant rouge à ce qui se passe
    en moyenne n'importe quel jour (la référence honnête)."""
    prix = canal["prix"]
    valide = canal["z"].notna()
    ev = evenements_rouges(canal, k) & valide
    lignes = []
    for nom, h in HORIZONS.items():
        rendement = prix.shift(-h) / prix - 1
        # pire baisse sur la période suivante (par rapport au prix du signal)
        min_futur = prix[::-1].rolling(h, min_periods=1).min()[::-1].shift(-1)
        baisse_max = min_futur / prix - 1
        connu = rendement.notna()
        r_sig = rendement[ev & connu]
        r_ref = rendement[valide & connu]
        lignes.append({
            "Horizon": nom,
            "Nb de signaux": int(len(r_sig)),
            "Rendement moyen après signal": r_sig.mean(),
            "Rendement moyen (tous les jours)": r_ref.mean(),
            "% de signaux suivis d'une baisse": (r_sig < 0).mean() if len(r_sig) else np.nan,
            "Pire baisse moyenne après signal": baisse_max[ev & connu].mean(),
            "Pire baisse moyenne (tous les jours)": baisse_max[valide & connu].mean(),
        })
    return pd.DataFrame(lignes).set_index("Horizon")


# ---------------------------------------------------------------------------
# 4. Backtest de la stratégie complète : vendre en haut, racheter au centre
# ---------------------------------------------------------------------------
MODES_SORTIE = {
    "franchissement": "Dès que le prix franchit la borne haute",
    "retour": "Quand le prix retombe sous la borne haute (confirmation)",
}

# Réglages par défaut des sorties progressives (esprit Charles Gave : on allège
# par paliers, on garde un socle, et on revient par étapes).
PROGRESSIF_DEFAUT = {
    "pas": 0.25,          # part vendue (ou rachetée) à chaque palier
    "expo_min": 0.5,      # exposition plancher : on ne descend jamais en dessous
    "ecart_paliers": 0.5, # écart entre deux paliers de vente, en écarts-types
    "rachat_jours": 21,   # délai minimal entre deux rachats (21 séances ≈ 1 mois)
    "plafond_meteo": None,  # série optionnelle : exposition maximale permise par la météo
}


def _alignee(serie: pd.Series | None, index: pd.DatetimeIndex, defaut):
    """Recopie une série jour par jour sur l'index du canal (valeur par défaut si absente)."""
    if serie is None:
        return np.full(len(index), defaut, dtype=float)
    return serie.reindex(index, method="ffill").astype(float).fillna(defaut).values


def _resultats(c: pd.DataFrame, position: pd.Series, frais: float) -> dict:
    """Performance d'une exposition (0 à 1) appliquée au prix. Les frais sont
    proportionnels à la part du portefeuille échangée. L'argent sorti ne rapporte rien."""
    ret = c["prix"].pct_change().fillna(0)
    variation = position.diff().fillna(0)
    ret_strat = position * ret - variation.abs() * frais

    courbe_strat = (1 + ret_strat).cumprod()
    courbe_bh = (1 + ret).cumprod()
    annees = len(c) / JOURS_PAR_AN

    def perf(courbe):
        cagr = courbe.iloc[-1] ** (1 / annees) - 1
        dd = (courbe / courbe.cummax() - 1).min()
        return cagr, dd

    cagr_s, dd_s = perf(courbe_strat)
    cagr_b, dd_b = perf(courbe_bh)
    chg = variation[variation != 0]
    ordres = pd.DataFrame({
        "Date": chg.index,
        "Action": np.where(chg.values < 0, "Vente", "Rachat"),
        "Part échangée": chg.abs().values,
        "Exposition avant": position.shift(1).reindex(chg.index).values,
        "Exposition après": position.reindex(chg.index).values,
        "Prix": c["prix"].reindex(chg.index).values,
    })
    return {
        "courbes": pd.DataFrame({"Stratégie canal": courbe_strat,
                                 "Achat-conservation": courbe_bh}),
        "position": position,
        "annees": annees,
        "cagr_strat": cagr_s, "dd_strat": dd_s,
        "cagr_bh": cagr_b, "dd_bh": dd_b,
        "nb_ordres": int(len(chg)),
        # dates d'exécution des ordres (pour le graphique)
        "ventes": chg.index[chg.values < 0],
        "rachats": chg.index[chg.values > 0],
        "ordres": ordres,
        "temps_investi": position.mean(),  # exposition moyenne
    }


def strategie(canal: pd.DataFrame, k: float, z_rachat: float = 0.0,
              frais: float = 0.001, mode_sortie: str = "franchissement",
              autorisation: pd.Series | None = None,
              progressif: dict | None = None) -> dict:
    """Règle « tout ou rien » (par défaut) :
      - investi par défaut ;
      - sortie, selon `mode_sortie` :
          "franchissement" : dès que z >= k ;
          "retour"         : le prix est passé au-dessus de la borne haute, puis
                             retombe dessous (on laisse courir la hausse et on
                             ne vend qu'au premier signe d'essoufflement) ;
      - rachat quand le prix redescend à z <= z_rachat.
    Si `progressif` est fourni (voir PROGRESSIF_DEFAUT), on passe aux sorties
    progressives : voir `_progressive`.
    `autorisation` (optionnel) : série vrai/faux par date. Si fournie, on ne vend
    au signal du canal que les jours où elle est vraie (ex. : météo mauvaise).
    Les ordres sont exécutés à la clôture du LENDEMAIN du signal : pas de triche.
    `frais` = coût d'un ordre, en proportion du montant échangé (0.001 = 0,1 %).
    """
    c = canal.dropna(subset=["z"])
    if len(c) < 30:
        return {}
    z = c["z"].values
    ok = _alignee(autorisation, c.index, 1.0).astype(bool)  # sans météo : pas de filtre

    if progressif is not None:
        pos = _progressive(z, ok, k, z_rachat, c.index, {**PROGRESSIF_DEFAUT, **progressif})
    else:
        pos = np.empty(len(z))
        investi, arme = 1.0, False
        for t in range(len(z)):
            if investi:
                if mode_sortie == "retour":
                    if z[t] >= k:
                        arme = True
                    elif arme and z[t] < k and ok[t]:
                        investi, arme = 0.0, False
                elif z[t] >= k and ok[t]:
                    investi = 0.0
            elif z[t] <= z_rachat:
                investi = 1.0
            pos[t] = investi
    position = pd.Series(pos, index=c.index).shift(1).fillna(1.0)  # exécution J+1
    return _resultats(c, position, frais)


def _progressive(z, ok, k, z_rachat, index, p: dict) -> np.ndarray:
    """Sorties et rachats par paliers.

    Ventes : paliers de z centrés sur la borne haute, par ex. pour k = 2 et un écart de 0,5 :
      z >= 1,5 -> on allège d'un pas ; z >= 2 -> d'un 2e pas ; z >= 2,5 -> d'un 3e...
      sans jamais descendre sous l'exposition plancher.
    Rachats : quand le prix revient vers le centre (z <= z_rachat), on rachète un pas,
      puis un pas de plus tous les `rachat_jours` tant que le prix ne remonte pas
      dans la zone de vente. On revient donc à 100 % par étapes, comme Gave.
    Plafond météo (optionnel) : l'exposition ne peut pas dépasser le plafond du jour.
    """
    pas, expo_min = p["pas"], p["expo_min"]
    n_max = int(round((1 - expo_min) / pas))
    paliers = [k - p["ecart_paliers"] + i * p["ecart_paliers"] for i in range(max(n_max, 1))]
    plafond = _alignee(p.get("plafond_meteo"), index, 1.0)

    expo, dernier_ordre, en_rachat = 1.0, -10 ** 9, False
    pos = np.empty(len(z))
    for t in range(len(z)):
        # 1. Ventes par paliers (signal du canal, si la météo l'autorise)
        niveau = sum(z[t] >= s for s in paliers[:n_max])
        cible = max(expo_min, round(1 - niveau * pas, 6))
        if cible < expo - 1e-9 and ok[t]:
            expo, dernier_ordre, en_rachat = cible, t, False
        # 2. Rachats par paliers
        elif expo < 1 - 1e-9:
            if z[t] <= z_rachat:
                en_rachat = True
            if z[t] >= paliers[0]:
                en_rachat = False
            if en_rachat and t - dernier_ordre >= p["rachat_jours"]:
                expo, dernier_ordre = min(1.0, round(expo + pas, 6)), t
        # 3. Plafond imposé par la météo du risque
        if expo > plafond[t] + 1e-9:
            expo, dernier_ordre = plafond[t], t
        pos[t] = expo
    return pos


def plafond_meteo(nb_rouges: pd.Series, paliers: dict | None = None) -> pd.Series:
    """Exposition maximale selon le nombre de voyants rouges de la météo du risque.
    Par défaut : 2 rouges -> 75 %, 3 -> 50 %, 4 ou plus -> 25 %."""
    paliers = paliers or {2: 0.75, 3: 0.5, 4: 0.25}
    cap = pd.Series(1.0, index=nb_rouges.index)
    for n, plaf in sorted(paliers.items()):
        cap[nb_rouges >= n] = plaf
    return cap


def comparer_fenetres(prix: pd.Series, annees_list, k, log, z_rachat, frais,
                      mode_sortie: str = "franchissement",
                      autorisation: pd.Series | None = None,
                      progressif: dict | None = None) -> pd.DataFrame:
    """Résumé pour plusieurs longueurs de fenêtre (ex. 2, 2,5 et 3 ans)."""
    lignes = []
    for a in annees_list:
        W = int(a * JOURS_PAR_AN)
        if len(prix) < W + 60:
            continue
        cn = canal_glissant(prix, W, log)
        st = stats_apres_signal(cn, k)
        res = strategie(cn, k, z_rachat, frais, mode_sortie, autorisation, progressif)
        lignes.append({
            "Fenêtre": f"{a:g} ans",
            "Signaux rouges": int(st.loc["3 mois", "Nb de signaux"]),
            "Rdt 3 mois après signal": st.loc["3 mois", "Rendement moyen après signal"],
            "Rdt 3 mois (référence)": st.loc["3 mois", "Rendement moyen (tous les jours)"],
            "Perf/an stratégie": res.get("cagr_strat", np.nan),
            "Perf/an achat-conservation": res.get("cagr_bh", np.nan),
            "Pire chute stratégie": res.get("dd_strat", np.nan),
            "Pire chute achat-cons.": res.get("dd_bh", np.nan),
        })
    return pd.DataFrame(lignes).set_index("Fenêtre") if lignes else pd.DataFrame()
