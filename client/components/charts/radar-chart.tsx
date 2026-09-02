"use client";

import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart as RechartsRadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

export interface RadarChartDatum {
  subject: string;
  candidate: number;
  required: number;
}

interface CompetencyRadarChartProps {
  data: ReadonlyArray<RadarChartDatum>;
  className?: string;
}

export function CompetencyRadarChart({
  data,
  className,
}: CompetencyRadarChartProps) {
  return (
    <div className={className} role="img" aria-label="Competency radar chart">
      <ResponsiveContainer width="100%" height="100%">
        <RechartsRadarChart data={[...data]} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="rgba(148, 163, 184, 0.25)" />
          <PolarAngleAxis
            dataKey="subject"
            tick={{ fill: "#94a3b8", fontSize: 12 }}
          />
          <PolarRadiusAxis
            angle={30}
            domain={[0, 100]}
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
          />
          <Radar
            name="Candidate"
            dataKey="candidate"
            stroke="#8b5cf6"
            fill="#8b5cf6"
            fillOpacity={0.35}
            strokeWidth={2}
          />
          <Radar
            name="Required"
            dataKey="required"
            stroke="#3b82f6"
            fill="transparent"
            strokeWidth={2}
          />
          <Legend
            wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }}
            iconType="circle"
          />
          <Tooltip
            contentStyle={{
              background: "#12121a",
              border: "1px solid rgba(30, 41, 59, 0.9)",
              borderRadius: "12px",
              color: "#fff",
            }}
          />
        </RechartsRadarChart>
      </ResponsiveContainer>
    </div>
  );
}
