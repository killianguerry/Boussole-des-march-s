"""
Page 2 — Météo du risque : indicateurs inspirés de Charles Gave, les 4 cadrans de Gavekal,
et leur lien avec tes ETF.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from boussole import ETFS
from donnees import calcul_meteo, cle_fred, telecharger, vider_cache
import meteo as mt

# ---------------------------------------------------------------------------
# Barre latérale
# ---------------------------------------------------------------------------
st.sidebar.header("🌦️ Météo du risque")
if st.sidebar.button("🔄 Recharger les données", help="Vide le cache et retélécharge tout."):
    vider_cache()
    st.rerun()
log = st.sidebar.checkbox("Échelle logarithmique (graphiques ETF)", value=True)

# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------
with st.spinner("Calcul de la météo du risque..."):
    m_valeurs, m_etats, m_derniere, m_erreurs, m_sources = calcul_meteo()
m_nrouges = mt.nb_rouges(m_etats)
dispo = m_etats.iloc[-1].notna()
emo, txt = mt.meteo_globale(int(m_nrouges.iloc[-1]))

st.title("🌦️ Météo du risque")
st.markdown(f"## {emo} {txt} — {int(m_nrouges.iloc[-1])} voyant(s) rouge(s) sur {int(dispo.sum())}")
st.caption("Indicateurs macro et de marché inspirés de Charles Gave (Institut des Libertés, "
           "Gavekal). Ils sont presque tous américains : l'économie US donne le ton aux marchés "
           "mondiaux. Gave donne rarement des seuils chiffrés : ceux-ci sont des choix raisonnables "
           "inspirés de ses règles. Les données macro sont décalées de leur délai de publication "
           "pour que les tests restent honnêtes.")

# ---------------------------------------------------------------------------
# Diagnostic des sources
# ---------------------------------------------------------------------------
fred_ko = [c for c in m_erreurs if c in mt.SERIES_FRED]
if fred_ko:
    st.warning(f"{len(fred_ko)} série(s) FRED non récupérée(s) : {', '.join(fred_ko)}. "
               "Les indicateurs concernés sont grisés.")
    if not cle_fred():
        st.info(
            "**Solution la plus fiable : une clé API FRED gratuite (2 minutes).**\n\n"
            "1. Crée un compte sur [fredaccount.stlouisfed.org](https://fredaccount.stlouisfed.org/login/secure/) "
            "puis va dans **API Keys → Request API Key** (motif : « projet personnel »).\n"
            "2. Sur [share.streamlit.io](https://share.streamlit.io), ouvre ton app → **⋮ → Settings → Secrets**, "
            "et colle la ligne : `FRED_API_KEY = \"ta_cle_ici\"` puis **Save**.\n"
            "3. Clique sur **🔄 Recharger les données** dans la barre latérale.")
with st.expander("Détail des sources de données"):
    lignes = [{"Série": c, "Description": mt.SERIES_FRED.get(c, c),
               "Source": m_sources.get(c, "❌"), "Erreur": m_erreurs.get(c, "")}
              for c in list(mt.SERIES_FRED) + list(mt.SERIES_YAHOO)]
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Voyants
# ---------------------------------------------------------------------------
st.markdown("### Les voyants")
lignes = []
for cle, d in mt.INDICATEURS.items():
    val, et = m_valeurs[cle].iloc[-1], m_etats[cle].iloc[-1]
    if pd.isna(val):
        txt_val = "—"
    elif d["unite"] == "%":
        txt_val = f"{val:+.1%}"
    else:
        txt_val = f"{val:+.2f} {d['unite']}".strip()
    der = m_derniere.get(cle)
    lignes.append({"": mt.EMOJI_ETAT.get(et, "⚪"), "Indicateur": d["nom"], "Valeur": txt_val,
                   "Donnée du": der.strftime("%d/%m/%Y") if der is not None else "—",
                   "Lecture": d["lecture"]})
st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")
st.caption("⚪ = donnée indisponible ou plus mise à jour. « Donnée du » = date de la dernière "
           "publication : le PIB n'est publié que tous les trimestres, avec un mois de retard.")
with st.expander("Ce que dit Charles Gave de chaque indicateur"):
    for d in mt.INDICATEURS.values():
        st.markdown(f"**{d['nom']}** — {d['gave']}")

# ---------------------------------------------------------------------------
# Les 4 cadrans
# ---------------------------------------------------------------------------
st.markdown("### Les 4 cadrans de Gavekal")
st.caption("Le cadre de Charles Gave et Gavekal pour choisir quoi détenir. Axe horizontal : la "
           "**croissance**, mesurée par le spread de Wicksell (le capital rapporte-t-il plus qu'il "
           "ne coûte ?). Axe vertical : l'**inflation**, qui accélère ou ralentit (glissement annuel "
           "des prix comparé à celui d'il y a 6 mois). Chaque cadran favorise des actifs différents.")

quad = mt.serie_quadrants(m_valeurs, "wicksell")
if quad.empty:
    st.info("Les 4 cadrans ont besoin des séries FRED (PIB, inflation, taux Baa). "
            "Ils s'afficheront dès qu'elles seront récupérées.")
else:
    actuel = quad.iloc[-1]
    q_act = mt.QUADRANTS[actuel["quadrant"]]
    c1, c2 = st.columns([3, 2])
    with c1:
        recent = quad.iloc[-24:]
        base = quad.iloc[-120:]
        ex = max(abs(base["croissance"]).max(), 0.5) * 1.15
        ey = max(abs(base["inflation"]).max(), 0.5) * 1.15
        fig = go.Figure()
        for cle, (x0, x1, y0, y1) in {"boom_desinfl": (0, ex, -ey, 0), "boom_infl": (0, ex, 0, ey),
                                      "recession_infl": (-ex, 0, 0, ey),
                                      "recession_defl": (-ex, 0, -ey, 0)}.items():
            d = mt.QUADRANTS[cle]
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=d["couleur"],
                          line_width=0, layer="below")
            fig.add_annotation(x=(x0 + x1) / 2, y=y1 - (y1 - y0) * 0.08 if y1 > 0 else y0 + (y1 - y0) * 0.08,
                               text=f"{d['emoji']} {d['nom']}", showarrow=False,
                               font=dict(size=12, color="rgba(80,80,80,0.95)"))
        n = len(recent)
        fig.add_trace(go.Scatter(
            x=recent["croissance"], y=recent["inflation"], mode="lines+markers",
            line=dict(color="rgba(90,90,90,0.5)", width=1.5),
            marker=dict(size=[5 + 6 * i / max(n - 1, 1) for i in range(n)],
                        color=list(range(n)), colorscale="Greys", cmin=-n * 0.3, cmax=n),
            customdata=recent.index.strftime("%m/%Y"),
            hovertemplate="%{customdata}<br>Croissance : %{x:+.2f}<br>Inflation : %{y:+.2f}<extra></extra>",
            name="24 derniers mois"))
        fig.add_trace(go.Scatter(
            x=[actuel["croissance"]], y=[actuel["inflation"]], mode="markers+text",
            marker=dict(symbol="star", size=22, color="#7b61ff", line=dict(color="white", width=1.5)),
            text=["Aujourd'hui"], textposition="top center", name="Aujourd'hui",
            hovertemplate="Aujourd'hui<br>Croissance : %{x:+.2f}<br>Inflation : %{y:+.2f}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color="rgba(100,100,100,0.6)", width=1))
        fig.add_vline(x=0, line=dict(color="rgba(100,100,100,0.6)", width=1))
        fig.update_xaxes(range=[-ex, ex], title="← récession · Croissance (spread de Wicksell, pts) · boom →",
                         zeroline=False)
        fig.update_yaxes(range=[-ey, ey], title="← désinflation · Inflation · inflation →",
                         zeroline=False)
        fig.update_layout(height=520, showlegend=False, margin=dict(t=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")
    with c2:
        st.metric("Cadran actuel", f"{q_act['emoji']} {q_act['nom']}")
        st.markdown(f"**Ce qui marche en général :** {q_act['actifs']}")
        depuis = quad["quadrant"].ne(quad["quadrant"].shift()).cumsum()
        mois_dans = int((depuis == depuis.iloc[-1]).sum())
        st.caption(f"Depuis {mois_dans} mois dans ce cadran (données à fin "
                   f"{quad.index[-1]:%m/%Y}). La trajectoire grise montre les 24 derniers mois : "
                   "le sens du déplacement compte autant que la position.")
        st.markdown("**Les 4 cadrans**")
        for d in mt.QUADRANTS.values():
            st.markdown(f"{d['emoji']} **{d['nom']}** — {d['actifs']}")

    # Frise historique
    histo = quad[quad.index >= "2000-01-01"]
    fig = go.Figure()
    for cle, d in mt.QUADRANTS.items():
        sel = histo[histo["quadrant"] == cle]
        fig.add_trace(go.Bar(x=sel.index, y=[1] * len(sel), name=f"{d['emoji']} {d['nom']}",
                             marker_color=d["couleur"].replace("0.13", "0.85"), width=31 * 86400000,
                             hovertemplate="%{x|%m/%Y}<extra>" + d["nom"] + "</extra>"))
    fig.update_layout(barmode="overlay", height=150, bargap=0, margin=dict(t=10, l=10, r=10, b=10),
                      yaxis=dict(visible=False), legend=dict(orientation="h", y=-0.35))
    st.markdown("**Historique des cadrans depuis 2000**")
    st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Historique du nombre de voyants rouges
# ---------------------------------------------------------------------------
st.markdown("### Nombre de voyants rouges dans le temps")
st.area_chart(m_nrouges[m_nrouges.index >= "2000-01-01"].resample("W-FRI").last(), height=200)


# ---------------------------------------------------------------------------
# Tes ETF face à la météo
# ---------------------------------------------------------------------------
def spans_rouges(etat: pd.Series):
    """Périodes continues où l'indicateur est rouge -> liste (début, fin)."""
    r = (etat == 2)
    debuts = r.index[r & ~r.shift(1, fill_value=False)]
    fins = r.index[r & ~r.shift(-1, fill_value=False)]
    return list(zip(debuts, fins))


