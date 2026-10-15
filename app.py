"""
Boussole des marchés — point d'entrée (menu de navigation entre les 2 pages).
Lancement local : streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Boussole des marchés", page_icon="🧭", layout="wide")

page = st.navigation([
    st.Page("page_etf.py", title="Boussole des ETF", icon="🧭", default=True),
    st.Page("page_meteo.py", title="Météo du risque", icon="🌦️"),
])
page.run()
