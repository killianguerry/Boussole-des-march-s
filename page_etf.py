"""
Page 1 — Boussole des ETF : canal de régression glissant, voyants et backtests.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from boussole import (ETFS, JOURS_PAR_AN, MODES_SORTIE, bornes, canal_glissant, plafond_meteo,
                      comparer_fenetres, stats_apres_signal, strategie, voyant)
from donnees import calcul_meteo, telecharger
import meteo as mt


def en_hebdo(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Regroupe les séances en bougies hebdomadaires (semaine finissant le vendredi)."""
    return ohlc.resample("W-FRI").agg({"Open": "first", "High": "max",
                                       "Low": "min", "Close": "last"}).dropna()


PERIODES = {"6 mois": 0.5, "1 an": 1, "2 ans": 2, "5 ans": 5, "Tout": None}

# ---------------------------------------------------------------------------
# Réglages (barre latérale)
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ Canal")
annees = st.sidebar.slider("Fenêtre de régression (années)", 2.0, 3.0, 2.5, 0.5,
                           help="Longueur de l'historique utilisé pour tracer la droite chaque jour.")
k = st.sidebar.slider("Largeur du canal (écarts-types)", 1.5, 3.0, 2.0, 0.25,
                      help="2 = réglage par défaut de TradingView.")
log = st.sidebar.checkbox("Échelle logarithmique", value=True,
                          help="Recommandé : une hausse de 10 % compte pareil à 100 € ou à 1 000 €.")

st.sidebar.header("📈 Graphique")
periode = st.sidebar.radio("Période affichée", list(PERIODES), index=1, horizontal=True)
unite = st.sidebar.radio("Bougies", ["Journalières", "Hebdomadaires"], horizontal=True)

st.sidebar.header("🎯 Stratégie testée")
type_sortie = st.sidebar.radio(
    "Type de sortie", ["Progressive (par paliers)", "Tout ou rien"],
    help="Progressive : on allège par étapes et on garde un socle, comme Charles Gave. "
         "Tout ou rien : on vend tout au signal, on rachète tout au retour vers le centre.")
progressif = None
mode_sortie = "franchissement"
if type_sortie.startswith("Progressive"):
    pas_pct = st.sidebar.select_slider("Part vendue à chaque palier", [20, 25, 33, 50], value=25,
                                       format_func=lambda v: f"{v} %")
    expo_min_pct = st.sidebar.select_slider("Exposition minimale (socle gardé)", [0, 25, 50, 75],
                                            value=50, format_func=lambda v: f"{v} %",
                                            help="Gave ne descend en général pas sous 50 % d'actions.")
    ecart = st.sidebar.select_slider("Écart entre paliers de vente (écarts-types)",
                                     [0.25, 0.5, 0.75, 1.0], value=0.5,
                                     help=f"Avec 0,5 et un canal à {k:g} : 1er palier à z = {k - 0.5:g}, "
                                          f"2e à {k:g}, 3e à {k + 0.5:g}…")
    rachat_txt = st.sidebar.radio("Rythme de rachat", ["2 semaines", "1 mois", "2 mois"], index=1,
                                  horizontal=True,
                                  help="Une fois le prix revenu vers le centre, on rachète un palier "
                                       "à ce rythme jusqu'à revenir à 100 %.")
    plafond_on = st.sidebar.checkbox(
        "Plafond météo du risque", value=False,
        help="La météo limite l'exposition : 2 voyants rouges → 75 % max, 3 → 50 %, 4+ → 25 %.")
    progressif = {"pas": {33: 1 / 3}.get(pas_pct, pas_pct / 100), "expo_min": expo_min_pct / 100,
                  "ecart_paliers": ecart,
                  "rachat_jours": {"2 semaines": 10, "1 mois": 21, "2 mois": 42}[rachat_txt],
                  "plafond_on": plafond_on}
else:
    mode_sortie = st.sidebar.radio("Vendre...", list(MODES_SORTIE),
                                   format_func=lambda m: MODES_SORTIE[m],
                                   help="« Confirmation » laisse courir la hausse tant que le prix "
                                        "reste au-dessus du canal, et vend quand il retombe dedans.")
z_rachat = st.sidebar.slider("Racheter quand le prix revient à (écarts-types)", -2.0, 1.0, 0.0, 0.25,
                             help="0 = on rachète quand le prix revient sur la droite centrale.")
filtre_n = st.sidebar.selectbox(
    "Filtre météo du risque", [0, 1, 2, 3],
    format_func=lambda n: "Aucun" if n == 0 else f"Vendre seulement si ≥ {n} voyant(s) rouge(s)",
    help="Ne vend au signal du canal que si la météo du risque est mauvaise. "
         "Compare les résultats avec et sans filtre pour voir si ça aide vraiment.")
