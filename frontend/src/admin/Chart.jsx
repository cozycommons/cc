import React from 'react';
import { DataRow } from '../design/system/DataPatterns.jsx';

const COLORS = ['var(--moss-dark)', 'var(--clay)', 'var(--blue-dusk)', 'var(--amber)', 'var(--walnut)', 'var(--moss)', 'var(--clay-light)', 'var(--espresso)'];
export default function Chart({ result, config }) {
  if (!result?.rows.length) return <p>No data</p>;
  const { rows, columns } = result;
  const table = <div className="admin-table"><table><thead><tr>{columns.map((col) => <th key={col}>{col}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((col) => <td key={col}>{row[col] == null ? '—' : typeof row[col] === 'object' ? JSON.stringify(row[col]) : String(row[col])}</td>)}</tr>)}</tbody></table></div>;
  if (config.type === 'table') return table;
  if (!columns.includes(config.x) || !config.y.length || config.y.some((col) => !columns.includes(col) || rows.some((row) => row[col] != null && typeof row[col] !== 'number')) || (config.series && !columns.includes(config.series))) {
    return <><p role="alert">Choose an X column and numeric Y columns.</p>{table}</>;
  }
  const keys = [];
  const grouped = new Map();
  rows.forEach((row) => {
    const key = row[config.x];
    if (!grouped.has(key)) grouped.set(key, { [config.x]: key });
    config.y.forEach((col) => {
      const series = config.series ? `${row[config.series]} · ${col}` : col;
      if (!keys.includes(series)) keys.push(series);
      grouped.get(key)[series] = row[col];
    });
  });
  const data = [...grouped.values()];
  const width = 680, height = 280, left = 48, right = 16, top = 16, bottom = 44;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const values = data.flatMap((row) => keys.map((key) => row[key])).filter((v) => typeof v === 'number');
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const y = (value) => top + (max - value) / (max - min) * plotHeight;
  const x = (index) => left + (index + .5) / data.length * plotWidth;
  const barWidth = Math.min(44, plotWidth / data.length * .8 / keys.length);
  return <><div className="admin-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${config.type} chart`}>
    {[0, 1, 2, 3, 4].map((step) => {
      const value = min + (max - min) * step / 4;
      return <g key={step}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke="var(--line)" /><text x={left - 8} y={y(value) + 4} textAnchor="end" fontSize="11" fill="currentColor">{Number(value.toFixed(1))}</text></g>;
    })}
    {data.map((row, index) => index % Math.max(1, Math.ceil(data.length / 6)) === 0 && <text key={index} x={x(index)} y={height - 18} textAnchor="middle" fontSize="11" fill="currentColor">{String(row[config.x]).slice(0, 18)}</text>)}
    {keys.map((key, series) => config.type === 'line'
      ? <g key={key}>{data.map((row, index) => row[key] != null && <React.Fragment key={index}>{index > 0 && data[index - 1][key] != null && <line x1={x(index - 1)} x2={x(index)} y1={y(data[index - 1][key])} y2={y(row[key])} stroke={COLORS[series % COLORS.length]} strokeWidth="2" />}<circle cx={x(index)} cy={y(row[key])} r="2" fill={COLORS[series % COLORS.length]}><title>{`${row[config.x]} · ${key}: ${row[key]}`}</title></circle></React.Fragment>)}</g>
      : <g key={key}>{data.map((row, index) => row[key] != null && <rect key={index} x={x(index) + (series - keys.length / 2) * barWidth} y={Math.min(y(row[key]), y(0))} width={Math.max(1, barWidth - 1)} height={Math.abs(y(row[key]) - y(0))} fill={COLORS[series % COLORS.length]}><title>{`${row[config.x]} · ${key}: ${row[key]}`}</title></rect>)}</g>)}
  </svg><div className="admin-legend">{keys.map((key, index) => <span key={key}><i style={{ background: COLORS[index % COLORS.length] }} />{key}</span>)}</div></div><DataRow title="Results" value={`${rows.length} rows`}>{table}</DataRow></>;
}