st.markdown("### Tes ETF face à la météo")
prix_etf_tous = {}
for label, info in ETFS.items():
    o = telecharger(info["ticker"])
    if not o.empty:
        prix_etf_tous[label] = o["Close"]

if not prix_etf_tous:
    st.warning("Aucun cours d'ETF récupéré.")
    st.stop()

c1, c2 = st.columns(2)
etf_choisi = c1.selectbox("ETF", list(prix_etf_tous))
horizon_txt = c2.radio("Horizon", ["3 mois", "6 mois"], horizontal=True)
horizon = 63 if horizon_txt == "3 mois" else 126
prix_etf = prix_etf_tous[etf_choisi]

st.markdown("#### Les indicateurs annoncent-ils les baisses ?")
corr = mt.correlations(prix_etf, m_valeurs, m_etats, horizon)
st.dataframe(corr.style.format({
    "Mois testés": "{:.0f}", "Mois en rouge": "{:.0f}", "Épisodes rouges": "{:.0f}",
    "Rdt moyen si rouge": "{:+.1%}", "Rdt moyen sinon": "{:+.1%}",
    "% de baisse si rouge": "{:.0%}", "Écart (rouge − sinon)": "{:+.1%}",
    "Corrélation danger ↔ rdt": "{:+.2f}",
}, na_rep="—").background_gradient(subset=["Écart (rouge − sinon)"], cmap="RdYlGn",
                                    vmin=-0.1, vmax=0.1), width="stretch")
