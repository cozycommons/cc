import React from 'react';
import { CalendarDays, CloudDrizzle, CloudRain, Snowflake, ThermometerSnowflake, TriangleAlert } from 'lucide-react';

const ICONS = { drizzle: CloudDrizzle, rain: CloudRain, 'heavy rain': CloudRain, snow: Snowflake };

// Why this hour is unlike an average one (weather, holiday), and Citi Bike's own alerts.
// Shown only when there is something to say; the API words the note.
export default function Conditions({ conditions }) {
  if (!conditions) return null;
  const { note, alerts = [], weather } = conditions;
  if (!note && !alerts.length) return null;
  const Icon = (weather && ICONS[weather.sky])
    || (weather && (weather.snow_72h_cm >= 2 ? Snowflake : weather.temp_c < 0 ? ThermometerSnowflake : null))
    || CalendarDays;
  return (
    <div className="bk-conditions" role="status">
      {note && <p><Icon size={18} aria-hidden="true" /><span>{note}</span></p>}
      {alerts.map((alert) => (
        <p key={alert.summary} className="is-alert"><TriangleAlert size={18} aria-hidden="true" /><span>{alert.summary}</span></p>
      ))}
    </div>
  );
}
