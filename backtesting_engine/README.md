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
| `ict_strategy.py` | `ICTKillzoneStrategy` : stratégie discrétionnaire "ICT" — ne trade que pendant des fenêtres horaires (`Killzone`), cherche un *liquidity sweep* (mèche au-delà d'un plus haut/bas récent puis clôture à l'intérieur), attend une confirmation de *market structure shift*, et sort en cas d'invalidation ou de fin de killzone. |
| `portfolio.py` | Positions, cash, equity mark-to-market, sizing des ordres, ordres de liquidation totale. |
| `risk_manager.py` | Middleware **entre** la création de l'`OrderEvent` et l'`ExecutionHandler`. Deux coupe-circuits : rate limiter (ordres/minute) et hard drawdown limit (2% depuis l'ouverture) qui émet un `LiquidateEvent`. |
| `execution_handler.py` | `SlippageModel` (impact de marché en racine carrée du taux de participation, pas un chiffre fixe) + `CommissionModel` (pourcentage + minimum), puis génère le `FillEvent`. |
| `forex_cost_models.py` | Équivalents FX : `ForexCommissionModel` (par lot standard, indépendant du prix), `ForexSlippageModel` (pips fixes, avec ajustement JPY), `ForexPositionSizer` (sizing en % du risque par trade selon la distance du stop en pips). Substituables aux modèles génériques (mêmes signatures). |
| `engine.py` | Boucle d'événements principale + **watchdog** : lève `MarketDataStallError` si aucun `MarketEvent` n'a été traité depuis `heartbeat_timeout_seconds`. |

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
