# Dice verification map

Read `../references/core-principles.md` first. Then load only the recipe for the changed journey. Release status and deferred work live in `docs/dice-feature-map.md`; this directory explains how to prove behavior.

| Journey | Recipe | Main contract |
|---|---|---|
| Find, start, join, and complete a live game | [Live game lifecycle](live-game-lifecycle.md) | A live game is first-class and recoverable |
| Record ordinary play quickly | [Referee scoring](referee-scoring.md) | Common observations are fast, attributed, and undoable |
| Correct mistakes or continue with missing data | [Corrections and gaps](corrections-and-gaps.md) | History changes without inventing observations |
| Record FIFA outcomes | [FIFA](fifa.md) | Goal, teammate catch, and save have distinct mechanics |
| See probability and use Virtual Dice | [Prediction and Virtual Dice](prediction-and-virtual-dice.md) | Enrichment is informative and failure-isolated |
| Compare duo ratings and inspect their evidence | [Duo ratings](duo-ratings.md) | Exact pairs are ranked from completed ranked 2v2 history |