frais_pct = st.sidebar.number_input("Frais par ordre (%)", 0.0, 1.0, 0.10, 0.05)
frais = frais_pct / 100
fenetre = int(annees * JOURS_PAR_AN)

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("🧭 Boussole des marchés")
st.caption(
    f"Canal de régression glissant sur {annees:g} ans, bornes à {k:g} écarts-types. "
    "Chaque jour, la droite n'utilise que le passé : pas de repaint, les signaux passés "
    "sont ceux que tu aurais vraiment vus en temps réel."
)

# Météo du risque (résumé ; le détail est sur l'autre page)
with st.spinner("Calcul de la météo du risque..."):
    m_valeurs, m_etats, m_derniere, m_erreurs, m_sources = calcul_meteo()
m_nrouges = mt.nb_rouges(m_etats)
autorisation = (m_nrouges >= filtre_n) if filtre_n > 0 else None
if progressif is not None:
    progressif["plafond_meteo"] = plafond_meteo(m_nrouges) if progressif.pop("plafond_on") else None
_dispo = m_etats.iloc[-1].notna()
_emo, _txt = mt.meteo_globale(int(m_nrouges.iloc[-1]))
st.markdown(f"### Météo du risque : {_emo} {_txt} — "
            f"{int(m_nrouges.iloc[-1])} voyant(s) rouge(s) sur {int(_dispo.sum())} "
            "· détail dans la page 🌦️ Météo du risque")

# Téléchargement + calcul pour les 4 ETF (le canal se calcule sur la clôture)
resultats = {}
with st.spinner("Récupération des cours..."):
    for label, info in ETFS.items():
        ohlc = telecharger(info["ticker"])
        if ohlc.empty:
            resultats[label] = None
            continue
        prix = ohlc["Close"]
        resultats[label] = {"ohlc": ohlc, "prix": prix,
                            "canal": canal_glissant(prix, fenetre, log)}

# ---------------------------------------------------------------------------
# Tableau de bord : un voyant par ETF
# ---------------------------------------------------------------------------
colonnes = st.columns(len(ETFS))
for col, (label, info) in zip(colonnes, ETFS.items()):
    with col:
        r = resultats[label]
        st.markdown(f"**{label}**  \n<small>{info['compte']} · {info['ticker']}</small>",
                    unsafe_allow_html=True)
        if r is None:
            st.error(f"Aucune donnée pour {info['ticker']} (ISIN {info['isin']}). "
                     "Corrige le ticker dans boussole.py.")
            continue
        dernier = r["canal"].iloc[-1]
        emoji, titre, detail = voyant(dernier["z"], k)
        st.markdown(f"## {emoji} {titre}")
        st.caption(detail)
        if pd.notna(dernier["z"]):
            haute = bornes(r["canal"].iloc[[-1]], k)["haute"].iloc[0]
            st.metric("Prix", f"{dernier['prix']:.2f} €",
                      f"{dernier['prix'] / haute - 1:+.1%} vs borne haute", delta_color="off")
            st.caption(f"Pente du canal : {dernier['pente_annuelle']:+.0%} / an")

st.markdown("---")


