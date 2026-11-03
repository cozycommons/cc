export function isTiedDuo(duos, duo) {
  return duos.some((other) => other.duo_id !== duo.duo_id && other.rank === duo.rank && duo.rank != null);
}
