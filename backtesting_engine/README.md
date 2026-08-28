# Event-Driven ML Backtesting Engine

Squelette de moteur de backtesting **event-driven** (pas de calcul vectorisé
type `df['signal'] * df['returns']`) pensé pour des stratégies pilotées par
un modèle de Machine Learning, avec gestion des risques stricte et un
modèle de coûts de transaction réaliste.

## Architecture

Tous les composants communiquent uniquement via une file d'événements
(`queue.Queue`) — aucun ne s'appelle directement, ce qui les rend
testables et remplaçables indépendamment.

```
DataHandler --MarketEvent--> Portfolio.update_timeindex + RiskManager.evaluate_portfolio_risk
                                            |
                                            v
                              (breach?) --> LiquidateEvent --> flatten all positions
                                            |
                                            v
                                       Strategy (ML) --SignalEvent--> Portfolio.update_signal
                                            |
                                            v
                                      OrderEvent --> RiskManager.process_order (middleware)
                                            |
                                    (approved) v
                                      ExecutionHandler --FillEvent--> Portfolio.update_fill
```

| Fichier | Responsabilité |
|---|---|
| `event.py` | Tous les types d'événements (`MarketEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `LiquidateEvent`). |
| `data_handler.py` | Alimente la file en `MarketEvent`. `HistoricCSVDataHandler` rejoue des DataFrames pandas ; à remplacer par un flux live sans toucher au reste. |
| `ml_model.py` | `DummyXGBoostSignalModel` : wrapper autour d'un `xgboost.XGBClassifier` (fallback pur Python si `xgboost` est absent), démonstratif uniquement. |
| `strategy.py` | `MLMomentumStrategy` : construit des features glissantes et interroge le modèle ML **de façon asynchrone** (tous les N barres, une fois l'historique suffisant) pour émettre des `SignalEvent`. |
| `ict_strategy.py` | `ICTKillzoneStrategy` : stratégie discrétionnaire "ICT" — ne trade que pendant des fenêtres horaires (`Killzone`), cherche un *liquidity sweep* (mèche au-delà d'un plus haut/bas récent puis clôture à l'intérieur), attend une confirmation de *market structure shift*, et sort en cas d'invalidation ou de fin de killzone. Expose aussi `KillzoneFilter`, partagé avec `ict_2022_strategy.py`. |
| `ict_2022_strategy.py` | `ICT2022Strategy` : version plus stricte à 4 étapes — sweep sur swing **fractal confirmé** (`FractalSwingDetector`, 5 bougies), MSS validé par la **clôture du corps** (jamais une mèche), recherche d'un **Fair Value Gap** (imbalance 3 bougies) une fois le MSS confirmé, puis entrée en attente du retour du prix dans la zone — annulée sans condition si la killzone se termine avant. |
| `portfolio.py` | Positions, cash, equity mark-to-market, sizing des ordres, ordres de liquidation totale. |
| `risk_manager.py` | Middleware **entre** la création de l'`OrderEvent` et l'`ExecutionHandler`. Deux coupe-circuits : rate limiter (ordres/minute) et hard drawdown limit (2% depuis l'ouverture) qui émet un `LiquidateEvent`. |
| `execution_handler.py` | `SlippageModel` (impact de marché en racine carrée du taux de participation, pas un chiffre fixe) + `CommissionModel` (pourcentage + minimum), puis génère le `FillEvent`. |
| `forex_cost_models.py` | Équivalents FX : `ForexCommissionModel` (par lot standard, indépendant du prix), `ForexSlippageModel` (pips fixes, avec ajustement JPY), `ForexPositionSizer` (sizing en % du risque par trade selon la distance du stop en pips). Substituables aux modèles génériques (mêmes signatures). |
| `engine.py` | Boucle d'événements principale + **watchdog** : lève `MarketDataStallError` si aucun `MarketEvent` n'a été traité depuis `heartbeat_timeout_seconds`. |
| `random_baseline_strategy.py` | `RandomKillzoneEntryStrategy` : entrées à pile ou face à l'intérieur des killzones, même sortie/mêmes coûts/même sizing que les stratégies ICT — sert uniquement de référence aléatoire pour `run_thesis_validation.py`. |
| `analytics.py` | `compute_performance_report` : win rate, profit factor, PnL moyen/trade, R moyen, max drawdown à partir des trades clôturés d'un `Portfolio`. Pur post-traitement, n'influence jamais une décision de trading. |
| `examples/real_data.py` | Chargement/nettoyage des trois jeux de données EUR/USD réels bundlés (`data/*.csv`), partagé par `run_real_eurusd_backtest.py` et `run_thesis_validation.py`. |

## Installation

```bash
pip install -r backtesting_engine/requirements.txt
```

`xgboost` est optionnel : s'il n'est pas installé, `ml_model.py` bascule
automatiquement sur un modèle de repli déterministe exposant la même
interface (`predict_proba`), pour que le reste du code n'ait jamais à le
savoir.

## Lancer la démo

```bash
python -m backtesting_engine.examples.run_backtest
```

Le script génère des données OHLCV synthétiques (avec un choc de prix
injecté) et fait tourner le pipeline complet de bout en bout. Il enchaîne
ensuite avec une démonstration déterministe du coupe-circuit de drawdown du
`RiskManager` (le déclenchement pendant le backtest ML dépend de la
position — stochastique — tenue par le modèle factice au moment du choc).

```bash
python -m backtesting_engine.examples.run_ict_backtest
```

Fait tourner `ICTKillzoneStrategy` sur plusieurs jours de données 1-minute
synthétiques EUR/USD, pour exercer chaque killzone (Asie, Londres, New York
AM, London Close) plusieurs fois, avec les modèles de coûts FX
(`ForexCommissionModel`, `ForexSlippageModel`) et un sizing par risque
(`ForexPositionSizer`) au lieu des modèles génériques utilisés par la démo
ML.

> ⚠️ `ICTKillzoneStrategy` implémente une version **simplifiée** d'un
> concept discrétionnaire (ICT) : détection de swing par fenêtre glissante
> plutôt que par pivots fractals confirmés, et l'interprétation "smart
> money" d'une mèche reste subjective. C'est une base solide et testable à
> affiner, pas une stratégie validée ni un edge garanti.

```bash
python -m backtesting_engine.examples.run_ict_2022_backtest
```

Fait tourner `ICT2022Strategy` (le modèle 4 étapes ci-dessus) sur 10 jours
de données 1-minute synthétiques EUR/USD, avec les mêmes modèles de coûts
FX.

> ⚠️ Même avertissement : swing fractal et MSS par clôture sont plus
> rigoureux que la version simple, mais la détection de FVG (3 bougies) et
> son critère de "retour dans la zone" restent des simplifications d'un
> concept discrétionnaire — pas une garantie d'edge.

### Backtest sur données réelles

```bash
python -m backtesting_engine.examples.run_real_eurusd_backtest              # ICT2022Strategy
python -m backtesting_engine.examples.run_real_eurusd_backtest --strategy killzone --dataset 2004_2024
```

Contrairement à tous les autres exemples (données synthétiques), celui-ci
charge de vraies barres EUR/USD historiques, chargées par
`examples/real_data.py`. Trois jeux de données réels sont disponibles
(aucun fournisseur financier habituel — Yahoo Finance, Alpha Vantage,
Stooq, histdata.com, dukascopy.com — n'est joignable depuis cet
environnement : seul `raw.githubusercontent.com` l'est, donc tous
proviennent de dépôts GitHub publics tiers plutôt que d'un vendeur de
données) :

| `--dataset` | Fichier | Période | Barres | Origine / repo GitHub |
|---|---|---|---|---|
| `covid_2020` (défaut) | `EURUSD_H1_2020.csv` | 2020-01-02 → 2020-04-24 (crash COVID) | 1 994 | [`ZTeste/Trady`](https://github.com/ZTeste/Trady), export bid FXCM/ForexConnect |
| `2020_2023` | `EURUSD_H1_2020_2023.csv` | 2020-07-01 → 2023-07-14 | 17 768 | [`JasonZhangjc/automated_trading_with_backtesting`](https://github.com/JasonZhangjc/automated_trading_with_backtesting), export Dukascopy Historical Data Feed |
| `2004_2024` | `EURUSD_H1_2004_2024_raw.csv` | 2004-01-01 → 2024-03-30 | 126 442 (après nettoyage) | [`cerealkode/RL-Algo-Trader`](https://github.com/cerealkode/RL-Algo-Trader), export Dukascopy |

**Vérification d'authenticité** (au-delà de la cohérence interne — pas de
barre le samedi, calendrier FX réel) : le fichier `2020_2023` montre
l'EUR/USD sous la parité (0.957) le 28 septembre 2022, et le fichier
`2004_2024` le montre à 1.137 le 24 juin 2016 (lendemain du vote Brexit)
et à 1.42 en septembre 2008 — trois faits de marché vérifiables qu'un
générateur synthétique ne produirait pas par coïncidence.

**Limites, à connaître avant d'interpréter un résultat :**
- **Granularité horaire (H1), pas 1-minute** : les stratégies ICT sont
  conçues pour de l'intraday fin ; sur H1 les killzones (fenêtres de
  quelques heures) ne contiennent que 2-4 barres chacune, ce qui réduit
  mécaniquement le nombre de setups détectables face à un flux 1-minute.
- **`2004_2024` a été explicitement nettoyé** : le fichier brut pave les
  heures de marché fermé (tout le samedi, quasi tout le dimanche) avec des
  barres OHLC plates à volume nul plutôt que de les omettre (~29% du
  fichier) — `real_data.py` les filtre (`volume > 0`). Son fuseau horaire
  ("Local time", GMT+0800 constant, sans heure d'été) est documenté par la
  source elle-même, contrairement aux deux autres fichiers où l'UTC est
  une hypothèse non vérifiée de notre part.
- **`covid_2020` est bid uniquement** (colonnes `askhigh`/`asklow`
  disponibles dans le fichier mais non utilisées) et sa fenêtre (~4 mois)
  est dominée par un régime de marché atypique (le crash COVID) — trop
  courte et trop spécifique pour en tirer une conclusion statistique
  seule ; c'est pour ça que `2020_2023` et surtout `2004_2024` existent.
- Le spread réel n'est modélisé nulle part explicitement, seul
  `ForexSlippageModel`/`ForexCommissionModel` l'approxime.

### Validation de la thèse : y a-t-il un edge du tout ?

```bash
python -m backtesting_engine.examples.run_thesis_validation
```

Un backtest qui gagne de l'argent une fois ne prouve rien — il faut savoir
si son résultat est meilleur que ce que produirait une entrée au hasard
dans les mêmes conditions. Ce script fait un test de permutation Monte
Carlo léger : il prend le résultat réel de chaque stratégie ICT sur les
données EUR/USD réelles, puis lance `RandomKillzoneEntryStrategy` (entrées
à pile ou face, mêmes killzones, mêmes coûts, même sizing par risque, seul
le "quand entrer" change) 200 fois avec des graines différentes, calibrées
pour produire en moyenne le même nombre de trades que la stratégie réelle.
Si le résultat réel se situe confortablement dans la distribution
aléatoire, son "edge" n'est pas distinguable du bruit sur ces données.

**Résultat sur 20 ans de données réelles (`--dataset 2004_2024`, 126 442 barres H1, 2004-2024) :**

| Stratégie | Trades | Win rate | Profit factor | PnL total | avg R | Max DD | P(aléatoire ≥ réel) |
|---|---|---|---|---|---|---|---|
| `ICTKillzoneStrategy` | 190 | 43.2% | 0.93 | -2316.57 | -0.01 | 7.61% | 0.21 |
| `ICT2022Strategy` | 4 | 25.0% | 0.15 | -4081.69 | -1.02 | 4.77% | 0.91 |

Un `profit_factor < 1` suffit déjà à répondre, indépendamment de toute
comparaison à l'aléatoire : **les deux stratégies perdent de l'argent en
absolu sur 20 ans**, une fois les coûts réalistes appliqués. Le
coupe-circuit de drawdown du `RiskManager` s'est déclenché dans les deux
cas. Aucune des deux ne bat l'entrée aléatoire de façon statistiquement
notable (21% et 91% des tirages aléatoires font aussi bien ou mieux).

> ⚠️ **Limite méthodologique sur la comparaison Monte Carlo** :
> `RandomKillzoneEntryStrategy` ne peut prendre qu'un trade par session de
> killzone (elle ne ressort qu'à la fin de la fenêtre), alors que
> `ICTKillzoneStrategy` peut ré-entrer dans la même session après une
> invalidation. Résultat : la calibration a plafonné à ~47 trades/run en
> moyenne (`p_entry≈0.998`, quasiment "entre à chaque occasion") sans
> jamais atteindre les 190 trades réels — la comparaison n'est donc pas à
> nombre de trades strictement égal pour cette stratégie. Pour
> `ICT2022Strategy`, la cible était si petite (4 trades) que la
> calibration à seulement 8 graines est bruitée (elle a convergé vers
> ~22.8 trades/run). Le `profit_factor < 1` en absolu reste la conclusion
> la plus solide des deux ; le p-value Monte Carlo est indicatif, pas une
> preuve statistique propre, pour ces deux raisons.

C'est la réponse honnête à "trouve la thèse qu'il te faut" : sur 20 ans de
marché réel couvrant de nombreux régimes (2008, 2016 Brexit, 2020 COVID,
2022 parité), **ni la mécanique ICT simple ni la version 2022 ne montrent
un edge** — les deux perdent de l'argent, et rien n'indique que leur
timing d'entrée fait mieux que le hasard. Ce n'est toujours pas une preuve
que ICT ne fonctionne jamais dans l'absolu (une seule paire, un seul
timeframe H1, une seule implémentation mécanique d'un concept
discrétionnaire), mais l'échantillon n'est plus le facteur limitant :
20 ans et 190 trades sont largement suffisants pour un verdict fiable sur
*cette* implémentation, sur *cette* paire, à *cette* granularité.

<details>
<summary>Résultat sur l'ancien échantillon (4 mois de H1, crash COVID) — conservé par transparence</summary>

| Stratégie | Trades | Win rate | Profit factor | PnL total | P(aléatoire ≥ réel) |
|---|---|---|---|---|---|
| `ICTKillzoneStrategy` | 13 | 30.8% | 0.44 | -2083.29 | 0.340 |
| `ICT2022Strategy` | 1 | 0% | 0.00 | -205.72 | 0.870 |

Déjà inconclusif faute de trades (13 et 1) — le résultat sur 20 ans
ci-dessus est strictement plus fiable et le remplace comme réponse de
référence.
</details>

### Sizing par risque (Forex)

`ForexPositionSizer` calcule une taille de position en lots à partir d'un
% du capital risqué par trade et de la distance du stop en pips (formule
"fixed fractional"). `ICTKillzoneStrategy` calcule ce `stop_loss_pips`
automatiquement : le niveau du *sweep* est l'invalidation naturelle du
setup ICT, donc sa distance à l'entrée devient le stop. Branchez le sizer
sur `Portfolio` :

```python
position_sizer = ForexPositionSizer(risk_per_trade_pct=0.01, pip_value_per_standard_lot=10.0)
portfolio = Portfolio(symbol_list=["EURUSD"], initial_capital=100_000.0, position_sizer=position_sizer)
```

`Portfolio` ne dépend que d'un protocole structurel (`PositionSizer` dans
`portfolio.py`) — n'importe quel sizer avec une méthode
`calculate_lot_size(account_equity, stop_loss_pips) -> float` fonctionne,
`ForexPositionSizer` n'est qu'une implémentation possible. Sans sizer
configuré (ou si le signal ne porte pas de `stop_loss_pips`), le
comportement d'origine (`fixed_order_quantity`) est inchangé.

> Les classes génériques `CommissionModel`/`SlippageModel`
> (`execution_handler.py`) n'ont pas été supprimées : elles restent
> utilisées par la démo ML (actions/CFD génériques) et ses tests. Les
> nouvelles classes FX les remplacent uniquement au point d'usage, dans
> la démo ICT — passez-les à `SimulatedExecutionHandler` pour vos propres
> pipelines FX.

## Tests

```bash
python -m unittest discover -s backtesting_engine/tests -v
```

## Points d'extension

- **Données réelles** : implémenter une nouvelle sous-classe de
  `DataHandler` (broker API, websocket, base de données) qui pousse des
  `MarketEvent` — aucune autre classe n'a besoin de changer.
- **Modèle ML réel** : remplacer `DummyXGBoostSignalModel` par un modèle
  entraîné et validé en walk-forward, sérialisé sur disque.
- **Sizing avancé** : remplacer la logique fixe de `Portfolio.update_signal`
  par du sizing par volatilité, Kelly, etc.
- **Exécution réelle** : implémenter une sous-classe d'`ExecutionHandler`
  qui envoie de vrais ordres à un broker (paper ou live).
