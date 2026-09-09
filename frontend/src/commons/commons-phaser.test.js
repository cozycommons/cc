import { describe, expect, it } from 'vitest';
import { sortCommonsEntities } from './commons-phaser.js';

describe('Commons renderer ordering', () => {
  it('uses stable entity keys instead of snapshot insertion order', () => {
    const first = sortCommonsEntities([
      { entityType: 'actor', id: 'host' },
      { entityType: 'object', id: 'dining-table' },
      { entityType: 'actor', id: 'maker' },
    ]);
    const second = sortCommonsEntities([
      { entityType: 'actor', id: 'maker' },
      { entityType: 'actor', id: 'host' },
      { entityType: 'object', id: 'dining-table' },
    ]);

    expect(first.map((entity) => `${entity.entityType}:${entity.id}`)).toEqual([
      'actor:host',
      'actor:maker',
      'object:dining-table',
    ]);
    expect(second.map((entity) => `${entity.entityType}:${entity.id}`)).toEqual(
      first.map((entity) => `${entity.entityType}:${entity.id}`),
    );
  });
});
