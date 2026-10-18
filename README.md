# 🧭 Boussole des marchés — V1

Un voyant par ETF, basé sur un canal de régression linéaire **glissant** (sans repaint),
et un backtest qui vérifie si le voyant rouge annonce vraiment une baisse.

## Fichiers
| Fichier | Rôle |
|---|---|
| `app.py` | Point d'entrée : le menu qui mène aux 2 pages. |
| `page_etf.py` | Page 🧭 Boussole des ETF (canal, voyants, stratégie). |
| `page_meteo.py` | Page 🌦️ Météo du risque (indicateurs Gave, 4 cadrans, corrélations). |
| `donnees.py` | Téléchargement des données (Yahoo, FRED) et cache. |
| `boussole.py` | Les calculs du canal et des backtests. C'est ici qu'on change les ETF/tickers. |
| `meteo.py` | Les calculs de la météo du risque et des 4 cadrans. |
| `requirements.txt` | Les bibliothèques à installer. |

## Mise en ligne (sans rien installer sur ton ordi)
1. Sur GitHub : **New repository** → nom `boussole-marches` → *Public* → *Create*.
2. **Add file → Upload files** → dépose les 8 fichiers → *Commit changes*.
3. Sur [share.streamlit.io](https://share.streamlit.io) : connecte ton compte GitHub →
   **Create app** → choisis le dépôt, branche `main`, fichier `app.py` → *Deploy*.
4. **Clé FRED (recommandé, gratuit)** : crée un compte sur fredaccount.stlouisfed.org →
   *API Keys* → *Request API Key*. Puis sur Streamlit Cloud : ton app → ⋮ → *Settings* →
   *Secrets* → colle `FRED_API_KEY = "ta_cle"` → *Save*. Sans clé, l'app tente un
   téléchargement direct, souvent bloqué depuis le cloud.
5. Au bout de 1-2 minutes, l'app est en ligne. Pour la mettre à jour, modifie
   un fichier sur GitHub : Streamlit redéploie tout seul.

## Lire l'app
- 🔴 **Au-dessus du canal** : le prix dépasse la borne haute (z ≥ 2 par défaut).
- 🟠 **Haut du canal** : entre +1 et +2 écarts-types.
- 🟢 **Dans le canal** · 🔵 **Bas du canal**.
- **z** = écart du prix à la droite, en écarts-types.
- Sur le graphique en bougies : ▼ rouge = vente, ▲ vert = rachat (une seule vente par épisode).
- **Sorties progressives** (par défaut) : on allège par paliers de 25 % quand le prix monte
  dans le haut du canal, sans descendre sous un socle de 50 %, puis on rachète un palier par
  mois une fois le prix revenu au centre. Option : la météo du risque plafonne l'exposition.
  La bande violette sous le graphique montre la part investie.
- En mode « tout ou rien », deux façons de vendre, à comparer dans la barre latérale : **dès le franchissement** de la
  borne haute, ou **par confirmation** (on laisse courir tant que le prix reste au-dessus,
  on vend quand il retombe dans le canal).
- Le tableau « après un voyant rouge » compare toujours avec la **référence** (n'importe quel
  jour). Un signal n'a de valeur que s'il fait nettement mieux que la référence.

## Météo du risque (page 🌦️)
8 indicateurs inspirés de Charles Gave, sources gratuites (FRED et Yahoo Finance) :
courbe des taux US 10 ans − 3 mois, spread de Wicksell, règle d'Allais, actions/or vs moyenne
5 ans, pétrole/or, écarts de crédit, VIX, indicateur avancé de l'OCDE.
- Les séries macro sont décalées de leur délai de publication : pas de triche dans les tests.
- Une série qui n'est plus mise à jour s'affiche ⚪ au lieu d'un faux voyant.
- Le tableau de corrélations montre, pour chaque ETF, ce qui s'est passé après les périodes rouges.
- **Les 4 cadrans de Gavekal** : croissance (spread de Wicksell) × inflation (accélère ou
  ralentit), avec la trajectoire des 24 derniers mois et le rendement de chaque ETF par cadran.
- Le **filtre météo** (barre latérale de la page ETF) ne vend au signal du canal que si la météo est mauvaise.

## Premier lancement : à vérifier
- Si un ETF affiche « Aucune donnée », corriger son ticker dans `ETFS` (en haut de `boussole.py`).
  Le ticker du Nasdaq (`PUST.PA`) est le seul non confirmé en ligne.
- Le Japon (`PTPXE.PA`) n'a qu'environ 7 ans d'historique : peu de signaux, résultats fragiles.

## Idées pour la V2
- Tester la méthode sur les indices sous-jacents (historique plus long).
- Alertes (e-mail/Telegram) quand un voyant change de couleur.
- Volet macro (taux, courbe des taux) façon Charles Gave.

*Outil d'aide à la réflexion, pas un conseil en investissement.*
