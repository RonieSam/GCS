import React, { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';
import { api } from '../api/client';

interface TelemetryPoint {
  timestamp: string;
  temperature_c: number | null;
  pressure_hpa: number | null;
  imu_jerk: number | null;
}

interface NodeTelemetryChartProps {
  nodeId: string;
}

export const NodeTelemetryChart: React.FC<NodeTelemetryChartProps> = ({ nodeId }) => {
  const [data, setData] = useState<TelemetryPoint[]>([]);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const pts = await api.getNodeTelemetry(nodeId, 50);
        if (mounted) {
          // Format timestamps for display
          const formatted = pts.map(p => ({
            ...p,
            timeLabel: new Date(p.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
          }));
          setData(formatted);
        }
      } catch (err) {
        console.error(err);
      }
    };

    load();
    const interval = setInterval(load, 3000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [nodeId]);

  if (!data || data.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 mt-4">
      {/* Environment Chart */}
      {(data[data.length - 1].temperature_c != null) && (
        <div className="p-3 border border-subtle rounded-sm bg-surface">
          <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2">
            Environment History
          </div>
          <div style={{ height: '200px', width: '100%', minHeight: '200px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                <XAxis dataKey="timeLabel" stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                <YAxis yAxisId="left" domain={['dataMin - 1', 'dataMax + 1']} stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                <YAxis yAxisId="right" orientation="right" domain={['dataMin - 1', 'dataMax + 1']} stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                <Tooltip contentStyle={{ backgroundColor: 'var(--bg-surface-elevated)', border: '1px solid var(--border-subtle)' }} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: '10px' }} />
                <Line yAxisId="left" type="monotone" dataKey="temperature_c" name="Temp (°C)" stroke="#fbbf24" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="right" type="monotone" dataKey="pressure_hpa" name="Pressure (hPa)" stroke="#3b82f6" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* IMU Jerk Chart */}
      {(data[data.length - 1].imu_jerk != null) && (
        <div className="p-3 border border-subtle rounded-sm bg-surface">
          <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2">
            IMU Jerk (Physical Activity)
          </div>
          <div style={{ height: '200px', width: '100%', minHeight: '200px', marginTop: '10px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                <XAxis dataKey="timeLabel" stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                <YAxis stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                <Tooltip contentStyle={{ backgroundColor: 'var(--bg-surface-elevated)', border: '1px solid var(--border-subtle)' }} />
                <Line type="stepAfter" dataKey="imu_jerk" name="Jerk" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
};