st.caption(
    f"Chaque fin de mois, on regarde si l'indicateur était rouge, puis ce qu'a fait l'ETF dans les "
    f"{horizon_txt} suivants. Un indicateur est utile si l'**écart** est nettement négatif et si la "
    "**corrélation** est négative (plus le danger est élevé, plus le rendement suivant est faible). "
    "⚠️ Regarde le nombre d'**épisodes rouges** : avec 1 ou 2 épisodes, un bon résultat peut n'être "
    "qu'une coïncidence (une seule crise comme 2020 ou 2022 suffit à tout faire pencher).")

if not quad.empty:
    st.markdown("#### Rendement de l'ETF selon le cadran")
    rq = mt.rendements_par_quadrant(prix_etf, quad, horizon)
    st.dataframe(rq.style.format({"Mois": "{:.0f}", "Rdt moyen": "{:+.1%}", "% de baisse": "{:.0%}"},
                                 na_rep="—"), width="stretch")
    st.caption(f"Rendement moyen sur les {horizon_txt} qui suivent une fin de mois passée dans chaque "
               "cadran. Si l'ETF fait nettement moins bien dans un cadran, c'est le moment où le "
               "réduire. Peu de mois = résultat fragile.")

st.markdown("#### Sur le graphique")
ind = st.selectbox("Indicateur à superposer", list(mt.INDICATEURS),
                   format_func=lambda c: mt.INDICATEURS[c]["nom"])
debut = prix_etf.index[0]
val = m_valeurs[ind][m_valeurs.index >= debut]
et = m_etats[ind][m_etats.index >= debut]
d = mt.INDICATEURS[ind]
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.05)
fig.add_trace(go.Scatter(x=prix_etf.index, y=prix_etf, name=etf_choisi,
                         line=dict(color="#333", width=1.4)), row=1, col=1)
fig.add_trace(go.Scatter(x=val.index, y=val, name=d["nom"],
                         line=dict(color="#7b61ff", width=1.4)), row=2, col=1)
for seuil, coul in [(d["rouge"], "#d62728"), (d["orange"], "#ff9f1c")]:
    fig.add_hline(y=seuil, line=dict(color=coul, width=1, dash="dash"), row=2, col=1)
for a, b in spans_rouges(et):
    fig.add_vrect(x0=a, x1=b, fillcolor="rgba(214,39,40,0.12)", line_width=0)
fig.update_yaxes(type="log" if log else "linear", row=1, col=1)
if d["unite"] == "%":
    fig.update_yaxes(tickformat=".0%", row=2, col=1)
fig.update_xaxes(tickformat="%m/%Y")
fig.update_layout(height=520, showlegend=False, margin=dict(t=10, l=10, r=10), hovermode="x unified")
st.plotly_chart(fig, width="stretch")
st.caption("Zones rouges = périodes où l'indicateur était défavorable. Regarde si les baisses de "
           "l'ETF tombent dedans… ou ailleurs.")

st.info("💡 Pour tester ces indicateurs dans la stratégie, va sur la page **🧭 Boussole des ETF** "
        "et utilise le **filtre météo du risque** dans la barre latérale.")
st.markdown("---")
st.caption("Outil d'aide à la réflexion, pas un conseil en investissement.")
