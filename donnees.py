"""
Boussole des marchés — téléchargement et mise en cache des données (partagé par les 2 pages).
"""

import pandas as pd
import streamlit as st
import yfinance as yf

import meteo as mt


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def telecharger(ticker: str) -> pd.DataFrame:
    """Historique complet en bougies (Open, High, Low, Close ajustés), sans fuseau horaire."""
    hist = yf.Ticker(ticker).history(period="max", auto_adjust=True)
    if hist.empty:
        return pd.DataFrame()
    ohlc = hist[["Open", "High", "Low", "Close"]].dropna()
    ohlc = ohlc[ohlc["Close"] > 0]
    ohlc.index = pd.to_datetime(ohlc.index).tz_localize(None)
    return ohlc


def _yahoo_close(ticker: str) -> pd.Series:
    h = yf.Ticker(ticker).history(period="max", auto_adjust=True)["Close"].dropna()
    h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
    return h


def cle_fred() -> str | None:
    """Clé API FRED, si elle a été ajoutée dans les « Secrets » de Streamlit Cloud."""
    try:
        return st.secrets.get("FRED_API_KEY") or None
    except Exception:  # pas de fichier de secrets
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def series_meteo() -> tuple[dict, dict, dict]:
    """Toutes les séries brutes de la météo du risque.

    Pour chaque série FRED, on essaie dans l'ordre :
      1. l'API officielle de FRED (si une clé gratuite est configurée) ;
      2. le téléchargement CSV direct (2 tentatives) ;
      3. un repli Yahoo Finance pour les taux (10 ans, 3 mois).
    Renvoie (brut, erreurs, sources) : erreurs = message exact par série en échec,
    sources = d'où vient chaque série.
    """
    brut, erreurs, sources = {}, {}, {}
    cle = cle_fred()
    csv_bloque = False  # si le CSV ne répond pas du tout, inutile d'insister 8 fois

    for code in mt.SERIES_FRED:
        msg = []
        if cle:
            try:
                brut[code] = mt.telecharger_fred_api(code, cle)
                sources[code] = "API FRED"
                continue
            except Exception as e:  # noqa: BLE001
                msg.append(f"API : {type(e).__name__} {e}"[:160])
        if not csv_bloque:
            for essai in range(2):
                try:
                    brut[code] = mt.telecharger_fred(code)
                    sources[code] = "FRED (CSV)"
                    break
                except Exception as e:  # noqa: BLE001
                    texte = f"CSV : {type(e).__name__} {e}"[:160]
                    if essai == 1:
                        msg.append(texte)
                        if "timed out" in texte or "URLError" in texte or "403" in texte:
                            csv_bloque = True
            if code in brut:
                continue
        else:
            msg.append("CSV : non tenté (FRED ne répond pas)")
        # Repli Yahoo pour les taux
        repli = mt.REPLIS_YAHOO.get(code)
        if repli:
            def taux(t):  # certains indices de taux ont été cotés ×10 : on ramène en %
                s = _yahoo_close(t)
                return s.where(s <= 20, s / 10)
            try:
                if isinstance(repli, tuple):
                    long_, court = (taux(t) for t in repli)
                    brut[code] = (long_ - court).dropna()
                else:
                    brut[code] = taux(repli)
                sources[code] = "Yahoo (repli)"
                continue
            except Exception as e:  # noqa: BLE001
                msg.append(f"Yahoo : {e}"[:120])
        erreurs[code] = " | ".join(msg)

    for cle_y, ticker in mt.SERIES_YAHOO.items():
        try:
            h = _yahoo_close(ticker)
            if len(h):
                brut[cle_y], sources[cle_y] = h, "Yahoo"
            else:
                erreurs[ticker] = "série vide"
        except Exception as e:  # noqa: BLE001
            erreurs[ticker] = str(e)[:160]
    return brut, erreurs, sources


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def calcul_meteo():
    brut, erreurs, sources = series_meteo()
    valeurs, etats, derniere = mt.construire(brut)
    return valeurs, etats, derniere, erreurs, sources


def vider_cache():
    st.cache_data.clear()
