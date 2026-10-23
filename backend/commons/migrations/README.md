# Retired Commons room migration history

The Commons room frontend and API have been removed. These migrations and their
schema contract remain unchanged because historical Dice readiness migrations
require the Commons schema and migration receipts. The shared migration runner
still replays and verifies this family for fresh installations and upgrades.

Do not edit or renumber these files or drop their database objects without a
forward migration that removes the Dice readiness dependency first.