# ---------------------------------------------------------------------------
# Graphique en bougies
# ---------------------------------------------------------------------------
def graphique(r: dict, res: dict) -> go.Figure:
    ohlc, canal = r["ohlc"], r["canal"]
    b = bornes(canal, k)

    # Fenêtre de temps affichée
    if PERIODES[periode] is not None:
        debut = ohlc.index[-1] - pd.DateOffset(months=int(PERIODES[periode] * 12))
        ohlc, b = ohlc[ohlc.index >= debut], b[b.index >= debut]
    else:
        debut = ohlc.index[0]
    bougies = en_hebdo(ohlc) if unite == "Hebdomadaires" else ohlc
    if unite == "Hebdomadaires":
        b = b.resample("W-FRI").last().dropna()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2],
                        vertical_spacing=0.03)
    # Canal (bandes)
    fig.add_trace(go.Scatter(x=b.index, y=b["haute"], name="Borne haute",
                             line=dict(color="rgba(214,69,65,0.8)", width=1.5),
                             hovertemplate="Borne haute : %{y:.2f} €<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=b.index, y=b["basse"], name="Borne basse",
                             line=dict(color="rgba(52,120,198,0.8)", width=1.5),
                             fill="tonexty", fillcolor="rgba(140,140,140,0.07)",
                             hovertemplate="Borne basse : %{y:.2f} €<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=b.index, y=b["centre"], name="Centre",
                             line=dict(color="rgba(120,120,120,0.9)", width=1, dash="dot"),
                             hovertemplate="Centre : %{y:.2f} €<extra></extra>"), row=1, col=1)
    # Bougies
    fig.add_trace(go.Candlestick(x=bougies.index, open=bougies["Open"], high=bougies["High"],
                                 low=bougies["Low"], close=bougies["Close"], name="Cours",
                                 increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)

    # Ordres de la stratégie (taille du triangle = part du portefeuille échangée)
    if res:
        o = res["ordres"]
        o = o[o["Date"] >= debut]
        for nom, symbole, couleur, decal, col_prix in [
            ("Vente", "triangle-down", "#d62728", 1.035, "High"),
            ("Rachat", "triangle-up", "#2ca02c", 0.965, "Low"),
        ]:
            sel = o[o["Action"] == nom]
            if sel.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sel["Date"], y=r["ohlc"][col_prix].reindex(sel["Date"]).values * decal,
                mode="markers", name=nom,
                marker=dict(symbol=symbole, size=8 + 14 * sel["Part échangée"].values, color=couleur,
                            line=dict(color="white", width=1)),
                customdata=sel[["Prix", "Part échangée", "Exposition après"]].values,
                hovertemplate=f"<b>{nom}</b> le %{{x|%d/%m/%Y}}<br>"
                              "Part : %{customdata[1]:.0%} → exposition %{customdata[2]:.0%}<br>"
                              "Clôture : %{customdata[0]:.2f} €<extra></extra>"), row=1, col=1)
        # Exposition au marché (bande du bas)
        expo = res["position"][res["position"].index >= debut]
        fig.add_trace(go.Scatter(x=expo.index, y=expo, name="Exposition", line_shape="hv",
                                 fill="tozeroy", line=dict(color="#7b61ff", width=1.5),
                                 fillcolor="rgba(123,97,255,0.15)",
                                 hovertemplate="Exposition : %{y:.0%}<extra></extra>"), row=2, col=1)

    # Axe du temps lisible
    mois = 12 * (PERIODES[periode] or len(r["ohlc"]) / JOURS_PAR_AN)
    pas = "M1" if mois <= 12 else "M3" if mois <= 30 else "M6" if mois <= 72 else "M12"
    fig.update_xaxes(dtick=pas, tickformat="%m/%Y", showgrid=True,
                     gridcolor="rgba(128,128,128,0.15)", rangeslider_visible=False,
                     rangebreaks=[dict(bounds=["sat", "mon"])] if unite == "Journalières" else [])
    fig.update_yaxes(type="log" if log else "linear", side="right",
                     gridcolor="rgba(128,128,128,0.15)", ticksuffix=" €", row=1, col=1)
    fig.update_yaxes(range=[0, 1.05], tickformat=".0%", side="right", dtick=0.25,
                     gridcolor="rgba(128,128,128,0.15)", title_text="Expo.", row=2, col=1)
    fig.update_layout(height=640, hovermode="x unified", margin=dict(t=10, l=10, r=10),
                      legend=dict(orientation="h", y=-0.12))
    return fig


# ---------------------------------------------------------------------------
# Détail par ETF
# ---------------------------------------------------------------------------
onglets = st.tabs([*ETFS.keys(), "📊 Comparer les fenêtres"])

for onglet, (label, info) in zip(onglets[:-1], ETFS.items()):
    with onglet:
        r = resultats[label]
        if r is None:
            st.warning("Pas de données.")
            continue
        prix, canal = r["prix"], r["canal"]
        st.subheader(info["nom"])
        st.caption(f"ISIN {info['isin']} · historique depuis le {prix.index[0]:%d/%m/%Y} "
                   f"({len(prix) / JOURS_PAR_AN:.1f} ans)")
        if len(prix) < fenetre + 60:
            st.warning("Historique trop court pour cette fenêtre : réduis-la ou attends.")
            continue

        res = strategie(canal, k, z_rachat, frais, mode_sortie, autorisation, progressif)
        st.plotly_chart(graphique(r, res), width="stretch")
        st.caption("▼ rouge = vente, ▲ vert = rachat (plus le triangle est gros, plus la part échangée "
                   "est grande), exécutés à la clôture du lendemain du signal. En bas : la part du "
                   "portefeuille investie. "
                   "Le canal est recalculé chaque jour avec le passé seul (pas de repaint).")

        # --- Stratégie complète ---
        st.markdown("#### Stratégie : alléger en haut du canal, racheter au retour vers le centre"
                    if progressif else
                    "#### Stratégie : vendre en haut du canal, racheter au retour vers le centre")
        if res:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Perf/an stratégie", f"{res['cagr_strat']:+.1%}",
                      f"{res['cagr_strat'] - res['cagr_bh']:+.1%} vs achat-conservation")
            c2.metric("Perf/an achat-conservation", f"{res['cagr_bh']:+.1%}")
            c3.metric("Pire chute stratégie", f"{res['dd_strat']:.0%}",
                      f"achat-cons. : {res['dd_bh']:.0%}", delta_color="off")
            c4.metric("Exposition moyenne" if progressif else "Temps investi",
                      f"{res['temps_investi']:.0%}",
                      f"{res['nb_ordres']} ordres en {res['annees']:.1f} ans", delta_color="off")
            st.line_chart(res["courbes"])

            if progressif:
                o = res["ordres"].copy()
                if not o.empty:
                    st.markdown("**Journal des ordres**")
                    o["Date"] = o["Date"].dt.strftime("%d/%m/%Y")
                    st.dataframe(o.style.format({
                        "Part échangée": "{:.0%}", "Exposition avant": "{:.0%}",
                        "Exposition après": "{:.0%}", "Prix": "{:.2f} €"}),
                        width="stretch", hide_index=True)
                    st.caption("Chaque ligne = un palier. La part échangée est exprimée en "
                               "proportion du portefeuille total.")
            # Journal des allers-retours (tout ou rien)
            ventes, rachats = ([], []) if progressif else (list(res["ventes"]), list(res["rachats"]))
            lignes = []
            for v in ventes:
                apres = [a for a in rachats if a > v]
                a = apres[0] if apres else None
                pv, pa = prix.loc[v], (prix.loc[a] if a is not None else prix.iloc[-1])
                lignes.append({"Vente": v.strftime("%d/%m/%Y"), "Prix vente": pv,
                               "Rachat": a.strftime("%d/%m/%Y") if a is not None else "en cours",
                               "Prix rachat": pa,
                               "Semaines dehors": ((a or prix.index[-1]) - v).days / 7,
                               "Gain de l'aller-retour": pv / pa - 1})
            if lignes:
                st.markdown("**Journal des allers-retours**")
                st.dataframe(pd.DataFrame(lignes).style.format({
                    "Prix vente": "{:.2f} €", "Prix rachat": "{:.2f} €",
                    "Semaines dehors": "{:.0f}", "Gain de l'aller-retour": "{:+.1%}"}),
                    width="stretch", hide_index=True)
                st.caption("Gain positif = tu as racheté moins cher que tu n'as vendu. "
                           "Négatif = le marché a continué de monter pendant que tu étais dehors.")

        # --- Que se passe-t-il après un signal rouge ? ---
        with st.expander("Statistiques : après un franchissement de la borne haute, le prix baisse-t-il ?"):
            stats = stats_apres_signal(canal, k)
            st.dataframe(stats.style.format({
                "Nb de signaux": "{:.0f}",
                "Rendement moyen après signal": "{:+.1%}",
                "Rendement moyen (tous les jours)": "{:+.1%}",
                "% de signaux suivis d'une baisse": "{:.0%}",
                "Pire baisse moyenne après signal": "{:+.1%}",
                "Pire baisse moyenne (tous les jours)": "{:+.1%}",
            }, na_rep="—"), width="stretch")
            n3 = stats.loc["3 mois", "Nb de signaux"]
            if n3 < 10:
                st.info(f"Seulement {n3} signaux : trop peu pour conclure.")
            st.caption("La colonne « tous les jours » est la référence : un signal n'est utile que si "
                       "ce qui suit est nettement pire que ce qui suit un jour quelconque.")

# ---------------------------------------------------------------------------
# Comparaison des fenêtres 2 / 2,5 / 3 ans
# ---------------------------------------------------------------------------
with onglets[-1]:
    st.subheader("Quelle fenêtre fonctionne le mieux ?")
    st.caption("Mêmes règles, seule la longueur de la fenêtre change. Méfie-toi de choisir "
               "la meilleure a posteriori : si les écarts sont faibles, c'est du bruit.")
    for label, info in ETFS.items():
        r = resultats[label]
        if r is None:
            continue
        tab = comparer_fenetres(r["prix"], [2.0, 2.5, 3.0], k, log, z_rachat, frais, mode_sortie,
                                autorisation, progressif)
        st.markdown(f"**{label}**")
        if tab.empty:
            st.caption("Historique trop court.")
            continue
        st.dataframe(tab.style.format({
            "Signaux rouges": "{:.0f}",
            "Rdt 3 mois après signal": "{:+.1%}", "Rdt 3 mois (référence)": "{:+.1%}",
            "Perf/an stratégie": "{:+.1%}", "Perf/an achat-conservation": "{:+.1%}",
            "Pire chute stratégie": "{:.0%}", "Pire chute achat-cons.": "{:.0%}",
        }, na_rep="—"), width="stretch")

st.markdown("---")
st.caption("Outil d'aide à la réflexion, pas un conseil en investissement. Données Yahoo Finance "
           "(peuvent avoir des trous ou un jour de retard). Rendements passés ≠ rendements futurs.")
